from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO, Callable, Iterator, List, Optional, Tuple

from .models import FileStat
from .utils import basename_uri, join_uri, sha256_text

try:
    import xbmcvfs  # type: ignore
except ImportError:  # pragma: no cover
    xbmcvfs = None


class KodiFileAdapter:
    """Seekable binary wrapper around xbmcvfs.File for metadata libraries."""

    def __init__(self, path: str):
        if xbmcvfs is None:
            raise RuntimeError("xbmcvfs is unavailable")
        self._file = xbmcvfs.File(path, "rb")
        self._position = 0

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = max(0, self.size() - self._position)

        # Kodi's xbmcvfs.File.read() is a text API and may try to decode
        # arbitrary JPEG/EXIF bytes as UTF-8. Metadata parsers need the VFS
        # byte API instead; otherwise a perfectly valid 0xff JPEG marker can
        # raise UnicodeDecodeError before ExifRead or our fallback sees it.
        read_bytes = getattr(self._file, "readBytes", None)
        if callable(read_bytes):
            data = bytes(read_bytes(size))
        else:  # Compatibility for very old/test VFS shims without readBytes.
            data = self._file.read(size)
            if isinstance(data, str):
                data = data.encode("latin-1", "replace")
            elif not isinstance(data, bytes):
                data = bytes(data)

        self._position += len(data)
        return data

    def seek(self, offset: int, whence: int = 0) -> int:
        self._position = int(self._file.seek(offset, whence))
        return self._position

    def tell(self) -> int:
        return self._position

    def size(self) -> int:
        try:
            return int(self._file.size())
        except Exception:
            current = self.tell()
            end = self.seek(0, 2)
            self.seek(current, 0)
            return end

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "KodiFileAdapter":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


class Filesystem:
    def exists(self, path: str) -> bool:
        raise NotImplementedError

    def listdir(self, path: str) -> Tuple[List[str], List[str]]:
        raise NotImplementedError

    def stat(self, path: str) -> FileStat:
        raise NotImplementedError

    def open_binary(self, path: str):
        raise NotImplementedError

    def makedirs(self, path: str) -> bool:
        raise NotImplementedError

    def copy(self, source: str, destination: str) -> bool:
        raise NotImplementedError

    def write_text(self, path: str, text: str) -> None:
        raise NotImplementedError

    def read_prefix(self, path: str, max_bytes: int) -> bytes:
        with self.open_binary(path) as stream:
            return stream.read(max_bytes)

    @contextlib.contextmanager
    def materialized(self, path: str, max_bytes: Optional[int] = None) -> Iterator[Optional[str]]:
        raise NotImplementedError


class CheckedBinaryStream:
    """Run a cancellation check around potentially blocking stream calls."""

    def __init__(self, stream, check: Callable[[], None]):
        self._stream = stream
        self._check = check

    def read(self, size: int = -1):
        self._check()
        value = self._stream.read(size)
        self._check()
        return value

    def seek(self, offset: int, whence: int = 0):
        self._check()
        value = self._stream.seek(offset, whence)
        self._check()
        return value

    def tell(self):
        return self._stream.tell()

    def size(self):
        self._check()
        value = self._stream.size()
        self._check()
        return value

    def close(self) -> None:
        self._stream.close()

    def __enter__(self) -> "CheckedBinaryStream":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def __getattr__(self, name):
        return getattr(self._stream, name)


class CancellationAwareFilesystem(Filesystem):
    """Filesystem proxy that checks for cancellation between VFS operations.

    Kodi's xbmcvfs calls do not expose a per-call timeout or abort callback. This
    proxy therefore cannot interrupt an SMB call while it is blocked, but it
    makes the scanner stop immediately before the next operation and as soon as
    the current operation returns.
    """

    def __init__(self, filesystem: Filesystem, check: Callable[[], None]):
        self._filesystem = filesystem
        self._check = check

    def exists(self, path: str) -> bool:
        self._check()
        value = self._filesystem.exists(path)
        self._check()
        return value

    def listdir(self, path: str) -> Tuple[List[str], List[str]]:
        self._check()
        value = self._filesystem.listdir(path)
        self._check()
        return value

    def stat(self, path: str) -> FileStat:
        self._check()
        value = self._filesystem.stat(path)
        self._check()
        return value

    def open_binary(self, path: str):
        self._check()
        stream = self._filesystem.open_binary(path)
        try:
            self._check()
        except Exception:
            stream.close()
            raise
        return CheckedBinaryStream(stream, self._check)

    def makedirs(self, path: str) -> bool:
        self._check()
        value = self._filesystem.makedirs(path)
        self._check()
        return value

    def copy(self, source: str, destination: str) -> bool:
        self._check()
        value = self._filesystem.copy(source, destination)
        self._check()
        return value

    def write_text(self, path: str, text: str) -> None:
        self._check()
        self._filesystem.write_text(path, text)
        self._check()

    @contextlib.contextmanager
    def materialized(self, path: str, max_bytes: Optional[int] = None) -> Iterator[Optional[str]]:
        self._check()
        with self._filesystem.materialized(path, max_bytes) as local_path:
            self._check()
            yield local_path
            self._check()


