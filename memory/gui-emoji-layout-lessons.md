---
name: gui-emoji-layout-lessons
description: Qt GUI 开发中 emoji 渲染、布局切换和细节修复的经验教训
metadata:
  type: feedback
---

增量 3（GUI 界面开发）中暴露的最新问题及修复方案：

**问题 1：emoji 在 Qt 中渲染不稳定**
尝试在 QTableWidgetItem 中显示 💻 📱 📋 📜 ▶ ✕ 等 emoji 字符时，PySide6 QTableWidgetItem 渲染行为不可预测。
- 某些 emoji 显示为空白方块
- 某些 emoji 导致 AttributeError / RuntimeError
- GBK 编码环境下的 UnicodeEncodeError

**修复**：全面移除 emoji，使用纯 ASCII 文本标识符 `[PC]` / `[Phone]`。

**问题 2：load_diffs 调用 module-level 函数 vs instance method**
将 `_format_device_size` 改为 module-level `format_device_size` 后，`_fill_row` 中仍引用 `self._format_device_size`，导致 `AttributeError`。
**修复**：确保方法名对齐，或全部使用 module-level 函数。

**问题 3：closeEvent 访问已释放 QThread**
Worker 线程在 `finished` 信号中调用了 `deleteLater()`，C++ 对象被销毁。当 `closeEvent` 遍历 `_scan_thread` / `_compare_thread` / `_execute_thread` 调用 `.isRunning()` 时触发 `RuntimeError: libshiboken: Internal C++ object already deleted`。
**修复**：所有 QThread 访问用 `try/except RuntimeError` 包装。

**Why:** Qt GUI 开发中的符号字符必须保守，闭包 lambda 中引用的对象生命周期需要显式保护。

**How to apply:** 后续任何 Qt 文本渲染中避免 non-ASCII 图形字符。closeEvent 中的所有线程操作包裹 RuntimeError 防护。
