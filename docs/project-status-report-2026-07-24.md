# MusicSync 项目现状完整报告

> 生成日期：2026-07-24 | 版本：v0.3.0 | 分支：main (干净)

---

## 1. 产品概述

MusicSync 是一个 **Windows 桌面应用**，用于在 PC 与 Android 手机之间通过 USB ADB 进行**单向镜像音乐文件夹同步**。用户选择源路径（标准库）和目的路径（被同步对象），程序扫描比对后展示差异列表，用户逐项勾选确认后执行同步。

**核心原则：**
- 严格单向镜像（源 → 目的），无冲突裁决
- 相对路径作匹配键，支持 PC/Phone 混合场景
- 纯文件对比，不读音乐标签、不比较修改时间
- 绿色便携，一个文件夹即用即删

**当前状态：** 开发中，已完成核心功能闭环，v0.3.0 可分发版本已打包完成。

---

## 2. 技术栈

| 层面 | 技术选型 |
|------|----------|
| 语言 | Python 3.x |
| GUI | PySide6 >= 6.5 (Qt for Python) |
| 数据库 | SQLite (标准库, WAL 模式) |
| 手机通信 | `adb_device_kit` — 零依赖 ADB 封装工具包 |
| 打包 | PyInstaller `--onedir` + 随包 `adb.exe` |
| 平台 | Windows 10/11 仅 |

**外部依赖仅两个：** `PySide6`（必须）+ `send2trash`（可选，回退到备份目录）。

---

## 3. 架构全景

```
main.py                          — 入口，设置 faulthandler + 日志 + QApplication
musicsync/
├── adb_device_kit/              — ★ 独立工具包（零外部依赖，v1.0.0 MIT）
│   ├── cancel_flag.py           — CancelFlag (threading.Event 封装)
│   ├── device.py                — Device 类（ADB 全操作：detect/list/stat/push/pull/delete/hash）
│   ├── executor_helpers.py     — transfer_with_verify / safe_delete_local / safe_delete_remote
│   ├── filter_utils.py         — AudioFilter / parse_musicignore / matches_any_rule
│   ├── hash_utils.py           — quick_hash() / compute_local_hash()
│   ├── models.py               — FileInfo / SkippedInfo / ScanResult / ActionResult
│   └── tests/                  — 单元测试（mock + 真机集成测试）
├── core/
│   ├── models.py               — DiffItem（差异项数据类）
│   ├── sync_engine.py          — scan() / compare() 纯函数管道
│   └── executor.py             — execute() 单函数，设备调度分发
├── store/
│   └── database.py             — SQLite 持久化层（WAL 模式）
├── ui/
│   ├── main_window.py          — MainWindow + 4 状态 FSM
│   ├── dir_bar.py              — 源/目的双路径选择器
│   ├── diff_view.py            — 差异列表（按操作类型分 Tab）
│   ├── history_view.py         — 操作历史（筛选 + 分页）
│   ├── status_bar.py           — 进度条 + 中文阶段标签
│   ├── workers.py              — ScanWorker / CompareWorker / ExecuteWorker
│   └── utils.py                — 日志设置 / get_app_dir / get_adb_path
└── tests/                      — 集成测试 + UI 测试
```

### 分层设计

```
UI 层 (PySide6)
  ↕ Signal/Slot + QThread
Workers 层 (ScanWorker / CompareWorker / ExecuteWorker)
  ↕ 纯函数调用
Core 层 (sync_engine.py / executor.py)
  ↕ 数据模型传递
ADB Kit 层 (Device, Hash, Filter, ...)
  ↕ subprocess 调用
操作系统 / ADB
```

---

## 4. 三大设备组合

| 组合 | 场景 |
|------|------|
| PC → Phone | PC 标准库同步到手机（最常用） |
| Phone → PC | 手机新歌汇集到 PC |
| PC → PC | 两个本地文件夹同步 |

Phone → Phone 明确不支持。

---

## 5. 核心逻辑详解

### 5.1 扫描 (scan)

```python
def scan(root_path, device_type, audio_filter, device, cancel_flag) -> tuple[list[FileInfo], SkippedInfo]
```

- **PC 端**：`os.walk` + `AudioFilter` 过滤，提取根路径前缀构造相对路径
- **Phone 端**：单次 `find -printf '%s|%p\n'`（比旧版 N+1 查询快 ~100x）
- 非音频文件自动跳过，底部显示统计摘要

### 5.2 比对 (compare)

```python
def compare(source_files, dest_files, cancel_flag) -> list[DiffItem]
```

**两层策略——完全不使用修改时间 (mtime)：**

| 层级 | 条件 | 判定 | I/O 成本 |
|------|------|------|----------|
| 快速路径 | 相对路径匹配 + 大小相同 | `synced`（跳过，不展示） | 0 |
| 确认路径 | 相对路径匹配 + 大小不同 | `updated_in_dest`（直接标记覆盖） | 0 |
| — | 仅在源端 | `new_in_dest`（复制到目的） | 0 |
| — | 仅在目的端 | `only_in_dest`（从目的删除） | 0 |

