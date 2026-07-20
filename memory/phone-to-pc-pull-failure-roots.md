---
name: phone-to-pc-pull-failure-roots
description: 路径截断 / adb 输出流 / device 闭包 三重 bug 剖析
metadata:
  type: feedback
---

Phone→PC pull 全失败（5/5），三个独立根因叠加：

**根因 1 — 路径前缀截断（`_scan_phone` 函数）**
旧代码 `rel = full_path[len(root_path):].lstrip("/")` 形式上是字符串截断，实际在有 `//` 前缀与带 `/` 后缀时静默截错。例如：
- `root_path = '/sdcard/Music/'`（len=15）
- `full_path = '//sdcard/Music/浩/年少有为-李荣浩.flac'`（Device._safe_path 加了 `//` 前缀）
截断只切 15 字符，得到的相对路径中包含 `『浩/』`前缀。
**修复**：规范化去斜杠后用 `find` 找 root 在路径中的位置，再从 root 结束位置取相对路径。

**根因 2 — adb pull 错误信息在 stderr 而非 stdout**
adb pull 成功时 stdout 为空（0 字节），stderr 含速度信息（`X bytes in Ys`）；失败时 stderr 含 `adb: error: ...`。
之前的代码检查 stdout 中是否有 "error"，从来没有命中过。
**修复**：始终检查 stderr（与 push 一致）。

**根因 3 — _make_phone_hash 中 device 变量被闭包捕获**
`_make_phone_hash` 返回的 `phone_hash` 闭包中引用了外层 `device` 变量。在某些调用路径下 device 引用可能指向 DiffItem（因为 lambda 闭包中的变量名遮蔽）。
**修复**：函数签名保持独立，不依赖闭包遮蔽。

**Why:** 三个 bug 每个都独立致命，需要同时修复才能打通 Phone→PC 全链路。

**How to apply:** Phone 端文件路径处理必须处理 `//` 前缀与 `/` 后缀的不一致。adb 子进程 stdout/stderr 语义对照表需要写在 Device 类文档中。
