"""MusicSync — 单向镜像音乐文件夹同步工具（GUI 入口）。

Windows 桌面应用。选择源路径与目的路径，按相对路径比对两端，
用户确认后执行镜像同步。支持 PC ↔ Android（ADB）三种设备组合。
"""

import faulthandler
import sys
import os

# ── 先启用 faulthandler（在 segfault 时输出 Python traceback） ──
# 将 traceback 写入 stderr（命令行可见）+ 日志文件
log_dir_for_fault = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "logs"
)
os.makedirs(log_dir_for_fault, exist_ok=True)
fault_log_path = os.path.join(log_dir_for_fault, "musicsync_crash.log")

try:
    fault_file = open(fault_log_path, "a", encoding="utf-8")
    faulthandler.enable(file=fault_file, all_threads=True)
    # 保留引用以防被 GC
except Exception:
    # 如果文件模式失败，退回到 stderr
    faulthandler.enable(all_threads=True)
    fault_file = None

# ── 日志初始化 ──
from musicsync.ui.utils import setup_logging, logger

setup_logging()

# 在 faulthandler 日志中也记一条启动标记
if fault_file:
    import datetime
    fault_file.write(f"\n{'='*60}\n")
    fault_file.write(f"MusicSync 启动 {datetime.datetime.now().isoformat()}\n")
    fault_file.write(f"{'='*60}\n")
    fault_file.flush()

# ── 入口 ──
if __name__ == "__main__":
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        logger.critical("PySide6 未安装。请运行: pip install PySide6>=6.5")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("MusicSync")
    app.setApplicationVersion("0.3.0")
    app.setOrganizationName("MusicSync")

    from musicsync.ui.main_window import MainWindow
    from musicsync.ui.utils import get_app_dir

    window = MainWindow(db_path=os.path.join(get_app_dir(), "musicsync.db"))
    window.show()

    logger.info("主窗口已显示")
    sys.exit(app.exec())