**关键设计决策：** 比对阶段**不计算哈希**——因为 `quick_hash()` 本身含了 `file_size`，不同大小的文件必然产生不同哈希，哈希检查是死代码。（详见 memory/compare-hash-redundant-removal.md）

### 5.3 执行 (execute)

```python
def execute(diff_items, source_config, dest_config, cancel_flag) -> ActionResult
```

**传输阶段才有哈希验证：**

```
For each selected DiffItem:
  ┌─ copy/overwrite ──────────────┐
  │ 1. 计算源端 quick_hash        │
  │ 2. push/pull/shutil.copy2     │
  │ 3. 计算目的端 quick_hash      │
  │ 4. 比对 → 不匹配 → 重试 1 次  │
  │ 5. 仍失败 → 标记失败          │
  └───────────────────────────────┘

  ┌─ delete ──────────────────────┐
  │ PC端:  send2trash → 失败时回退到 backup_dir  │
  │ Phone: pull 备份 → quick_hash 验证 → rm → stat 确认 │
  └───────────────────────────────┘
```

### 5.4 快速哈希算法

```
SHA-256(文件前 64KB + 文件后 64KB + str(文件大小))
```

- I/O 成本从全文件降至 ~128KB
- ADB 远程文件通过 `adb exec-out dd iflag=count_bytes,skip_bytes` 二进制安全读取
- 绕过 PTY 伪终端避免 `\n` → `\r\n` 数据损坏

### 5.5 线程模型

| Worker | 线程 | 职责 |
|--------|------|------|
| ScanWorker | QThread #1 | 扫描源端 → 扫描目的端 |
| CompareWorker | QThread #2 | 比对两端的 FileInfo 列表 |
| ExecuteWorker | QThread #3 | 逐个执行复制/覆盖/删除 |

- 取消信号：`CancelFlag`（`threading.Event` 封装），三级降级：poll → quit → terminate
- closeEvent 优雅关闭，3 秒超时
- 跨线程传递使用 `copy.deepcopy()` 保证线程隔离

---

## 6. 数据库设计

SQLite 单文件 `musicsync.db`，位于应用目录，WAL 模式。

### 4 张表

| 表名 | 用途 | 类型 |
|------|------|------|
| `operation_history` | 操作记录持久化 | 持久 |
| `app_settings` | KV 配置（音频扩展名、musicignore 开关） | 持久 |
| `remembered_paths` | 路径记忆（下拉补全） | 持久 |
| `session_diff` | 会话差异临时存储（程序关闭自动清空） | 临时 |

所有表无外键、自包含记录，查询无需 JOIN。

---

## 7. 文件统计

