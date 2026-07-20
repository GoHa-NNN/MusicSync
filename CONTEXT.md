# MusicSync

单向镜像音乐文件夹同步工具。源为参照标准，目的被改造为与源一致。Windows PC ↔ Android（ADB），支持四种设备组合。

## Language

**源路径 (source path)**:
同步的参照标准——用户认为"这是对的"那一端。
_Avoid_: 主路径、标准路径

**目的路径 (dest path)**:
被同步的对象——将被改造为与源路径一致。
_Avoid_: 目标、目标路径

**镜像同步 (mirror sync)**:
严格单向操作：源始终覆盖目的，不存在反向复制或冲突裁决。
_Avoid_: 同步、双向同步、合并

**相对路径 (relative path)**:
文件相对于根路径的后缀部分，统一使用正斜杠。是比对阶段匹配两端文件的唯一键。
_Avoid_: 子路径、后缀路径

**根路径 (root path)**:
源端或目的端的顶层目录，扫描从此开始。文件路径 = 根路径 + 相对路径。

**差异类型 (diff type)**:
| 类型 | 条件 |
|------|------|
| `synced` | 两端都有、大小相同（不展示） |
| `new_in_dest` | 源有、目的无 |
| `updated_in_dest` | 两端都有、大小不同 |
| `only_in_dest` | 目的有、源无 |

**快速哈希 (quick hash)**:
`SHA-256(文件前 64KB + 文件后 64KB + str(文件大小))`。只读头尾各 64KB，I/O 成本 ~128KB。
_Avoid_: 预览哈希、轻量哈希

**音频白名单 (audio whitelist)**:
默认 7 种扩展名：`flac`, `mp3`, `wav`, `aac`, `ogg`, `m4a`, `wma`。非白名单文件在扫描阶段自动跳过。

**.musicignore**:
位于根路径下的排除规则文件，语法兼容 `.gitignore`（子集）。支持 glob 模式和目录规则。
_Avoid_: 过滤规则、排除列表

**操作历史 (operation history)**:
每次同步操作的完整记录，自包含（无需 JOIN）。包含时间、操作类型、方向、文件路径、大小。

## Device

**设备类型**: `pc`（Windows 本地文件系统）或 `phone`（通过 ADB 连接的 Android 设备）。

**四种设备组合**:
| 源 | 目的 | 场景 |
|----|------|------|
| PC | Phone | PC 标准库同步到手机 |
| Phone | PC | 手机新歌汇集到 PC |
| PC | PC | 两个本地文件夹同步 |
| Phone | Phone | 两台手机之间同步 |

**ADB**: Android Debug Bridge，MusicSync 仅支持 USB ADB（无 MTP、无网络传输）。
