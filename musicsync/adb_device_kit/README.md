# adb_device_kit — Android ADB 设备通信与文件操作工具包

> 从 MusicSync v1 提取的经过 bug 修复验证的底层模块，零外部依赖（仅 Python 标准库）。

**版本**: 1.0.0 &nbsp;|&nbsp; **许可**: MIT &nbsp;|&nbsp; **Python**: ≥ 3.8

---

## 目录

- [快速开始（5 分钟上手）](#快速开始5-分钟上手)
- [安装](#安装)
- [API 参考](#api-参考)
  - [Device — ADB 设备层](#device--adb-设备层)
  - [hash_utils — 快速哈希](#hash_utils--快速哈希)
  - [filter_utils — 文件过滤器](#filter_utils--文件过滤器)
  - [executor_helpers — 传输校验与安全删除](#executor_helpers--传输校验与安全删除)
  - [cancel_flag — 线程安全取消标志](#cancel_flag--线程安全取消标志)
  - [models — 共享数据模型](#models--共享数据模型)
- [已修复的关键 Bug](#已修复的关键-bug)
- [测试](#测试)
- [设计原则](#设计原则)

---

## 快速开始（5 分钟上手）

```python
from adb_device_kit import (
    Device, CancelFlag,
    quick_hash, compute_local_hash,
    AudioFilter, DEFAULT_AUDIO_EXTENSIONS,
    transfer_with_verify, safe_delete_remote, format_size,
)

# ── 1. 连接设备 ──────────────────────────────────────
device = Device("adb")  # 或 Device("C:/platform-tools/adb.exe")
if not device.detect():
    print("未检测到设备——请连接 Android 手机并开启 USB 调试")
    exit(1)

info = device.get_device_info()
print(f"已连接: {info.get('model', '未知')} ({info.get('device_id', '?')})")

# ── 2. 扫描文件 ──────────────────────────────────────
files = device.list_files("//sdcard/Music/")
print(f"找到 {len(files)} 个文件")

# ── 3. 获取文件元数据 ────────────────────────────────
for f in files[:3]:
    meta = device.stat(f)
    if meta:
        print(f"  {f}")
        print(f"    大小: {format_size(meta['size'])}")
        print(f"    修改时间: {meta['modified']}")

# ── 4. 计算文件哈希（不传输整个文件） ──────────────────
if files:
    head, tail = device.read_head_tail(files[0])
    h = quick_hash(head, tail, device.stat(files[0])["size"])
    print(f"首个文件哈希: {h}")

# ── 5. 传输文件并校验 ────────────────────────────────
# PC → 手机：push + 哈希校验
ok, err = transfer_with_verify(
    transfer_fn=device.push,
    source_hash_fn=compute_local_hash,
    dest_hash_fn=lambda path, size: quick_hash(*device.read_head_tail(path), size),
    source_path="C:/Music/song.flac",
    dest_path="//sdcard/Music/song.flac",
    file_size=26580279,
)
print("传输成功" if ok else f"传输失败: {err}")

# ── 6. 安全删除手机文件（先备份到 PC） ─────────────────
ok, err = safe_delete_remote(
    device=device,
    remote_path="//sdcard/Music/old.flac",
    relative_path="Archive/old.flac",
    backup_dir="C:/MusicSync_backup/",
)
print("安全删除成功" if ok else f"删除失败: {err}")

# ── 7. 使用文件过滤器 ─────────────────────────────────
f = AudioFilter(musicignore_content="*.jpg\n临时/\n")
kept, skipped = f.filter(files, side="dest")
print(f"保留 {len(kept)} 个音频文件，跳过 {len(skipped)} 个")
```

---

## 安装

将 `adb_device_kit/` 目录复制到你的项目中即可使用，无需 `pip install`。

**前置条件**:
- Python 3.8 或更高版本
- [Android Debug Bridge (ADB)](https://developer.android.com/tools/adb) 可执行文件（`adb.exe` 在 PATH 中或指定完整路径）
- 可选：[send2trash](https://pypi.org/project/Send2Trash/)（`pip install send2trash`）—— 启用回收站安全删除

**验证安装**:
```bash
python -c "from adb_device_kit import Device, quick_hash, AudioFilter; print('OK')"
# 输出: OK
```

---

## API 参考

### Device — ADB 设备层

**文件**: `adb_device_kit/device.py`

封装所有 ADB 交互——设备检测、文件枚举、属性获取、传输操作。所有与手机通信的方法都接受可选的 `cancel_flag` 参数用于安全取消长时操作。

```python
from adb_device_kit import Device, DeviceError
```

#### `Device(adb_path: str = "adb")`

构造 Device 实例。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `adb_path` | `str` | `"adb"` | adb 可执行文件路径。默认从系统 PATH 查找；可传入完整路径如 `"C:/platform-tools/adb.exe"` |

```python
device = Device()                    # PATH 中查找 adb
device = Device("tools/adb.exe")     # 指定路径
```

---

#### `device.detect() -> bool`

检测是否有已授权的 Android 设备连接。解析 `adb devices -l` 输出，只识别状态为 `device` 的已授权设备（忽略 `unauthorized` 和 `offline`）。

```python
if device.detect():
    print("设备已连接")
else:
    print("请连接手机并开启 USB 调试")
```

---

#### `device.get_device_info() -> dict[str, str]`

获取当前连接设备的详细信息。

**返回值**:
- 成功: `{"device_id": "f50f82b8", "model": "23013RK75C", "product": "mondrian", ...}`
- 无设备: `{}`

```python
info = device.get_device_info()
print(info.get("model"))       # "23013RK75C"
print(info.get("device_id"))   # "f50f82b8"
```

---

#### `device.list_files(directory: str, cancel_flag: CancelFlag | None = None) -> list[str]`

枚举目录下所有文件的完整 ADB 路径。使用 `adb shell find <dir> -type f`，返回按字母序排序的完整路径列表。

| 参数 | 类型 | 说明 |
|------|------|------|
| `directory` | `str` | ADB 远程目录路径，如 `"//sdcard/Music/"` |
| `cancel_flag` | `CancelFlag \| None` | 可选取消标志。已设置时立即返回空列表 |

**返回值**: 文件完整路径列表（已排序）。目录不存在或为空时返回空列表。

**注意**: 不过滤隐藏文件（如 `.thumbnails`）——由调用方负责过滤。

```python
files = device.list_files("//sdcard/Music/")
print(f"找到 {len(files)} 个文件")
for f in files[:5]:
    print(f"  {f}")
```

---

#### `device.stat(file_path: str) -> dict | None`

获取手机端文件的属性。通过 `adb shell stat -c '%s|%Y'` 获取文件大小和 Unix 时间戳，时间戳转换为 ISO 8601 格式。

| 参数 | 类型 | 说明 |
|------|------|------|
| `file_path` | `str` | ADB 文件路径，如 `"//sdcard/Music/song.flac"` |

**返回值**:
- 文件存在: `{"size": 26580279, "modified": "2026-01-15T08:30:00+00:00"}`
- 文件不存在或出错: `None`

```python
info = device.stat("//sdcard/Music/song.flac")
if info:
    print(f"大小: {info['size']} bytes")       # 26580279
    print(f"修改时间: {info['modified']}")       # "2026-01-15T08:30:00+00:00"
```

---

#### `device.read_head_tail(file_path: str, chunk_size: int = 65536, cancel_flag: CancelFlag | None = None) -> tuple[bytes, bytes]`

**二进制安全**地读取手机端文件的头部和尾部字节。这是快速哈希的核心支撑函数。

> ⚠️ **关键实现细节**: 使用 `adb exec-out` **而非** `adb shell`。`exec-out` 绕过 PTY 伪终端，避免 PTY 的 `\n` → `\r\n` 文本转换污染二进制数据。使用 `dd iflag=count_bytes,skip_bytes` 确保以**字节**（而非块）为单位精确读取。这些修复解决了 MusicSync v1 中 ADB 哈希校验永远失败的 Bug。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `file_path` | `str` | — | ADB 文件路径 |
| `chunk_size` | `int` | `65536` | 读取块大小（字节）。文件小于此值时头部包含全部内容、尾部为空 |
| `cancel_flag` | `CancelFlag \| None` | `None` | 可选取消标志 |

**返回值**: `(head_bytes, tail_bytes)` — 各最多 `chunk_size` 字节。文件不存在或读取出错时对应位置为空 `b""`。

```python
head, tail = device.read_head_tail("//sdcard/Music/song.flac")
# 可用于快速哈希: SHA-256(head + tail + file_size)
```

---

#### `device.push(local_path: str, remote_path: str, cancel_flag: CancelFlag | None = None) -> bool`

将本地文件推送到手机。

```python
ok = device.push("C:/Music/song.flac", "//sdcard/Music/song.flac")
```

---

#### `device.pull(remote_path: str, local_path: str, cancel_flag: CancelFlag | None = None) -> bool`

从手机拉取文件到本地。

```python
ok = device.pull("//sdcard/Music/song.flac", "C:/backup/song.flac")
```

---

#### `device.delete(remote_path: str, cancel_flag: CancelFlag | None = None) -> bool`

删除手机端文件。执行 `rm -f` 后调用 `stat` 验证文件确实不存在。

```python
if device.delete("//sdcard/Music/old.flac"):
    print("已删除并验证")
```

---

#### `device.get_free_space(directory: str = "//sdcard/") -> int | None`

获取手机端剩余空间。通过 `df -k` 解析 Available 列。

**返回值**: 剩余空间字节数；获取失败返回 `None`。

```python
free = device.get_free_space()
if free:
    print(f"剩余: {free / (1024**3):.1f} GB")
```

---

#### `DeviceError` — 异常类

```python
class DeviceError(Exception):
    """ADB 设备层错误。"""
```

---

#### 常量

| 常量 | 值 | 说明 |
|------|-----|------|
| `CMD_TIMEOUT_SHORT` | `15` | 短命令超时（秒）：devices、stat、rm |
| `CMD_TIMEOUT_LIST` | `60` | 文件枚举超时（秒）：find |
| `CMD_TIMEOUT_TRANSFER` | `300` | 传输超时（秒）：push、pull |
| `QUICK_HASH_CHUNK` | `65536` | 快速哈希块大小（64KB） |

---

### hash_utils — 快速哈希

**文件**: `adb_device_kit/hash_utils.py`

基于 SHA-256 的快速文件哈希算法，仅读取文件的前 64KB 和后 64KB，适用于数 GB 的大文件快速校验。

**算法**: `SHA-256(前64KB + 后64KB + str(文件大小))`

```python
from adb_device_kit import quick_hash, compute_local_hash
```

#### `quick_hash(head: bytes, tail: bytes, file_size: int) -> str`

纯函数，无 I/O 依赖。给定文件头尾字节和大小，返回确定性哈希值。

| 参数 | 类型 | 说明 |
|------|------|------|
| `head` | `bytes` | 文件头部字节（通常为前 64KB，小文件时为全部内容） |
| `tail` | `bytes` | 文件尾部字节（通常为后 64KB，小文件时为空） |
| `file_size` | `int` | 文件总大小（字节），作为哈希输入的一部分确保不同大小文件产生不同哈希 |

**返回值**: 64 字符小写十六进制 SHA-256 哈希字符串。

**算法保证**:
- **确定性**: 相同输入永远产生相同输出
- **区分性**: 不同 head/tail/size 产生不同输出
- **格式**: 始终为 64 字符十六进制

```python
h = quick_hash(b"head_bytes...", b"tail_bytes...", 1234567)
print(h)  # "a1b2c3d4e5f6..."  (64 字符)
```

#### `compute_local_hash(file_path: str, file_size: int) -> str | None`

计算 PC 端本地文件的快速哈希。自动读取文件头部和尾部片段后调用 `quick_hash()`。

| 参数 | 类型 | 说明 |
|------|------|------|
| `file_path` | `str` | PC 端文件绝对路径 |
| `file_size` | `int` | 文件大小（通过 `os.path.getsize()` 获取） |

**返回值**:
- 成功: 64 字符哈希字符串
- 文件不存在或读取失败: `None`

```python
import os
path = "C:/Music/song.flac"
h = compute_local_hash(path, os.path.getsize(path))

# 校验两个文件是否相同
h1 = compute_local_hash("a.flac", os.path.getsize("a.flac"))
h2 = compute_local_hash("b.flac", os.path.getsize("b.flac"))
if h1 and h2 and h1 == h2:
    print("内容相同")
```

#### 常量

| 常量 | 值 | 说明 |
|------|-----|------|
| `QUICK_HASH_CHUNK` | `65536` | 读取块大小（64KB） |

---

### filter_utils — 文件过滤器

**文件**: `adb_device_kit/filter_utils.py`

组合**音频扩展名白名单**和可选的 **.musicignore 规则**。纯函数设计——`.musicignore` 内容由调用方传入字符串，不涉及文件 I/O。

```python
from adb_device_kit import (
    AudioFilter,
    parse_musicignore,
    matches_any_rule,
    DEFAULT_AUDIO_EXTENSIONS,
)
```

#### `DEFAULT_AUDIO_EXTENSIONS: list[str]`

内置默认白名单：`["flac", "mp3", "wav", "aac", "ogg", "m4a", "wma"]`

#### `parse_musicignore(content: str) -> list[str]`

解析 `.musicignore` 文件内容为规则列表。规则语法兼容 `.gitignore`（子集）。

| 规则类型 | 示例 | 说明 |
|----------|------|------|
| 注释 | `# 这是注释` | 以 `#` 开头，忽略 |
| 空行 | (空) | 忽略 |
| glob 模式 | `*.jpg` | fnmatch glob 匹配 |
| 目录规则 | `临时/` | 匹配路径中任意位置的该目录名 |

```python
rules = parse_musicignore("# 图片\n*.jpg\n*.png\n临时/\n")
# ['*.jpg', '*.png', '临时/']
```

#### `matches_any_rule(relative_path: str, rules: list[str]) -> bool`

检查相对路径是否匹配任意一条规则。同时检查 Unix (`/`) 和 Windows (`\`) 路径分隔符。

| 参数 | 类型 | 说明 |
|------|------|------|
| `relative_path` | `str` | 文件相对路径，如 `"VOCALOID/cover.jpg"` |
| `rules` | `list[str]` | `parse_musicignore()` 返回的规则列表 |

```python
rules = ["*.jpg", "临时/"]
matches_any_rule("VOCALOID/cover.jpg", rules)   # True
matches_any_rule("临时/song.flac", rules)         # True
matches_any_rule("song.flac", rules)               # False
```

#### `AudioFilter(extensions: list[str] | None = None, musicignore_content: str | None = None)`

音频文件过滤器。组合白名单 + `.musicignore` 规则。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `extensions` | `list[str] \| None` | `None` | 自定义音频扩展名列表。`None` 使用默认 7 种格式。大小写无关，前导 `.` 自动去除 |
| `musicignore_content` | `str \| None` | `None` | `.musicignore` 文本内容。`None` 或空不启用忽略规则。解析失败静默回退 |

**属性**:
- `extensions: list[str]` — 当前生效的扩展名列表（小写，不含点）
- `musicignore_rules: list[str]` — 当前生效的规则列表

---

#### `filter.should_include(file_path: str) -> bool`

检查单个文件是否应被包含。两阶段检查：① 扩展名必须在白名单中 ② 路径不能匹配 `.musicignore` 规则。

```python
f = AudioFilter()
f.should_include("music/song.flac")   # True
f.should_include("music/cover.jpg")    # False
```

---

#### `filter.filter(file_list: list[str], side: str = "source") -> tuple[list[str], list[str]]`

批量过滤文件列表，同时记录跳过统计。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `file_list` | `list[str]` | — | 文件路径列表 |
| `side` | `str` | `"source"` | 设备端标识（`"source"` / `"dest"`），用于分组统计 |

**返回值**: `(kept, skipped)` — 保留的和跳过的文件列表。

```python
kept, skipped = f.filter(files, side="source")
print(f"保留 {len(kept)}，跳过 {len(skipped)}")
```

---

#### `filter.get_skipped_summary() -> SkippedInfo`

返回跳过文件的统计信息。

```python
summary = f.get_skipped_summary()
print(f"总共跳过 {summary.total} 个文件")
print(f"  按扩展名: {summary.by_extension}")   # {".jpg": 77, ".tmp": 3}
print(f"  按设备: {summary.by_side}")          # {"source": 2, "dest": 80}
print(f"  文件列表: {summary.file_list[:5]}...")
```

---

#### `filter.reset_skipped() -> None`

重置所有跳过统计计数器。在开始新扫描前调用，防止跨扫描数据累积。

```python
f.filter(scan1_files, side="source")
# ... 使用统计后 ...
f.reset_skipped()
f.filter(scan2_files, side="dest")  # 全新统计
```

---

### executor_helpers — 传输校验与安全删除

**文件**: `adb_device_kit/executor_helpers.py`

从 MusicSync v1 Executor 类中提取的核心传输+校验+安全删除逻辑，解耦为独立纯函数。

```python
from adb_device_kit import (
    transfer_with_verify,
    safe_delete_local,
    safe_delete_remote,
    format_size,
    HAS_SEND2TRASH,
)
```

#### `transfer_with_verify(transfer_fn, source_hash_fn, dest_hash_fn, source_path, dest_path, file_size) -> tuple[bool, str]`

传输文件并立即在目标端校验完整性。

**流程**: ① 计算源文件哈希 → ② 执行传输 → ③ 计算目标文件哈希 → ④ 校验比对

| 参数 | 类型 | 说明 |
|------|------|------|
| `transfer_fn` | `(str, str) -> bool` | 传输函数（如 `device.push` 或 `device.pull`） |
| `source_hash_fn` | `(str, int) -> str \| None` | 源端哈希计算函数 |
| `dest_hash_fn` | `(str, int) -> str \| None` | 目标端哈希计算函数 |
| `source_path` | `str` | 源文件路径 |
| `dest_path` | `str` | 目标文件路径 |
| `file_size` | `int` | 文件大小（字节） |

**返回值**: `(成功?, 错误信息)` — 成功时错误信息为空字符串。

```python
# PC → 手机: push + 校验
ok, err = transfer_with_verify(
    transfer_fn=device.push,
    source_hash_fn=compute_local_hash,
    dest_hash_fn=lambda path, size: quick_hash(*device.read_head_tail(path), size),
    source_path="C:/Music/song.flac",
    dest_path="//sdcard/Music/song.flac",
    file_size=26580279,
)

# 手机 → PC: pull + 校验
ok, err = transfer_with_verify(
    transfer_fn=lambda src, dst: device.pull(src, dst),
    source_hash_fn=lambda path, size: quick_hash(*device.read_head_tail(path), size),
    dest_hash_fn=compute_local_hash,
    source_path="//sdcard/Music/song.flac",
    dest_path="C:/backup/song.flac",
    file_size=26580279,
)
```

---

#### `safe_delete_local(local_path: str, relative_path: str, backup_dir: str) -> tuple[bool, str]`

安全删除 PC 端本地文件。优先使用 `send2trash`（移入回收站，可恢复）；若不可用则移动到备份目录。

| 参数 | 类型 | 说明 |
|------|------|------|
| `local_path` | `str` | 要删除的本地文件绝对路径 |
| `relative_path` | `str` | 文件相对路径（用于在备份目录中保留目录结构） |
| `backup_dir` | `str` | 备份根目录 |

```python
ok, err = safe_delete_local(
    "C:/Music/old.flac",
    "Archive/old.flac",
    "C:/MusicSync_backup/",
)
```

---

#### `safe_delete_remote(device, remote_path, relative_path, backup_dir, cancel_flag=None) -> tuple[bool, str]`

安全删除手机端文件。ADB 没有回收站——先拉取备份到 PC → 哈希校验完整性 → 再删除远程文件。

**流程**: ① 创建备份目录 → ② 获取远程文件 stat → ③ pull 到 PC → ④ 哈希校验备份完整性 → ⑤ rm 远程文件 + 验证

| 参数 | 类型 | 说明 |
|------|------|------|
| `device` | `Device` | Device 实例 |
| `remote_path` | `str` | 手机端文件路径 |
| `relative_path` | `str` | 相对路径（用于备份目录结构） |
| `backup_dir` | `str` | PC 端备份根目录 |
| `cancel_flag` | `CancelFlag \| None` | 可选取消标志 |

```python
ok, err = safe_delete_remote(
    device=device,
    remote_path="//sdcard/Music/old.flac",
    relative_path="Archive/old.flac",
    backup_dir="C:/MusicSync_backup/",
)
```

---

#### `format_size(size_bytes: int) -> str`

格式化文件大小为人类可读格式。

| 输入 | 输出 |
|------|------|
| `0` | `"0B"` |
| `500` | `"500B"` |
| `1500` | `"1KB"` |
| `26580279` | `"25.3MB"` |
| `5368709120` | `"5.00GB"` |

```python
print(format_size(26580279))  # "25.3MB"
```

#### `HAS_SEND2TRASH: bool`

布尔常量。`True` 表示 `send2trash` 包已安装并可用。

---

### cancel_flag — 线程安全取消标志

**文件**: `adb_device_kit/cancel_flag.py`

基于 `threading.Event` 的取消标志。零依赖，纯标准库。用于在多线程操作中安全传递取消信号。

```python
from adb_device_kit import CancelFlag
```

#### `CancelFlag()`

线程安全取消标志。

```python
flag = CancelFlag()

# ── 在 worker 线程中周期性检查 ──
def worker(flag):
    for item in items:
        if flag.is_set():
            print("收到取消信号，安全退出")
            return
        process(item)

# ── 在 UI 线程中取消 ──
flag.cancel()
```

#### `flag.cancel() -> None`

设置取消标志。幂等操作——重复调用无副作用。

#### `flag.is_set() -> bool`

检查取消标志是否已被设置。

#### `flag.reset() -> None`

重置取消标志（用于启动新操作）。

```python
flag.cancel()
assert flag.is_set()          # True
flag.reset()
assert not flag.is_set()      # True
```

---

### models — 共享数据模型

**文件**: `adb_device_kit/models.py`

纯数据结构（dataclass），无业务逻辑、无 I/O 依赖。

```python
from adb_device_kit import FileInfo, SkippedInfo, ScanResult, ActionResult
```

#### `FileInfo`

单个文件的元数据快照。用于在 scan/compare 阶段传递文件信息。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `path` | `str` | (必填) | 文件完整路径 |
| `relative_path` | `str` | (必填) | 相对路径（用于跨设备文件匹配） |
| `size` | `int \| None` | `None` | 文件大小（字节） |
| `modified` | `str \| None` | `None` | ISO 8601 修改时间 |
| `hash` | `str \| None` | `None` | 快速哈希值（按需计算） |

```python
f = FileInfo(
    path="//sdcard/Music/song.flac",
    relative_path="VOCALOID/song.flac",
    size=26580279,
    modified="2026-01-15T08:30:00+00:00",
)
```

#### `SkippedInfo`

扫描时被跳过的文件统计。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `total` | `int` | `0` | 跳过文件总数 |
| `by_extension` | `dict[str, int]` | `{}` | 按扩展名分组，如 `{".jpg": 77}` |
| `by_side` | `dict[str, int]` | `{}` | 按设备端分组，如 `{"source": 2}` |
| `file_list` | `list[str]` | `[]` | 被跳过的文件完整路径列表 |

#### `ScanResult`

扫描阶段产出。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `source_files` | `list[FileInfo]` | `[]` | 源端文件列表 |
| `dest_files` | `list[FileInfo]` | `[]` | 目的端文件列表 |

#### `ActionResult`

执行阶段产出（传输/删除等操作的汇总结果）。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `success_count` | `int` | `0` | 成功数 |
| `failure_count` | `int` | `0` | 失败数 |
| `skip_count` | `int` | `0` | 跳过数（用户取消等） |
| `failures` | `list[(str, str)]` | `[]` | 失败详情：`(文件路径, 错误信息)` |
| `total_bytes_transferred` | `int` | `0` | 总传输字节数 |

```python
result = ActionResult(
    success_count=150,
    failure_count=2,
    failures=[("song.flac", "传输超时"), ("cover.jpg", "权限不足")],
    total_bytes_transferred=3_540_000_000,
)
```

---

## 已修复的关键 Bug

本工具包包含 MusicSync v1 中以下 3 个已修复和验证的 Bug：

### Bug #1: ADB 哈希校验永远失败

| 项目 | 详情 |
|------|------|
| **根因** | 两个独立问题叠加：① `adb shell` 路由通过 PTY 伪终端，将二进制流中的 `\n` 转换为 `\r\n`，破坏数据完整性；② `dd bs=65536 skip=N count=1` 以**块**（而非字节）为单位，`(file_size - chunk_size) // chunk_size` 整数除法导致尾部偏移错误 |
| **修复** | ① 使用 `adb exec-out` 替代 `adb shell`，绕过 PTY；② 使用 `dd iflag=skip_bytes,count_bytes` 替代块模式 `bs=N skip=N count=1` |
| **影响模块** | `device.py` → `read_head_tail()` |
| **状态** | ✅ 已修复并验证 |

### Bug #2: 扫描比对崩溃（返回类型不匹配）

| 项目 | 详情 |
|------|------|
| **根因** | `AudioFilter.get_skipped_summary()` 返回值类型不一致——有时返回 dict，有时返回 SkippedInfo 对象。调用方做属性访问时对 dict 对象报 `AttributeError` |
| **修复** | 统一返回 `SkippedInfo` dataclass |
| **影响模块** | `filter_utils.py` → `AudioFilter.get_skipped_summary()` |
| **状态** | ✅ 已修复并验证 |

### Bug #3: 跳过的文件统计跨扫描累积

| 项目 | 详情 |
|------|------|
| **根因** | `AudioFilter._skipped` 列表在多次 `filter()` 调用间持续累积，未在扫描间重置 |
| **修复** | 新增 `reset_skipped()` 方法，调用方在开始新扫描前调用 |
| **影响模块** | `filter_utils.py` → `AudioFilter.reset_skipped()` |
| **状态** | ✅ 已修复并验证 |

---

## 测试

```bash
# 全部单元测试（无需 ADB 设备）
python -m pytest adb_device_kit/tests/ -v

# 仅单元测试（排除集成测试）
python -m pytest adb_device_kit/tests/ -v -k "not Integration and not Real"

# 真实设备集成测试（需要 ADB 授权设备连接）
python -m pytest adb_device_kit/tests/test_device.py -v -k "Integration or Real"
```

**测试覆盖**:

| 测试文件 | 测试数 | 覆盖内容 |
|----------|--------|----------|
| `test_cancel_flag.py` | 7 | 基本功能 + 多线程安全 |
| `test_hash.py` | 11 | 确定性、区分性、边界条件、已知向量 |
| `test_filter.py` | 25 | .musicignore 解析、glob 匹配、白名单、批量过滤、统计、reset |
| `test_device.py` | 25 | 设备检测、文件枚举、stat、传输、删除、空间、集成测试 |

> 真实设备集成测试（6 个）在没有 ADB 设备连接时会自动跳过。

---

## 设计原则

1. **零外部依赖** — 仅使用 Python 标准库（`send2trash` 为可选依赖）
2. **纯函数优先** — `quick_hash`、`parse_musicignore`、`matches_any_rule` 等核心函数无 I/O 无副作用
3. **依赖注入** — `Device` 接受 `adb_path` 参数，测试时可 mock `subprocess.run`
4. **静默降级** — `.musicignore` 解析失败不抛异常，静默回退到无规则状态
5. **取消安全** — 所有长时操作接受 `CancelFlag`，取消时立即安全退出
6. **二进制安全** — ADB 文件读取使用 `exec-out` + `dd iflag` 确保数据完整性
