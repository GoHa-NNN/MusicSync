# ADR 0001: 增量 2 手机 ADB 适配架构决策

**日期**: 2026-07-20
**状态**: 已接受

## 背景

增量 1 完成了 PC→PC 单向镜像同步 CLI 先行版。增量 2 需要将同步能力扩展到涉及手机（ADB）的设备组合。

## 决策

### 1. Executor 内联注入（非策略对象）

`execute()` 新增 `source_device: Device | None` 和 `dest_device: Device | None` 参数。
内部按三种设备组合 dispatch 四个函数（transfer_fn、source_hash_fn、dest_hash_fn、delete_fn），
统一使用已有的 `transfer_with_verify()` 替代当前手写的 `_copy_with_verify()`。

**拒绝的方案**: 策略对象/TransferStrategy 类层次结构——过于重量级，
`transfer_with_verify()` 已经是现成的 adapter 接口。

### 2. CLI 显式设备 flag

`--source-device pc|phone` 和 `--dest-device pc|phone`，默认值 `pc`。
路径以 `//` 开头不自动推断为 Phone——Win32 路径启发式不可靠。
向后兼容：不带 flag 等价于 PC→PC。

**拒绝的方案**: 从路径前缀隐式推断设备类型。

### 3. Phone 源端跳过 .musicignore

当源端为 Phone 时，不尝试加载 `.musicignore`。Phone 端通常没有此文件，
且 `Device` 当前缺少读取完整文件内容的原语（`read_head_tail` 只读 128KB）。
后续增量可扩展。

### 4. 设备组合范围：三种，不做 Phone→Phone

PRD、CONTEXT.md、CLAUDE.md 已统一修正。Phone→Phone 加入"明确不做"列表。
ADB 不支持设备间直接传输，必须经 PC 中转，增加复杂度且非用户核心场景。

### 5. 测试策略：分层

- **单元测试**：CLI 参数解析、设备组合 dispatch 逻辑、hash 函数选择 → mock Device
- **集成测试**：PC→Phone 和 Phone→PC 全链路 → 真实 ADB 设备
- 现有 PC→PC 38 个测试保持不变

## 影响

- `executor.py`: 重构 `execute()` + 删除 `_copy_with_verify()`，新增 dispatch 逻辑约 40 行
- `cli.py`: 新增 argparse + Device 实例化 + ADB 设备检测，约 30 行
- `sync_engine.py`: `_scan_phone()` 已就绪，无需修改
- 新增测试文件: `test_cli_device.py`、`test_executor_device.py`（单元）、`test_integration_phone.py`（集成）