| 类别 | 数量 |
|------|------|
| 源代码文件 (Python) | 30+ |
| 单元测试文件 (`adb_device_kit/tests/`) | 5 |
| 集成/UI 测试文件 (`musicsync/tests/`) | 11 |
| UI 组件 | 7 |
| 文档文件 (README/PRD/ADR/MEMORY/memory/*.md) | 15+ |
| 配置文件 (.gitignore / CLAUDE.md / .claude/) | 4 |

---

## 8. 文档资产

| 文件 | 内容 |
|------|------|
| [README.md](README.md) | 用户文档：安装、使用、架构图、测试命令 |
| [PRD.md](PRD.md) | 产品需求文档 (567 行)：23 个用户故事、领域模型、技术决策 12 条、DB DDL |
| [CONTEXT.md](CONTEXT.md) | 领域术语表（18 个术语） |
| [CLAUDE.md](CLAUDE.md) | AI Agent 项目指南 |
| [MEMORY.md](MEMORY.md) | 经验教训索引（7 条） |
| [MusicSync.spec](MusicSync.spec) | PyInstaller 打包配置 |
| `docs/adr/0001-increment2-phone-adb-architecture.md` | 架构决策记录 |
| `memory/` (7 个 .md) | Bug 根因 + 设计决策详细记录 |

---

## 9. Git 近期历史 (最近 10 次提交)

| Hash | 日期 | 消息 |
|------|------|------|
| 42e9cc3 | 2026-07-23 | **feat:** PyInstaller --onedir 绿色便携打包 |
| 2cb3d7a | 2026-07-23 | **feat:** HistoryView 重构 — 筛选工具栏 + 日期分隔行 + 分页 |
| bbb3ee9 | 2026-07-23 | **fix:** Phone 端删除备份从系统 Temp 迁至程序目录 backups/ |
| 0c72f09 | 2026-07-23 | **fix:** 操作历史时间戳偏移 + 记录"丢失"修复 |
| 8e34566 | 2026-07-23 | **refactor:** remove redundant hash comparison from compare() |
| 8d0378a | 2026-07-23 | **feat:** Phone select ADB detection + button disable + re-check |
| 5c81fc6 | 2026-07-23 | **fix:** Operation history 5 bugs |
| 664497c | 2026-07-20 | **fix:** Phone scan 3 bugs — pipe deadlock + N+1 query + silent error swallowing |
| 7640110 | 2026-07-20 | **fix:** Phone-to-PC all failures — 3 root causes fixed |
| b256914 | 2026-07-20 | **feat:** Auto re-compare after sync completion + summary dialog |

**近期趋势：** 7/20-7/23 为密集开发与修复期，聚焦 Phone→PC pull 链路 bug、操作历史可靠性、Pipe deadlock、以及最终的可分发打包。

---

## 10. 已知经验教训 (memory/)

| 主题 | 要点 |
|------|------|
| [GUI Emoji 布局教训](memory/gui-emoji-layout-lessons.md) | Qt 中 emoji 渲染不稳定，deleteLater 跨线程访问触发 RuntimeError |
| [Phone→PC pull 三重根因](memory/phone-to-pc-pull-failure-roots.md) | 路径截断 + adb stderr + 闭包遮蔽导致全链路失败 |
| [Signal(int) 溢出](memory/pyside6-signal-int-overflow.md) | Signal 映射 C++ signed 32-bit，>2.1GB 值需改为 Signal(object) |
| [操作历史 5 项 Bug](memory/operation-history-five-bugs.md) | 静默丢 delete 操作、硬编码假标签、字段语义不足、变量名误导 |
| [时间戳偏移+记录丢失](memory/operation-history-timezone-and-silent-failure.md) | UTC 未转本地差 8h + LIMIT 50 截断 + except:pass 吞错 |
| [compare 哈希冗余](memory/compare-hash-redundant-removal.md) | quick_hash 含 file_size 使比对阶段哈希为死代码，移除零回归 |
| [备份绿色便携](memory/phone-backup-green-portable.md) | 备份目录从系统 Temp 迁至程序目录，全审计零用户目录污染 |

---

## 11. 测试覆盖现状

### adb_device_kit 单元测试 (mock + 真机)

| 模块 | 用例数 | 覆盖 |
|------|--------|------|
| cancel_flag | 7 | 基本操作、多线程竞态 |
| hash | 11 | quick_hash 确定性/区分性/SHA-256格式/边界/已知向量 |
| filter | 25 | musicignore 解析、glob 规则、AudioFilter 全流程、real-world 场景 |
| device | mock + 集成 | detect/list/stat/push/pull/delete/free_space |
| pipe deadlock | 5 | 128KB 输出不阻塞、cancel 响应、timeout 触发 |

### musicsync 集成测试

| 测试文件 | 覆盖范围 |
|----------|----------|
| test_sync_engine_scan.py | scan 纯函数逻辑 |
| test_sync_engine_compare.py | compare 四种差异判定 |
| test_executor.py | execute 分发逻辑 |
| test_executor_device.py | 设备组合 dispatch |
| test_workers.py | Worker 线程化 |
| test_database.py | CRUD 操作 |
| test_diff_view.py | 差异视图 |
| test_dir_bar.py | 路径选择器 |
| test_cli_device.py | CLI 设备参数 |
| test_integration_phone.py | 真机端到端 |

**测试原则：** ADB 相关测试必须连接真实设备执行，不使用 mock 替代 ADB 交互。

---

## 12. 关键约束清单

| 约束 | 说明 |
|------|------|
| 仅 Windows 10/11 | 不跨平台 |
| 仅 USB ADB | 无 MTP、无网络传输 |
| 仅单台设备 | 不支持同时多台 ADB 设备 |
| 单向同步 | 无双向、无冲突裁决 |
| 音频白名单 | FLAC/MP3/WAV/AAC/OGG/M4A/WMA |
| `.musicignore` | 排除规则（语法同 .gitignore） |
| 零外部依赖 (adb_device_kit) | 仅用 Python 标准库 |
| 绿色便携 | `adb.exe` 随 PyInstaller 打包 |

---

## 13. 待办 & 可能的改进方向

基于当前状态分析：

1. **测试覆盖** — `musync/__init__.py` 和 `core/__init__.py` 为空文件（占位符），可考虑统一清理
2. **版本号** — GUI 显示 v0.3.0，但 README 最后更新仍标注 2026-07-23
3. **打包分发** — PyInstaller `--onedir` 已完成，但缺少 installer / updater 机制
4. **进度反馈** — execute 阶段有逐文件进度，但长时间操作缺少预估剩余时间
5. **Android 端默认路径** — 硬编码 `//sdcard/Music/`，可考虑支持用户自定义

---

*报告结束。如需深入某个子系统的细节，可随时查看对应源码或 MEMORY.md 中的详细记录。*
