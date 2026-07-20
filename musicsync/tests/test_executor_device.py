"""test_executor_device.py — executor 设备分发单元测试。

用真实 PC 文件 + mock Device 验证 execute() 的 dispatch 逻辑。
mock Device 的 push/pull 执行真实的文件复制以确保 transfer_with_verify 哈希通过。
"""

import os
import shutil
import pytest
from unittest import mock

from musicsync.adb_device_kit.models import ActionResult
from musicsync.adb_device_kit.cancel_flag import CancelFlag
from musicsync.core.models import DiffItem
from musicsync.core.executor import execute


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _diff(**kw) -> DiffItem:
    defaults = {
        "relative_path": "song.flac",
        "diff_type": "new_in_dest",
        "operation": "copy",
        "direction": "source → dest",
        "source_size": 100,
        "dest_size": None,
        "selected": True,
    }
    defaults.update(kw)
    return DiffItem(**defaults)


def _make_mock_device(name: str = "mock_device", real_hash: bool = False):
    """构造 mock Device。push/pull 做真实文件复制以确保哈希校验通过。

    ``read_head_tail`` 返回与 ``compute_local_hash`` 一致的数据，
    使得 transfer_with_verify 的 source + dest 哈希匹配。
    """
    d = mock.MagicMock()
    d.name = name

    # 记录 push/pull 调用参数
    d._push_src = None
    d._push_dst = None
    d._pull_src = None
    d._pull_dst = None

    def _push(local: str, remote: str, cancel_flag=None) -> bool:
        d._push_src = local
        d._push_dst = remote
        try:
            os.makedirs(os.path.dirname(remote), exist_ok=True)
            shutil.copy2(local, remote)
            return True
        except OSError:
            return False

    def _pull(remote: str, local: str, cancel_flag=None) -> bool:
        d._pull_src = remote
        d._pull_dst = local
        try:
            os.makedirs(os.path.dirname(local), exist_ok=True)
            shutil.copy2(remote, local)
            return True
        except OSError:
            return False

    def _delete(path: str, cancel_flag=None) -> bool:
        try:
            os.unlink(path)
            return True
        except OSError:
            return False

    def _stat(path: str):
        if os.path.exists(path):
            st = os.stat(path)
            from datetime import datetime, timezone
            return {
                "size": st.st_size,
                "modified": datetime.fromtimestamp(
                    st.st_mtime, tz=timezone.utc
                ).isoformat(),
            }
        return None

    def _read_head_tail(path: str, cancel_flag=None):
        """读取真实文件的头尾数据（与 compute_local_hash 一致）。"""
        try:
            with open(path, "rb") as f:
                head = f.read(64 * 1024)
                file_size = os.path.getsize(path)
                if file_size <= 64 * 1024:
                    return (head, b"")
                tail_start = max(file_size - 64 * 1024, 0)
                f.seek(tail_start)
                tail = f.read(64 * 1024)
                return (head, tail)
        except OSError:
            return (None, None)

    d.push.side_effect = _push
    d.pull.side_effect = _pull
    d.delete.side_effect = _delete
    d.stat.side_effect = _stat
    d.read_head_tail.side_effect = _read_head_tail

    return d


# ---------------------------------------------------------------------------
# PC→PC dispatch
# ---------------------------------------------------------------------------

class TestPcToPc:
    """PC→PC 路径：保持原有行为，不使用 Device。"""

    def test_copy_uses_local_hash(self, tmp_path):
        """PC→PC copy 应使用 compute_local_hash + shutil.copy2。"""
        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        os.makedirs(src_dir)
        os.makedirs(dst_dir)
        (src_dir / "song.flac").write_bytes(b"x" * 200)

        diffs = [_diff(relative_path="song.flac", source_size=200)]
        # 不传 device，走 PC→PC
        result = execute(diffs, str(src_dir), str(dst_dir))
        assert result.success_count == 1
        assert (dst_dir / "song.flac").read_bytes() == b"x" * 200

    def test_delete_uses_safe_delete_local(self, tmp_path):
        """PC→PC delete 应使用 safe_delete_local。"""
        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        backup = tmp_path / "backup"
        os.makedirs(src_dir)
        os.makedirs(dst_dir)
        os.makedirs(backup)
        (dst_dir / "stale.flac").write_bytes(b"old")

        diffs = [_diff(
            relative_path="stale.flac",
            diff_type="only_in_dest",
            operation="delete",
            source_size=None,
            dest_size=3,
        )]
        result = execute(
            diffs, str(src_dir), str(dst_dir),
            backup_dir=str(backup),
        )
        assert result.success_count == 1
        assert not (dst_dir / "stale.flac").exists()


# ---------------------------------------------------------------------------
# PC→Phone dispatch（mock Device）
# ---------------------------------------------------------------------------

