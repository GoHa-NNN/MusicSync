---
name: operation-history-five-bugs
description: 操作历史记录 5 项 Bug — 静默丢数据、硬编码假标签、字段语义不足、变量名误导
metadata:
  type: feedback
---

操作历史记录表 (`operation_history`) 在一轮审计中发现 **5 个 Bug**，涉及写入路径不一致、UI 硬编码、字段语义模糊三个根因类别。

## Bug 1: GUI 静默丢弃 delete 记录（数据丢失）

`main_window.py` 的 `_on_execute_finished()` 中：

```python
if d.selected and d.operation != "delete":  # ← 显式跳过 delete
```

CLI 端 (`cli.py`) 无此过滤，两端行为不一致。删除操作在 GUI 中执行后历史表毫无痕迹。

**根因**: 写入逻辑分散在 GUI/CLI 两处，各自实现过滤条件，缺乏统一的"是否记录"决策点。

## Bug 2 & 3: `direction` 字段永远不含设备标签 + UI 硬编码 `[PC]`

`sync_engine.py` 的 `compare()` 将 direction 硬编码为 `"source → dest"` / `"dest"`。`history_view.py` 的 `_action_display()` 硬编码显示 `[PC] → [PC]` / `删除 in [PC]`。三种设备组合（PC→PC、PC→Phone、Phone→PC）在历史记录中完全不可区分。

**根因**: `direction` 字段在设计时假设"源/目的"语义足够，但忽略了设备身份是历史可追溯性的必需信息。

**修复策略**: 不改 `compare()` 签名（避免影响面扩散），在写入层（`_on_execute_finished` / `cli.main`）根据 `_current_src_device` / `_current_dst_device` 构造含设备标签的 direction（如 `"PC → Phone"`、`"Phone"`）。

## Bug 4: overwrite 只记录源端大小

表中 `file_size` 只有源端新大小。覆盖操作丢失目的端旧大小，无法追溯覆盖前后的变化幅度。

**修复**: 加 `dest_size INTEGER` 列（ALTER TABLE 迁移），`record_operation()` 增加 `dest_size` 参数。copy 为 NULL，overwrite 为旧大小，delete 不使用。

## Bug 5: CLI 变量名与语义相反

```python
succeeded_paths = {f[0] for f in result.failures}  # 装的是失败路径!
```

变量名叫"成功路径"，实际装的是失败路径。后续条件 `not in succeeded_paths` 的逻辑结果碰巧正确，但变量名严重误导。

## 通用教训

1. **写入路径不要分散**: 同一张表的写入逻辑散落多处时，必有一处遗漏。应有一个单一的写入入口，各调用方只传数据。
2. **表格列永远留余地**: `file_size` 只记录一个方向的大小，结果 overwrite 场景语义不足。设计列时思考"这个字段在不同操作类型下分别代表什么"。
3. **不要在 UI 层硬编码数据值**: `_action_display()` 把 `[PC]` 写死在代码里，而不是从数据推断。数据层和展示层应解耦——数据说了算，展示层只负责格式化。
4. **变量名与实际语义不一致是定时炸弹**: `succeeded_paths` = failures。随时可能被后续维护者"修正"成真的 `succeeded_paths`，引入反向 bug。
5. **CLI 和 GUI 必须共享核心逻辑**: 两端的写入过滤条件不同（一个过滤 delete，一个不过滤），说明核心规则没有下沉到共享层。

**Why:** 操作历史是用户信任的基础——用户需要知道"我同步了什么、删了什么、覆盖了什么"。丢失 delete 记录意味着用户可能不知道手机上的文件被删了。

**How to apply:** 后续任何新增操作类型时，检查: (1) 写入路径是否统一，(2) 字段语义是否覆盖所有操作类型，(3) 展示层是否从数据解析而非硬编码，(4) CLI/GUI 是否共享了核心规则。
