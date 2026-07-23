---
name: compare-hash-redundant-removal
description: compare() 中"大小不同→哈希确认"分支因 file_size 参与哈希而逻辑冗余，移除后简化比对、零回归
metadata:
  type: project
---

# compare() 哈希比对逻辑冗余——移除优化

## 发现

`quick_hash` 算法为 `SHA-256(head_64KB + tail_64KB + str(file_size))`，其中 `file_size` 被编码进哈希输入。

`compare()` 中"两端都有 + 大小不同 → 调用 `_ensure_hash()` 计算哈希 → 比对"分支存在逻辑冗余：
因为 `file_size` 参与哈希计算，不同大小的文件哈希**必然不同**（SHA-256 抗碰撞性），`hash_src == hash_dst` 在 `src.size != dst.size` 前提下数学上不可能为真。

该分支唯一的实际价值是"防御 ADB 文件大小上报错误"，但即使在那场景下，错误上报的大小也会导致哈希不同，无法真正"挽救"这种情况。

## 修改

| 文件 | 变更 |
|------|------|
| `musicsync/core/sync_engine.py` | 移除 `_ensure_hash()` 函数、`compute_local_hash` import；`compare()` 中大小不同直接判定 overwrite |
| `musicsync/tests/test_sync_engine_compare.py` | `test_different_size_same_hash` → `test_different_size_always_overwrite` |

## 不变

哈希在 **execute 阶段** 仍完整保留，用于传输后完整性验证：
- `transfer_with_verify()` — 每次 copy/overwrite 后源端 vs 目的端 quick_hash 比对
- `safe_delete_remote()` — 删除 Phone 端文件前，先 pull 备份 → 哈希验证 → 再删

**Why:** quick_hash 的 `file_size` 参数使比对阶段的哈希检查成为死代码分支。直接依据大小差异判定，逻辑更简洁，比对阶段从"路径+大小+哈希"三级降为"路径+大小"两级。

**How to apply:** 若将来修改 `quick_hash` 使其不再包含 `file_size`，需重新评估是否在 `compare()` 中恢复哈希比对——那时它会有实际意义（同一文件因 ID3 标签差异导致大小略不同时，可通过头尾哈希判定为已同步）。
