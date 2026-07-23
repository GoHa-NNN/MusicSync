---
name: operation-history-timezone-and-silent-failure
description: 操作历史两个 Bug——时间戳显示差8小时 + 批量记录"丢失"根因分析
metadata:
  type: project
---

# 操作历史记录两个 Bug 修复

## Bug #1：时间戳显示差 8 小时

**症状**：下午 15:xx 的操作，历史记录中显示为上午 06:xx。

**根因**：`database.py:83` 存储时使用 `datetime.now(timezone.utc)`（带 UTC 时区），`history_view.py:85-86` 显示时直接 `.strftime()` 输出 UTC 时间，没有 `.astimezone()` 转本地时区。UTC 与中国时区（UTC+8）差 8 小时。

**修复**：
- `history_view.py:85-90`：`datetime.fromisoformat(ts)` 后检查 `dt.tzinfo`，非 None 时调用 `.astimezone()` 转本地时区再格式化
- `database.py:83`：注释标明存储策略（UTC）

## Bug #2：181 条批量操作在历史记录中"丢失"

**症状**：执行 181 条 Phone→PC overwrite 后，操作完成无误，但用户认为历史记录中没有这 181 条记录。

**实际调查**：
1. 181 条记录**全部成功写入**数据库，时间戳在 06:31 UTC（14:31 CST）
2. 用户没看到的原因有三层：
   - **时间偏移（Bug #1）**：显示为 06:31，用户以为是旧记录，不认得
   - **LIMIT 50**：`list_operations` 默认只返回 50 条，181 条中 138 条被截断
   - **静默吞错**：`_on_execute_finished` 中 `except Exception: pass` 会隐藏所有持久化失败

**修复**：
- `main_window.py:347-350`：`except Exception` 改为 `logger.exception()` 记录失败详情
- `database.py:96`：`list_operations` 默认 limit 50→500

**Why:** UTC 存储正确（跨时区可比+无 DST 歧义），但显示时必须转本地。批量操作中每条记录的时间戳在同 1 秒内，按时间倒序查询时 LIMIT 50 会截断大量同秒记录。

**How to apply:** 新增时间相关功能时，统一：存储用 `datetime.now(timezone.utc).isoformat()`（带 `+00:00`），显示用 `datetime.fromisoformat(ts).astimezone().strftime()`。持久化操作不可用 `except: pass`，至少要打日志。
