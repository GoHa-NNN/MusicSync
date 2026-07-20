# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

MusicSync 是一个 Windows 桌面应用，用于在 PC 与 Android 手机之间单向镜像同步音乐文件。用户选择源路径（标准库）和目的路径（被同步对象），程序扫描比对后展示差异，用户确认后执行。

## 常用命令

```bash
# 运行所有单元测试（无需 ADB 设备）
python -m pytest musicsync/adb_device_kit/tests/ -v

# 仅单元测试（排除需要真实 ADB 设备的集成测试）
python -m pytest musicsync/adb_device_kit/tests/ -v -k "not Integration and not Real"

# 运行特定测试文件
python -m pytest musicsync/adb_device_kit/tests/test_hash.py -v
python -m pytest musicsync/adb_device_kit/tests/test_filter.py -v

# 真实设备集成测试（需连接已授权 ADB 设备）
python -m pytest musicsync/adb_device_kit/tests/test_device.py -v -k "Integration or Real"

# 验证 adb_device_kit 导入
python -c "from musicsync.adb_device_kit import Device, quick_hash, AudioFilter; print('OK')"
```

## 架构

### 分层结构

```
main.py                   — 入口
musicsync/
  adb_device_kit/          — 已验证的 ADB 封装工具包（零外部依赖）
  ui/                      — PySide6 界面层（QThread + Worker + Signal/Slot）
  core/                    — 核心逻辑层（纯函数 + ADB 设备抽象）
  store/                   — SQLite 持久化层（WAL 模式）
```

### 设备组合

源端和目的端各自独立选择 PC 或 Phone（ADB），共三种组合：PC→Phone、Phone→PC、PC→PC。`adb_device_kit` 封装所有 ADB 通信。

### 线程模型

- 三个 Worker（ScanWorker / CompareWorker / ExecuteWorker）各自运行在独立 QThread
- CancelFlag（`threading.Event` 封装）跨线程传递取消信号
- closeEvent 优雅关闭，3 秒超时

### 比对策略

纯文件对比，不读音乐标签，不比较修改时间（跨文件系统 mtime 不可靠）：
- 相对路径匹配 + 大小相同 → 跳过
- 相对路径匹配 + 大小不同 → 快速哈希确认 → 源覆盖目的
- 仅在源端 → 复制到目的
- 仅在目的端 → 从目的删除

### 快速哈希

`SHA-256(文件前 64KB + 文件后 64KB + str(文件大小))`，I/O 成本从全文件降为 ~128KB。ADB 远程文件通过 `adb exec-out` + `dd iflag=count_bytes,skip_bytes` 二进制安全读取（绕过 PTY 伪终端）。

### 实现顺序

自底向上：`store/database.py` → `core/models.py` → `core/filter.py` → `core/device.py` → `core/sync_engine.py` → `core/executor.py` → `ui/workers.py` → `ui/` 全部组件 + `main.py`

## 关键约束

- **仅 Windows 10/11**，不跨平台
- **仅 USB ADB**，无 MTP、无网络传输
- **仅支持单台 ADB 设备**同时连接
- **单向同步**（源→目的），无双向、无冲突裁决
- **真实 ADB 测试**：测试必须连接真实 ADB 设备执行，不使用 mock 替代 ADB 交互
- **零外部依赖**：`adb_device_kit/` 仅用 Python 标准库，`send2trash` 为可选依赖
- `adb.exe` 随 PyInstaller `--onedir` 打包分发，绿色便携

## Agent skills

### Issue tracker

Issues 在 GitHub Issues 中管理，使用 `gh` CLI 操作。详见 `docs/agents/issue-tracker.md`。

### Domain docs

单上下文布局：`CONTEXT.md` + `docs/adr/`。详见 `docs/agents/domain.md`。
