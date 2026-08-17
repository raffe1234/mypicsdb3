from __future__ import annotations

from types import SimpleNamespace

from mypicsdb3 import filesystem


class _BinaryKodiFile:
    def __init__(self, data: bytes):
        self.data = data
        self.position = 0
        self.text_reads = 0
        self.byte_reads = 0

    def readBytes(self, size: int):
        self.byte_reads += 1
        start = self.position
        end = min(len(self.data), start + max(0, int(size)))
        self.position = end
        return bytearray(self.data[start:end])

    def read(self, _size: int):
        self.text_reads += 1
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    def seek(self, offset: int, whence: int = 0):
        if whence == 0:
            self.position = int(offset)
        elif whence == 1:
            self.position += int(offset)
        elif whence == 2:
            self.position = len(self.data) + int(offset)
        return self.position

    def size(self):
        return len(self.data)

    def close(self):
        return None


def test_kodi_file_adapter_uses_binary_vfs_read_for_jpeg(monkeypatch) -> None:
    jpeg = b"\xff\xd8\xff\xe1\x00\x10Exif\x00\x00payload"
    handle = _BinaryKodiFile(jpeg)
    fake_vfs = SimpleNamespace(File=lambda _path, _mode="": handle)
    monkeypatch.setattr(filesystem, "xbmcvfs", fake_vfs)

    with filesystem.KodiFileAdapter("smb://nas/picture.jpg") as stream:
        assert stream.read(6) == jpeg[:6]
        assert stream.read(4) == jpeg[6:10]

    assert handle.byte_reads == 2
    assert handle.text_reads == 0


def test_kodi_file_adapter_read_all_uses_binary_vfs_read(monkeypatch) -> None:
    data = b"\xff\xd8binary\x00\xffdata"
    handle = _BinaryKodiFile(data)
    fake_vfs = SimpleNamespace(File=lambda _path, _mode="": handle)
    monkeypatch.setattr(filesystem, "xbmcvfs", fake_vfs)

    with filesystem.KodiFileAdapter("smb://nas/picture.jpg") as stream:
        assert stream.read() == data

    assert handle.byte_reads == 1
    assert handle.text_reads == 0
