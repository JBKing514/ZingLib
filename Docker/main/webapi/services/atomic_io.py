"""Replace a file in one step, so a crash cannot leave a half-written one.

Every file ZingLib writes back to a library -- ComicInfo.xml inside a gallery
folder, the rebuilt `.cbz`, the per-gallery sidecar -- is a *replacement* of
something that already exists and is the only copy of the user's metadata. A
plain `write_bytes()` truncates that file first and fills it in bytes at a time,
so a full disk or a killed process leaves a truncated file where a valid one used
to be. The report called this out directly: "verify that a corrupt sidecar, a
full disk, an unavailable permission or an interrupted process cannot destroy an
existing backup".

The pattern here is the only one that survives that: write a sibling temp file,
flush and `fsync` it, then `os.replace` it over the target (atomic on POSIX and
on Windows for same-volume moves), and finally `fsync` the directory so the
rename itself is durable. Anything that goes wrong removes the temp file and
leaves the target exactly as it was.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _fsync_dir(directory: Path) -> None:
    """Make the rename durable. Best effort: Windows cannot open a directory."""
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def atomic_write_bytes(path: Path | str, data: bytes) -> None:
    """Write `data` to `path` atomically.

    Readers either see the previous contents or the complete new ones; there is
    no window in which the file exists but is short. Raises whatever the
    filesystem raises -- callers that must not raise (the sidecar writer) catch
    it themselves -- but always leaves the target untouched on failure.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    _fsync_dir(target.parent)


def atomic_write_text(path: Path | str, data: str, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, data.encode(encoding))
