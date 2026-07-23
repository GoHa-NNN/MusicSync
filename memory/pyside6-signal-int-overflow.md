---
name: pyside6-signal-int-overflow
description: PySide6 Signal(int) 溢出 → Slot 找不到
metadata:
  type: project
---

PySide6 `Signal(int, int, int)` 将 Python `int` 映射为 C++ signed 32-bit（−2³¹ ~ +2³¹−1，上限约 2.15GB）。当文件大小（或 multi-select 合计值）超过此上限时：

1. shiboken: `libshiboken: Overflow: Value NNN exceeds limits of type [signed] "int" (4bytes).`
2. Signal 签名损坏 → `AttributeError: Slot 'XXX::on_changed(int,int,int)' not found.`

**Why:** PySide6 Signal 参数默认映射到 C++ 类型，Python 不限大小的 int 在越过 C++ int 边界时就炸。

**How to apply:** Qt 信号中任何可能承载 2GB+ 数值的参数，用 `object` 类型替换 `int`。Python 原生 int 通过 object 原样传递，slot 侧对类型无感。下游 `format_size()` 等消费的地方本来用的就是 Python int，不受影响。

Related: [[gui-emoji-layout-lessons]]