class KodiFilesystem(Filesystem):
    def __init__(self, temp_dir: str):
        if xbmcvfs is None:
            raise RuntimeError("xbmcvfs is unavailable")
        self.temp_dir = temp_dir.rstrip("/\\")
        if not xbmcvfs.exists(self.temp_dir):
            xbmcvfs.mkdirs(self.temp_dir)

    def exists(self, path: str) -> bool:
        return bool(xbmcvfs.exists(path))

    def listdir(self, path: str) -> Tuple[List[str], List[str]]:
        directories, files = xbmcvfs.listdir(path)
        return list(directories), list(files)

    def stat(self, path: str) -> FileStat:
        stat = xbmcvfs.Stat(path)
        size = int(stat.st_size())
        mtime = float(stat.st_mtime())
        return FileStat(size=size, mtime=mtime)

    def open_binary(self, path: str) -> KodiFileAdapter:
        return KodiFileAdapter(path)

    def makedirs(self, path: str) -> bool:
        if xbmcvfs.exists(path):
            return True
        return bool(xbmcvfs.mkdirs(path))

    def copy(self, source: str, destination: str) -> bool:
        return bool(xbmcvfs.copy(source, destination))

    def write_text(self, path: str, text: str) -> None:
        handle = xbmcvfs.File(path, "w")
        try:
            try:
                written = handle.write(text)
            except TypeError:
                written = handle.write(text.encode("utf-8"))
            if written is False:
                raise OSError("Kodi VFS write returned false")
        finally:
            handle.close()

    @contextlib.contextmanager
    def materialized(self, path: str, max_bytes: Optional[int] = None) -> Iterator[Optional[str]]:
        translated = xbmcvfs.translatePath(path) if hasattr(xbmcvfs, "translatePath") else path
        if os.path.isfile(translated):
            yield translated
            return
        try:
            if max_bytes is not None and self.stat(path).size > max_bytes:
                yield None
                return
        except Exception:
            yield None
            return
        extension = basename_uri(path).rsplit(".", 1)[-1] if "." in basename_uri(path) else "bin"
        target = self.temp_dir + "/metadata-" + sha256_text(path)[:20] + "." + extension
        copied = False
        try:
            copied = bool(xbmcvfs.copy(path, target))
            yield target if copied else None
        finally:
            if copied and xbmcvfs.exists(target):
                xbmcvfs.delete(target)


class LocalFilesystem(Filesystem):
    """Local adapter used by tests and command-line development tools."""

    def exists(self, path: str) -> bool:
        return os.path.exists(path)

    def listdir(self, path: str) -> Tuple[List[str], List[str]]:
        directories: List[str] = []
        files: List[str] = []
        for entry in os.scandir(path):
            if entry.is_dir(follow_symlinks=False):
                directories.append(entry.name)
            elif entry.is_file(follow_symlinks=False):
                files.append(entry.name)
        return directories, files

    def stat(self, path: str) -> FileStat:
        value = os.stat(path)
        return FileStat(size=int(value.st_size), mtime=float(value.st_mtime))

    def open_binary(self, path: str) -> BinaryIO:
        return open(path, "rb")

    def makedirs(self, path: str) -> bool:
        os.makedirs(path, exist_ok=True)
        return True

    def copy(self, source: str, destination: str) -> bool:
        shutil.copy2(source, destination)
        return True

    def write_text(self, path: str, text: str) -> None:
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)

    @contextlib.contextmanager
    def materialized(self, path: str, max_bytes: Optional[int] = None) -> Iterator[Optional[str]]:
        if max_bytes is not None and os.path.getsize(path) > max_bytes:
            yield None
        else:
            yield path
