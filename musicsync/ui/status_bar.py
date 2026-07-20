"""底部状态栏 — 进度信息 + 警告消息 + 统计。

对外接口:
    - update_progress(stage, phase, current, total, detail)
    - set_warning(text, level)  — INFO/WARNING/ERROR/FATAL 颜色区分
    - set_stats(total, selected, estimated_bytes)
    - clear()
"""

from PySide6.QtWidgets import QStatusBar, QLabel, QProgressBar, QHBoxLayout, QWidget
from PySide6.QtCore import Qt


# 颜色方案
LEVEL_COLORS = {
    "INFO":    "#1a73e8",  # 蓝色
    "WARNING": "#B8860B",  # 暗金
    "ERROR":   "#CC5500",  # 深橙
    "FATAL":   "#CC0000",  # 红色
}

LEVEL_DEFAULT = "#1a73e8"


class StatusBar(QStatusBar):
    """底部状态栏：进度条 + 进度文本 + 统计信息 + 警告消息。

    由 MainWindow 统一连接 Worker 信号到此组件。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeGripEnabled(True)

        # 进度文本（左）
        self._label = QLabel("就绪")
        self._label.setMinimumWidth(200)

        # 进度条
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setMaximumWidth(250)
        self._progress_bar.setVisible(False)
        self._progress_bar.setTextVisible(True)

        # 统计信息（中央）
        self._stats_label = QLabel("")
        self._stats_label.setAlignment(Qt.AlignCenter)

        # 警告标签（右）
        self._warning_label = QLabel("")
        self._warning_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        # 永久 widget
        self.addPermanentWidget(self._label)
        self.addPermanentWidget(self._progress_bar, 1)
        self.addPermanentWidget(self._stats_label, 2)
        self.addPermanentWidget(self._warning_label)

        # 初始消息
        self.showMessage("就绪 — 请选择源路径和目的路径", 3000)

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def update_progress(self, stage: str, phase: str, current: int, total: int, detail: str) -> None:
        """更新进度显示。

        Args:
            stage: "scan" | "compare" | "execute"
            phase: "source" | "dest" | "comparing" | "transferring" | "deleting" | "done"
            current: 当前进度
            total: 总数
            detail: 正在处理的文件名（可为空）
        """
        PHASE_NAMES = {
            "source":       "扫描源端",
            "dest":         "扫描目的端",
            "comparing":    "比对分析",
            "transferring": "传输中",
            "deleting":     "删除中",
            "done":         "完成",
        }
        STAGE_NAMES = {
            "scan":    "扫描",
            "compare": "比对",
            "execute": "执行",
        }
        phase_cn = PHASE_NAMES.get(phase, phase)
        stage_cn = STAGE_NAMES.get(stage, stage)

        if phase == "done":
            self._progress_bar.setVisible(False)
            if detail:
                self._label.setText(f"{stage_cn}完成: {detail}")
            else:
                self._label.setText(f"{stage_cn}完成")
            self._progress_bar.setValue(100)
        else:
            self._progress_bar.setVisible(True)
            if total > 0:
                pct = min(100, (current * 100) // total)
                self._progress_bar.setValue(pct)
            else:
                self._progress_bar.setRange(0, 0)  # 不确定模式

            if detail:
                self._label.setText(f"{stage_cn} — {phase_cn} ({current}/{total}) {detail}")
            else:
                self._label.setText(f"{stage_cn} — {phase_cn} ({current}/{total})")

        if current == total and total > 0:
            self._progress_bar.setRange(0, 100)

    def set_warning(self, text: str, level: str = "INFO") -> None:
        """设置警告/错误消息和颜色。

        Args:
            text: 消息文本，空字符串清除
            level: "INFO" | "WARNING" | "ERROR" | "FATAL"
        """
        color = LEVEL_COLORS.get(level, LEVEL_DEFAULT)
        self._warning_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        self._warning_label.setText(text)

    def set_stats(self, total: int, selected: int, estimated_bytes: int) -> None:
        """更新底部统计信息。

        Args:
            total: 差异总数
            selected: 已勾选数量
            estimated_bytes: 预估传输量（字节）
        """
        from musicsync.adb_device_kit.executor_helpers import format_size
        size_str = format_size(estimated_bytes)
        self._stats_label.setText(
            f"共 {total} 项差异  |  已勾选 {selected} 项  |  预估传输量 {size_str}"
        )

    def clear(self) -> None:
        """重置状态栏到初始状态。"""
        self._label.setText("就绪")
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(False)
        self._stats_label.setText("")
        self._warning_label.setText("")
