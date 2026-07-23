# MusicSync — 单向镜像音乐文件夹同步工具

> Windows 桌面应用。选择源路径与目的路径，按相对路径比对两端，用户确认后执行镜像同步。支持 PC ↔ Android（ADB）三种设备组合。操作历史持久化。

**状态**: 开发中 &nbsp;|&nbsp; **更新**: 2026-07-23

---

## 目录

1. [产品概述](#1-产品概述)
2. [用户场景与故事](#2-用户场景与故事)
3. [领域模型](#3-领域模型)
4. [同步规则](#4-同步规则)
5. [架构设计](#5-架构设计)
6. [数据库设计](#6-数据库设计)
7. [核心流程](#7-核心流程)
8. [GUI 设计](#8-gui-设计)
9. [技术决策](#9-技术决策)
10. [测试策略](#10-测试策略)
11. [范围边界](#11-范围边界)
12. [依赖与工具包](#12-依赖与工具包)

---

## 1. 产品概述

MusicSync 帮助用户在 Windows PC 与 Android 手机之间维护一致的音乐文件库。用户指定**源路径**（标准库）和**目的路径**（被同步对象），程序扫描两端文件、按相对路径匹配、展示差异列表、用户逐项勾选确认后执行镜像同步。

### 核心原则

- **单向镜像** — 源为参照标准，目的被改造为与源完全一致。不存在反向复制或冲突裁决。
- **相对路径作身份** — 文件由相对路径标识，根路径前缀被剥离。两端根路径等价。
- **纯文件对比** — 比对仅依赖文件大小匹配，不读取音乐标签和文件内容。
- **用户最终决定** — 所有差异项展示给用户，用户勾选确认后才执行，不自动操作。
- **绿色便携** — 一个文件夹即用即删，数据库和日志均在应用目录内。

### 典型使用方式

```
PC 已整理好的标准库 (E:\Music\)
        ↓ 镜像同步（USB ADB）
手机音乐目录 (//sdcard/Music/)
```

### 支持的三种设备组合

| 源端 | 目的端 | 场景 |
|------|--------|------|
| PC | Phone | PC 标准库同步到手机 |
| Phone | PC | 手机新歌汇集到 PC |
| PC | PC | 两个本地文件夹同步 |

---

## 2. 用户场景与故事

### 路径选择与设备连接

| # | 故事 |
|---|------|
| 1 | 两个独立的路径选择器分别设置源和目的，每个均可选 PC 或 Phone 设备类型 |
| 2 | 选择 Phone 时自动检测 ADB 设备并预填 `/sdcard/Music/`，未检测到时禁用"开始比对"按钮并显示配置指引（含"重新检测"按钮供用户手动刷新设备状态） |
| 3 | 历史选过的路径（含设备类型）自动记住，下拉列表快速选择 |
| 4 | 两个路径均填写完毕后"开始比对"按钮才可用 |

### 扫描与比对

| # | 故事 |
|---|------|
| 5 | 点击"开始比对"后显示分阶段进度：扫描源端 → 扫描目的端 → 比对分析 |
| 6 | 相对路径匹配 + 文件大小相同 → 直接判定"一致"，不展示，不比较修改时间 |
| 7 | 相对路径匹配 + 文件大小不同 → 直接标记为源覆盖目的（比对阶段不哈希；哈希验证在传输阶段进行） |
| 8 | 比对过程中可随时取消 |
| 9 | 非音频文件在扫描阶段自动跳过，底部显示"已跳过 N 个非音频文件" |
| 10 | 支持 `.musicignore` 文件做排除规则（语法同 `.gitignore`） |

### 差异审核

| # | 故事 |
|---|------|
| 11 | 差异按操作类型分标签页展示：复制到目的 / 覆盖目的 / 从目的删除 |
| 12 | 每行含复选框（默认勾选）、文件名（相对路径）、两端大小和时间、操作方向 |
| 13 | 底部状态栏实时显示"共 N 项差异 \| 已勾选 M 项 \| 预估传输量" |

### 执行同步

| # | 故事 |
|---|------|
| 14 | 逐文件进度："正在复制 VOCALOID/song.flac → 目的端 (28MB) [3/18]" |
| 15 | 传输后自动哈希校验，不一致时重试 1 次，仍失败标记失败并列出 |
| 16 | 删除 PC 端文件送入回收站（send2trash），不可用时回退到备份目录 |
| 17 | 删除手机端文件先 pull 备份到 PC `MusicSync_backup/` → 验证 → 再 rm |
| 18 | 执行过程中可随时取消，已完成的操作已写入历史 |

### 操作历史

| # | 故事 |
|---|------|
| 19 | 每次同步操作的完整记录可查：时间、操作类型、方向、文件路径、两端路径、设备类型、大小 |
| 20 | 操作历史按时间倒序排列 |

### 通用体验

| # | 故事 |
|---|------|
| 21 | 绿色便携，无需安装，拷贝文件夹即用 |
| 22 | 错误按严重程度用颜色区分（黄色警告 / 橙色错误 / 红色致命），附带可操作建议 |
| 23 | 关闭程序时临时数据自动清理，持久化数据完整保留 |

---

## 3. 领域模型

### 核心概念

#### 源路径与目的路径

- **源路径**: 同步的参照标准，用户认为"这是对的"那一端
- **目的路径**: 被同步的对象，将被改造为与源一致

各可独立选择 PC 本地目录或 Android ADB 路径。

#### 设备类型

| 值 | 含义 |
|----|------|
| `pc` | Windows 本地文件系统 |
| `phone` | 通过 ADB 连接的 Android 设备 |

#### 镜像同步

严格单向策略：源为参照标准，目的被改造为与源一致。方向始终从源流向目的。

#### 相对路径

文件相对于根路径的后缀部分。是比对阶段匹配两端文件的**唯一键**。统一使用正斜杠（`/`）。

```
源根路径:    E:\Music\
文件全路径:   E:\Music\VOCALOID\song.flac
相对路径:     VOCALOID/song.flac

目的根路径:   //sdcard/Music/
文件全路径:   //sdcard/Music/VOCALOID/song.flac
相对路径:     VOCALOID/song.flac

→ 两端相对路径相同 → 视为同一文件
```

#### 混合比对

两层策略，**不比较修改时间**（跨文件系统 mtime 不可靠）：

| 层级 | 条件 | 判定 | I/O |
|------|------|------|-----|
| 快速路径 | 相对路径匹配 + 大小相同 | 一致，跳过 | 无 |
| 确认路径 | 相对路径匹配 + 大小不同 | 直接覆盖（比对阶段不哈希） | 无 |

#### 快速哈希

```
SHA-256(文件前 64KB + 文件后 64KB + str(文件大小))
```

只读头尾各 64KB，避免全文件哈希的 I/O 成本。文件大小作为哈希输入的一部分，确保不同大小的文件绝对产生不同哈希值。

ADB 远程文件通过 `adb exec-out dd iflag=count_bytes,skip_bytes` 读取二进制片段，绕过 PTY 伪终端避免数据损坏。

#### 差异类型

| 类型 | 条件 | 操作 | 方向 |
|------|------|------|------|
| `synced` | 两端都有、大小相同 | (不展示) | — |
| `new_in_dest` | 源有、目的无 | `copy_to_dest` | source → dest |
| `updated_in_dest` | 两端都有、大小不同 | `overwrite_dest` | source → dest |
| `only_in_dest` | 目的有、源无 | `delete_from_dest` | dest |

### 数据结构

#### FileInfo — 文件元数据快照

| 字段 | 类型 | 说明 |
|------|------|------|
| `path` | `str` | 文件完整路径 |
| `relative_path` | `str` | 相对路径（匹配键） |
| `size` | `int \| None` | 文件大小（字节） |
| `modified` | `str \| None` | ISO 8601 修改时间（仅用于 UI 展示，不参与比对） |
| `hash` | `str \| None` | 快速哈希值（按需计算） |

#### DiffItem — 差异项

| 字段 | 类型 | 说明 |
|------|------|------|
| `relative_path` | `str` | 文件相对路径 |
| `diff_type` | `str` | `new_in_dest` / `updated_in_dest` / `only_in_dest` |
| `operation` | `str` | `copy_to_dest` / `overwrite_dest` / `delete_from_dest` |
| `direction` | `str` | 操作方向描述 |
| `source_size` | `int \| None` | 源端文件大小 |
| `dest_size` | `int \| None` | 目的端文件大小 |
| `source_modified` | `str \| None` | 源端修改时间（仅展示） |
| `dest_modified` | `str \| None` | 目的端修改时间（仅展示） |
| `selected` | `bool` | UI 中是否勾选（默认 `True`） |

---

## 4. 同步规则

### 文件匹配

两端文件通过**相对路径字符串完全相等**进行匹配。根路径前缀在扫描阶段剥离，在执行阶段重新拼接。

### 差异判定

```
For each 相对路径:

  两端都存在:
    if src.size == dst.size → synced (跳过，不比较 mtime)
    if src.size != dst.size → 计算两端快速哈希 → updated_in_dest (源覆盖目的)

  仅在源端 → new_in_dest → 复制到目的
  仅在目的端 → only_in_dest → 从目的删除
```

### 执行操作

| operation | 行为 | 校验 |
|-----------|------|------|
| `copy_to_dest` | 源端文件传输到目的端 | 传输后哈希校验，失败重试 1 次 |
| `overwrite_dest` | 源端文件覆盖目的端同名文件 | 同上 |
| `delete_from_dest` | 删除目的端文件 | PC: send2trash；手机: 先备份后 rm + stat 确认 |

---

## 5. 架构设计

### 分层结构

```
main.py              — 入口
musicsync/
  ui/                  — PySide6 界面层
    main_window.py     — 三面板主窗口
    dir_bar.py         — 源/目的双路径选择器
    diff_view.py       — 差异列表（按操作类型分标签页）
    history_view.py    — 操作历史
    status_bar.py      — 底部状态栏
    workers.py         — ScanWorker / CompareWorker / ExecuteWorker
    utils.py           — 共享工具函数
  core/                — 核心逻辑层
    models.py          — 数据类 + CancelFlag
    device.py          — ADB 设备层（由 adb_device_kit 提供）
    filter.py          — 文件过滤（白名单 + .musicignore）
    sync_engine.py     — scan / compare 纯函数管道（比对阶段不哈希）
    executor.py        — 同步执行（传输 + 校验 + 重试 + 安全删除）
  store/               — 持久化层
    database.py        — SQLite 建表 + CRUD + derive_status()
```

### 技术栈

| 层 | 技术 |
|----|------|
| 语言 | Python 3.x |
| GUI | PySide6（Qt for Python） |
| 数据库 | SQLite（标准库 `sqlite3`，WAL 模式） |
| 手机通信 | adb_device_kit（ADB 封装工具包） |
| 打包 | PyInstaller `--onedir`，`adb.exe` 随包分发 |
| 平台 | Windows 10/11 + Android（ADB） |

### 实现顺序

自底向上，每层独立验证后进入下一层：

1. `store/database.py`
2. `core/models.py`
3. `core/filter.py`
4. `core/device.py`
5. `core/sync_engine.py`
6. `core/executor.py`
7. `ui/workers.py`
8. `ui/` 全部组件 + `main.py`

### 线程模型

- QThread + QObject Worker + Signal/Slot
- 三个 Worker（Scan / Compare / Execute）各自独立线程
- CancelFlag（`threading.Event` 封装）跨线程传递取消信号
- closeEvent 中优雅关闭（等待线程结束，3 秒超时）

---

## 6. 数据库设计

SQLite 单文件（`musicsync.db`），位于应用同目录。WAL 模式，`check_same_thread=False`。

### 表结构

#### operation_history（持久化）

```sql
CREATE TABLE operation_history (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path         TEXT NOT NULL,
    dest_path           TEXT NOT NULL,
    device_type_source  TEXT NOT NULL CHECK(device_type_source IN ('pc','phone')),
    device_type_dest    TEXT NOT NULL CHECK(device_type_dest IN ('pc','phone')),
    action_type         TEXT NOT NULL CHECK(action_type IN ('copy','overwrite','delete')),
    direction           TEXT NOT NULL,
    relative_path       TEXT NOT NULL,
    file_size           INTEGER NOT NULL,
    timestamp           TEXT NOT NULL
);
CREATE INDEX idx_op_history_timestamp ON operation_history(timestamp DESC);
```

每条记录自包含完整信息，查询无需 JOIN。

#### remembered_paths（持久化）

```sql
CREATE TABLE remembered_paths (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    device_type TEXT NOT NULL CHECK(device_type IN ('pc','phone')),
    path        TEXT NOT NULL,
    role        TEXT NOT NULL CHECK(role IN ('source','dest')),
    last_used   TEXT NOT NULL,
    UNIQUE(device_type, path, role)
);
```

`INSERT OR REPLACE` 去重，按 `last_used DESC` 排序。

#### session_diff（临时，关闭清空）

```sql
CREATE TABLE session_diff (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    relative_path TEXT NOT NULL,
    operation     TEXT NOT NULL CHECK(operation IN (
                      'copy_to_dest','overwrite_dest','delete_from_dest')),
    direction     TEXT NOT NULL,
    file_size     INTEGER,
    modified_time TEXT
);
```

程序关闭时 `DELETE FROM session_diff`，保留表结构。

#### app_settings（持久化）

```sql
CREATE TABLE app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO app_settings (key, value) VALUES
  ('audio_extensions', '["flac","mp3","wav","aac","ogg","m4a","wma"]'),
  ('musicignore_enabled', 'true');
```

### derive_status() 纯函数

```python
def derive_status(source_size, dest_size,
                  source_hash=None, dest_hash=None) -> str:
    """返回 synced | new_in_dest | updated_in_dest | only_in_dest"""
```

---

## 7. 核心流程

### 7.1 扫描（scan）

```python
def scan(root_path, device_type, audio_filter, device, cancel_flag) -> list[FileInfo]:
```

- `pc`: `os.walk` + `os.stat` 遍历本地
- `phone`: `device.list_files()` + `device.stat()` 获取远程文件
- 剥离根路径前缀构造 `relative_path`
- 经 `audio_filter.filter()` 排除非音频文件
- 每约 50 个文件报告一次进度

### 7.2 比对（compare）

```python
def compare(source_files, dest_files, cancel_flag) -> CompareResult:
    src_index = {f.relative_path: f for f in source_files}
    dst_index = {f.relative_path: f for f in dest_files}

    for rel_path in sorted(all_paths):
        if rel_path in both:
            if src.size == dst.size → synced (skip)
            if src.size != dst.size → updated_in_dest
        elif only in source → new_in_dest
        elif only in dest   → only_in_dest
```

### 7.3 哈希计算

哈希仅在 **执行阶段** 使用（比对阶段不计算哈希）：

- `transfer_with_verify()` — 传输后源端 vs 目的端哈希比对，确保完整性
- `safe_delete_remote()` — 删除 Phone 文件前，先 pull 备份 → 哈希验证 → 再删除

| 源 | 目的 | 源哈希方式 | 目的哈希方式 |
|----|------|-----------|-------------|
| PC | Phone | `compute_local_hash(path, size)` | `quick_hash(*device.read_head_tail(path), size)` |
| Phone | PC | `quick_hash(*device.read_head_tail(path), size)` | `compute_local_hash(path, size)` |
| PC | PC | `compute_local_hash` | `compute_local_hash` |

### 7.4 执行（execute）

```
For each diff where diff.selected:

  copy_to_dest / overwrite_dest:
    1. 源端哈希
    2. 传输（push / pull / shutil.copy2）
    3. 目的端哈希
    4. 比对 → 不匹配 → 重试 1 次 → 仍失败 → 标记失败
    5. 成功 → 写入 operation_history

  delete_from_dest:
    PC:   send2trash → 失败回退到备份目录
    Phone: pull 备份 → 本地验证哈希 → rm → stat 确认
    成功 → 写入 operation_history
```

---

## 8. GUI 设计

### 布局

```
┌─────────────────────────────────────────────────────────┐
│  源 [PC ▼] [________路径________] [浏览]                 │
│  目的 [Phone ▼] [______路径______] [浏览]    [开始比对]   │
│  ⚠ 未检测到 Android 设备。请确认 USB 连接…   [重新检测]   │
├─────────────────────────────────────────────────────────┤
│  [复制到目的] [覆盖目的] [从目的删除] │ [操作历史]       │
│  ┌─────────────────────────────────────────────────┐    │
│  │ ☑ VOCALOID/song.flac   复制   源→目的    28MB   │    │
│  │ ☑ Artist/album.mp3     覆盖   源→目的    15MB   │    │
│  │ ☑ Archive/old.flac     删除   从目的     8MB   │    │
│  └─────────────────────────────────────────────────┘    │
├─────────────────────────────────────────────────────────┤
│  [=========进度条=========] 共 18 项 | 已勾选 15 项      │
│                                    [执行同步]  [取消]    │
└─────────────────────────────────────────────────────────┘
```

### 交互细节

- **差异标签页**：按操作类型分三组，每行复选框默认勾选
- **跳过提示**：底部显示"已跳过 N 个非音频文件"，可点击查看详情
- **操作历史**：`operation_history` 表按时间倒序，平铺列表
- **路径记忆**：`remembered_paths` 表填充下拉选项

---

## 9. 技术决策

| # | 决策 | 理由 |
|---|------|------|
| 1 | 严格单向镜像（源→目的） | 用户始终以一端为标准库，双向模型是过度设计 |
| 2 | 相对路径作匹配键，剥离根前缀 | 消除"路径等价 bug"——E:\Music\a.flac 与 //sdcard/Music/a.flac 应被视为同一文件 |
| 3 | 比对不比较修改时间 | 跨文件系统（NTFS↔ext4/F2FS）mtime 不可靠；大小相同即判定一致 |
| 4 | 快速哈希：SHA-256(头64KB + 尾64KB + 大小) | 针对音乐文件结构优化，I/O 成本从全文件降为 ~128KB |
| 5 | ADB 用 exec-out + dd iflag 读取 | 绕过 PTY 伪终端的 `\n→\r\n` 转换，字节精度 skip_bytes/count_bytes |
| 6 | 3 持久表 + 1 临时表 | 无外键、自包含记录，查询无需 JOIN |
| 7 | 音频白名单（7 种格式）+ .musicignore | 自动过滤非音频杂文件，用户可按需排除 |
| 8 | PC 删除用 send2trash | 进回收站可恢复，不可用时回退到备份目录 |
| 9 | 手机删除先备份后 rm | ADB 无回收站，先 pull 到 PC 再删 |
| 10 | 传输后哈希校验 + 重试 1 次 | 防止静默数据损坏 |
| 11 | QThread + Worker + Signal/Slot | 保持 GUI 响应，正确管理线程生命周期 |
| 12 | PyInstaller --onedir | 绿色便携，无安装过程 |

---

## 10. 测试策略

### 原则

**所有测试必须连接真实 ADB 设备后执行。** 不使用 mock 替代 ADB 交互。mock 无法验证 `exec-out` 二进制安全性、`dd iflag` 字节精度以及真实设备的文件系统行为。

### 必测场景

| 类别 | 具体场景 |
|------|---------|
| ADB 全链路 | detect → get_device_info → list_files → stat → read_head_tail → push → pull → delete → get_free_space |
| 快速哈希 | 确定性、区分性、已知向量、小文件/大文件/边界 |
| 文件过滤 | 白名单、.musicignore 解析、glob/目录规则匹配、reset_skipped |
| 比对 | 大小相同→跳过、大小不同→直接覆盖、仅源端→复制、仅目的端→删除 |
| 传输校验 | 传输 + 哈希校验 + 失败重试 + 二次失败标记 |
| 安全删除 | PC: send2trash + 回退；手机: pull 备份→验证→rm→stat |
| 路径等价 | 同步后再次比对 → 0 差异 |
| 端到端 | PC→PC: 创建文件→比对→执行→再比对确认 |
| 端到端 | PC→Phone: 同步→再比对→手动删文件→比对显示差异→确认操作类型正确 |
| 取消标志 | 基本操作 + 多线程竞态 |

### 不测试的

- PySide6 组件布局（手动验证）
- 不存在的功能（标签比对、冲突检测、双向同步）

---

## 11. 范围边界

### 明确不做

| 项目 | 说明 |
|------|------|
| 音乐标签读取 | 不依赖 mutagen，不读标题/艺术家/封面/歌词 |
| 修改时间参与比对 | 比对完全不使用 mtime |
| 双向同步 | 不支持目的→源方向 |
| 冲突检测 | 源始终覆盖目的，无冲突概念 |
| 意图推断 | 不查询历史猜测用户意图 |
| 文件夹名模糊匹配 | 路径字符串不同即视为不同目录 |
| MTP | 仅 ADB |
| 非 Windows 平台 | 仅 Windows 10/11 |
| 自动同步 | 不监听文件系统事件 |
| 网络传输 | 仅 USB 直连 |
| 多手机 | 仅支持同时连接一台设备 |
| Phone→Phone | 不支持两台手机间直接同步（无法不经过 PC 中转） |

---

## 12. 依赖与工具包

### Python 依赖

```
PySide6>=6.5
send2trash          # 可选——未安装时自动回退到备份目录
```

### adb_device_kit

项目直接使用 `adb_device_kit` 工具包进行所有 ADB 通信。该工具包提供：

| 模块 | 提供的能力 |
|------|-----------|
| `Device` | ADB 设备检测、文件枚举、stat、read_head_tail（二进制安全）、push/pull、delete、空间查询 |
| `quick_hash` / `compute_local_hash` | 快速哈希计算 |
| `AudioFilter` / `parse_musicignore` | 音频文件过滤 + .musicignore 规则 |
| `transfer_with_verify` / `safe_delete_local` / `safe_delete_remote` | 传输校验 + 安全删除 |
| `CancelFlag` | 线程安全取消标志 |
| `FileInfo` / `SkippedInfo` / `ActionResult` | 共享数据模型 |

`adb_device_kit` 零外部依赖（仅 Python 标准库），即拷即用。将 `adb_device_kit/` 目录放在项目根目录下即可导入：

```python
from adb_device_kit import Device, quick_hash, AudioFilter, CancelFlag
```

### 外部工具

- `adb.exe` — Android Debug Bridge，随 PyInstaller 打包分发
- 手机端需开启 USB 调试（开发者选项）
