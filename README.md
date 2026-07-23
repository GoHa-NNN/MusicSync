# MusicSync

单向镜像音乐文件夹同步工具 — Windows 桌面应用，支持 PC ↔ Android（USB ADB）三种设备组合。

## 功能

- **单向镜像同步**：源路径为参照标准，目的路径被改造为与源一致
- **三种设备组合**：PC→Phone / Phone→PC / PC→PC
- **ADB 设备检测**：选择 Phone 时自动检测设备连接，未连接时禁用同步按钮并给出配置指引
- **快速哈希比对**：SHA-256（文件头尾各 64KB + 文件大小），~128KB I/O 成本
- **音频白名单**：自动过滤非音频文件（支持 .musicignore 排除规则）
- **差异审核**：按操作类型分组展示，逐项勾选确认后执行
- **安全删除**：PC 端送入回收站，手机端先备份后删除
- **操作历史**：每次同步完整记录，自包含可追溯
- **绿色便携**：单文件夹即用即删，无需安装

## 快速开始

### 环境要求

- Windows 10/11
- Python 3.11+
- Android 手机需开启 USB 调试（开发者选项）

### 安装

```bash
git clone <repo-url>
cd MusicSync
pip install PySide6>=6.5
```

### 运行

```bash
python main.py
```

### 命令行模式

```bash
# PC→PC 同步
python -m musicsync.cli C:/Music/Source C:/Music/Dest --yes

# PC→Phone 同步（需 ADB 设备连接）
python -m musicsync.cli C:/Music/Source /sdcard/Music/ --dest-device phone --yes

# Phone→PC 同步
python -m musicsync.cli /sdcard/Music/ C:/Music/Dest --source-device phone --yes
```

## 架构

```
main.py                   — 入口
musicsync/
  adb_device_kit/          — ADB 封装工具包（零外部依赖）
  ui/                      — PySide6 界面层（QThread + Worker + Signal/Slot）
  core/                    — 核心逻辑层（纯函数 + ADB 设备抽象）
  store/                   — SQLite 持久化层（WAL 模式）
```

### 线程模型

- ScanWorker / CompareWorker / ExecuteWorker 各自独立 QThread
- CancelFlag（threading.Event 封装）跨线程取消信号
- closeEvent 优雅关闭，3 秒超时

### 比对策略

纯文件对比，不读音乐标签，不比较修改时间：

| 条件 | 判定 | 操作 |
|------|------|------|
| 相对路径匹配 + 大小相同 | 一致 | 跳过 |
| 相对路径匹配 + 大小不同 | 差异 | 快速哈希确认 → 源覆盖目的 |
| 仅在源端 | 新文件 | 复制到目的 |
| 仅在目的端 | 多余 | 从目的删除 |

### 快速哈希

```
SHA-256(文件前 64KB + 文件后 64KB + str(文件大小))
```

ADB 远程文件通过 `adb exec-out` + `dd iflag=count_bytes,skip_bytes` 二进制安全读取。

## 测试

```bash
# 全部单元测试（无需 ADB 设备）
python -m pytest musicsync/adb_device_kit/tests/ musicsync/tests/ -v -k "not Integration and not Real"

# 仅 adb_device_kit 单元测试
python -m pytest musicsync/adb_device_kit/tests/ -v

# 真实 ADB 设备集成测试
python -m pytest musicsync/tests/ -v -k "Integration or Real"
```

## 关键约束

- 仅 Windows 10/11，不跨平台
- 仅 USB ADB，无 MTP、无网络传输
- 仅支持单台 ADB 设备同时连接
- 单向同步（源→目的），无双向、无冲突裁决
- `adb.exe` 随 PyInstaller --onedir 打包分发

## 开发

详见 [CLAUDE.md](CLAUDE.md)（项目指令）、[PRD.md](PRD.md)（产品规格）、[CONTEXT.md](CONTEXT.md)（领域术语）。

### 实现顺序

自底向上：`store/database.py` → `core/models.py` → `core/filter.py` → `core/device.py` → `core/sync_engine.py` → `core/executor.py` → `ui/workers.py` → `ui/` 全部组件 + `main.py`
