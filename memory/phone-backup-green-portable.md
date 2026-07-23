---
name: phone-backup-green-portable
description: Phone 端删除备份目录改为程序运行目录下，消除用户目录污染
metadata:
  type: project
---

# Phone 端删除备份目录绿色化

## 问题

PC→Phone 同步时，在 Phone 端删除文件前会先 pull 到 PC 备份。原实现使用 `tempfile.gettempdir()` 即 Windows 系统临时目录（`C:\Users\<user>\AppData\Local\Temp\musicsync_phone_backup\`），违背程序"绿色不污染用户目录"原则。

## 修改

[executor.py](musicsync/core/executor.py#L70-L87) — `backup_dir` 默认值逻辑：

- **Phone 端删除**：`<app_dir>/backups/<dest_dir_name>_phone_backup/`（程序运行目录下）
- **PC 端删除**：`<dest_root>_backup/`（与目的目录同级，不变）

`app_dir` 通过 `sys.frozen` 判断打包/开发模式：
- 打包后：`os.path.dirname(sys.executable)`
- 开发模式：从 `executor.py` 位置向上 3 级找到项目根

## 审计结论 — 所有文件写入位置均为程序目录

| # | 内容 | 路径 |
|---|---|---|
| 1 | SQLite DB | `<app_dir>/musicsync.db` |
| 2 | SQLite WAL/SHM | `<app_dir>/musicsync.db-wal` `.db-shm` |
| 3 | 运行日志 | `<app_dir>/logs/musicsync_YYYY-MM-DD.log` |
| 4 | 崩溃日志 | `<app_dir>/logs/musicsync_crash.log` |
| 5 | Phone 删除备份 | `<app_dir>/backups/<dir>_phone_backup/`（已修复） |

**无**任何写入到 `%APPDATA%`、`%USERPROFILE%`、`%LOCALAPPDATA%` 或 `~/Documents`。满足 PyInstaller `--onedir` 绿色封装要求。

**Why:** 用户反馈删除备份污染了 Win 用户目录，不符合绿色程序原则。

**How to apply:** 涉及执行/备份相关改动时，确保备份路径始终在程序运行目录下。PyInstaller 打包后通过 `sys.frozen` 判断路径。
[[operation-history-five-bugs]]
[[phone-to-pc-pull-failure-roots]]