class TestPcToPhoneDispatch:
    """PC→Phone 路径：验证 push + quick_hash（手机端）被调用。"""

    def test_copy_calls_push(self, tmp_path):
        """PC→Phone copy 应使用 device.push 传输。"""
        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        os.makedirs(src_dir)
        os.makedirs(dst_dir)
        (src_dir / "song.flac").write_bytes(b"a" * 200)

        device = _make_mock_device()

        diffs = [_diff(relative_path="song.flac", source_size=200)]
        result = execute(
            diffs, str(src_dir), str(dst_dir),
            dest_device=device,
        )
        assert result.success_count == 1
        # 验证 push 被调用
        device.push.assert_called_once()
        # 验证 read_head_tail 被调用（手机端哈希）
        device.read_head_tail.assert_called()

    def test_push_failure_reported(self, tmp_path):
        """push 失败时应报告失败。"""
        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        os.makedirs(src_dir)
        os.makedirs(dst_dir)
        (src_dir / "song.flac").write_bytes(b"b" * 200)

        # 用真正的 mock 会走真实文件复制；改用 side_effect 直接控制
        device = _make_mock_device()
        device.push.side_effect = None
        device.push.return_value = False

        diffs = [_diff(relative_path="song.flac", source_size=200)]
        result = execute(
            diffs, str(src_dir), str(dst_dir),
            dest_device=device,
        )
        assert result.failure_count == 1
        device.push.assert_called()

    def test_delete_calls_safe_delete_remote(self, tmp_path):
        """PC→Phone delete 应调用 safe_delete_remote。"""
        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        os.makedirs(src_dir)
        os.makedirs(dst_dir)
        # safe_delete_remote 需要文件存在于 phone_dst 路径上
        # mock Device 的 stat 会读取实际文件系统
        (dst_dir / "song.flac").write_bytes(b"x" * 50)

        device = _make_mock_device()

        diffs = [_diff(
            relative_path="song.flac",
            diff_type="only_in_dest",
            operation="delete",
            source_size=None,
            dest_size=50,
        )]
        result = execute(
            diffs, str(src_dir), str(dst_dir),
            dest_device=device,
        )
        assert result.success_count == 1
        # 验证 pull（备份）被调用
        device.pull.assert_called()
        device.delete.assert_called_once()


# ---------------------------------------------------------------------------
# Phone→PC dispatch（mock Device）
# ---------------------------------------------------------------------------

class TestPhoneToPcDispatch:
    """Phone→PC 路径：验证 pull + quick_hash（手机端源）被调用。"""

    def test_copy_calls_pull(self, tmp_path):
        """Phone→PC copy 应使用 device.pull 传输。"""
        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        os.makedirs(src_dir)
        os.makedirs(dst_dir)
        # Phone→PC: src_path 是 phone_src，在 executor 中拼接
        # 文件必须在 src_dir 下存在（因为 phone_src 拼接 src_root + rel）
        (src_dir / "song.flac").write_bytes(b"p" * 150)

        device = _make_mock_device()

        diffs = [_diff(relative_path="song.flac", source_size=150)]
        result = execute(
            diffs, str(src_dir), str(dst_dir),
            source_device=device,
        )
        assert result.success_count == 1
        device.pull.assert_called_once()
        device.read_head_tail.assert_called()

    def test_delete_uses_local(self, tmp_path):
        """Phone→PC delete 应使用 safe_delete_local（目的端是 PC）。"""
        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        backup = tmp_path / "backup"
        os.makedirs(src_dir)
        os.makedirs(dst_dir)
        os.makedirs(backup)
        (dst_dir / "song.flac").write_bytes(b"old-data")

        device = _make_mock_device()

        diffs = [_diff(
            relative_path="song.flac",
            diff_type="only_in_dest",
            operation="delete",
            source_size=None,
            dest_size=8,
        )]
        result = execute(
            diffs, str(src_dir), str(dst_dir),
            source_device=device,
            backup_dir=str(backup),
        )
        assert result.success_count == 1
        assert not (dst_dir / "song.flac").exists()


# ---------------------------------------------------------------------------
# Phone→Phone 被拒绝
# ---------------------------------------------------------------------------

class TestPhoneToPhone:
    """Phone→Phone 应显式抛出 NotImplementedError。"""

    def test_phone_to_phone_raises(self, tmp_path):
        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        os.makedirs(src_dir)
        os.makedirs(dst_dir)

        d1 = _make_mock_device("phone1")
        d2 = _make_mock_device("phone2")

        with pytest.raises(NotImplementedError, match="Phone→Phone"):
            execute([], str(src_dir), str(dst_dir), source_device=d1, dest_device=d2)


# ---------------------------------------------------------------------------
# cancel_flag 跨设备组合
# ---------------------------------------------------------------------------

class TestCancelFlagDispatch:
    """cancel_flag 应在所有设备组合中被检查。"""

    def test_cancel_pc_to_phone(self, tmp_path):
        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        os.makedirs(src_dir)
        os.makedirs(dst_dir)
        (src_dir / "x.flac").write_bytes(b"x")

        device = _make_mock_device()
        flag = CancelFlag()
        flag.cancel()

        diffs = [_diff(relative_path="x.flac", source_size=1)]
        result = execute(
            diffs, str(src_dir), str(dst_dir),
            dest_device=device,
            cancel_flag=flag,
        )
        assert result.skip_count >= 1

    def test_cancel_phone_to_pc(self, tmp_path):
        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        os.makedirs(src_dir)
        os.makedirs(dst_dir)

        device = _make_mock_device()
        flag = CancelFlag()
        flag.cancel()

        diffs = [_diff(relative_path="x.flac", source_size=1)]
        result = execute(
            diffs, str(src_dir), str(dst_dir),
            source_device=device,
            cancel_flag=flag,
        )
        assert result.skip_count >= 1
