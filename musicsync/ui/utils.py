"""UI 共享工具函数和日志初始化。

日志基础设施:
    - ``setup_logging()`` — 初始化 Python logging + Qt 消息路由
    - ``status_warning_text`` — 模块级变量，状态栏可绑定读取
"""

import logging
import logging.handlers
import os
import sys
import platform
from datetime import datetime

try:
    import PySide6
except ImportError:
    PySide6 = None


# ---------------------------------------------------------------------------
# 模块级状态（状态栏读取）
# ---------------------------------------------------------------------------

_status_warning_text: str = ""


def get_status_warning() -> str:
    """返回当前待显示在状态栏的警告/错误文本。"""
    return _status_warning_text


def set_status_warning(text: str) -> None:
    """设置状态栏警告文本（模块级共享）。"""
    global _status_warning_text
    _status_warning_text = text


# ---------------------------------------------------------------------------
# 日志初始化
# ---------------------------------------------------------------------------

# 全局 logger 实例
logger = logging.getLogger("musicsync")

# Qt 消息处理器状态
_qt_handler_installed = False
_qt_handler_active = False  # 防重入标志


def _qt_message_handler(msg_type, context):
    """将 Qt 内部消息路由到 Python logging。

    通过 ``qInstallMessageHandler`` 注册，所有 Qt 的 qDebug/qWarning/
    qCritical/qFatal 输出会被转发到 Python logging 统一管道。

    防重入保护：如果 handler 本身触发了 Qt 消息，直接写入 stderr 作为保底。
    """
    global _qt_handler_active
    if _qt_handler_active:
        # 防重入：保底输出到 stderr
        sys.stderr.write(f"[Qt-reentrant] {msg_type}: {context}\n")
        return

    _qt_handler_active = True
    try:
        msg = str(context)
        if msg_type == 0:  # QtDebugMsg
            logger.debug("Qt: %s", msg)
        elif msg_type == 1:  # QtWarningMsg
            logger.warning("Qt: %s", msg)
        elif msg_type == 2:  # QtCriticalMsg
            logger.error("Qt: %s", msg)
        elif msg_type == 3:  # QtFatalMsg
            logger.critical("Qt FATAL: %s", msg)
            set_status_warning(f"致命错误: {msg}")
        else:
            logger.info("Qt: %s", msg)
    finally:
        _qt_handler_active = False


def setup_logging(log_dir: str = "") -> None:
    """初始化 Python logging + 安装 Qt 消息处理器。

    日志文件命名格式 ``musicsync_YYYY-MM-DD.log``，使用
    ``RotatingFileHandler``（5 文件 × 1MB 滚动覆盖）。

    Qt 消息通过 ``qInstallMessageHandler`` 路由到同一日志管道。

    Args:
        log_dir: 日志目录，默认 ``<程序所在目录>/logs/``
    """
    global _qt_handler_installed

    # 确定日志目录
    if not log_dir:
        if getattr(sys, "frozen", False):
            # PyInstaller 打包后
            app_dir = os.path.dirname(sys.executable)
        else:
            # 开发模式
            app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        log_dir = os.path.join(app_dir, "logs")

    os.makedirs(log_dir, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    log_path = os.path.join(log_dir, f"musicsync_{today}.log")

    # ── Python logging 配置 ──
    handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=1024 * 1024,   # 1 MB
        backupCount=4,           # 保留 4 个备份 = 5 个文件
        encoding="utf-8",
    )
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    # 同时输出到 stderr（控制台可见）
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.WARNING)  # stderr 只看 WARNING 以上
    logger.addHandler(stream_handler)

    # ── 启动日志头 ──
    logger.info("=" * 60)
    logger.info("MusicSync 启动")
    logger.info("Python %s", sys.version.split()[0])
    if PySide6:
        try:
            from PySide6.QtCore import __version__ as qt_version
            logger.info("PySide6 %s | Qt %s", PySide6.__version__, qt_version)
        except Exception:
            logger.info("PySide6 %s", PySide6.__version__)
    else:
        logger.info("PySide6: 未安装")
    logger.info("平台: %s %s %s", platform.system(), platform.release(), platform.version())
    logger.info("日志文件: %s", log_path)
    logger.info("=" * 60)

    # ── 安装 Qt 消息处理器 ──
    if not _qt_handler_installed and PySide6:
        try:
            from PySide6.QtCore import qInstallMessageHandler, QtMsgType
            qInstallMessageHandler(_qt_message_handler)
            _qt_handler_installed = True
            logger.debug("Qt 消息处理器已安装")
        except Exception as e:
            logger.warning("无法安装 Qt 消息处理器: %s", e)
