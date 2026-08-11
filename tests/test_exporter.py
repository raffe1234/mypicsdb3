from __future__ import annotations

import json
from pathlib import Path

from mypicsdb3.exporter import SafeExporter, normalize_export_name
from mypicsdb3.filesystem import LocalFilesystem


class FakeCatalog:
    def __init__(self, rows, source_roots=()):
        self.rows = {int(row["id"]): dict(row) for row in rows}
        self.requests = []
        self.source_roots = tuple(source_roots)

    def get_sources(self):
        return [type("Source", (), {"uri": value})() for value in self.source_roots]

    def media_for_export(self, picture_ids):
        ids = [int(value) for value in picture_ids]
        self.requests.append(ids)
        return [dict(self.rows[value]) for value in ids if value in self.rows]


def row(media_id: int, uri: Path, filename: str | None = None):
    return {
        "id": media_id,
        "uri": str(uri),
        "filename": filename or uri.name,
        "media_type": "picture",
        "file_size": uri.stat().st_size if uri.exists() else 0,
        "file_mtime": uri.stat().st_mtime if uri.exists() else 0,
        "source_label": "Photos",
    }


def test_safe_export_copies_without_overwriting_and_writes_manifest(tmp_path: Path) -> None:
    source_a = tmp_path / "source-a"
    source_b = tmp_path / "source-b"
    source_a.mkdir()
    source_b.mkdir()
    first = source_a / "same.jpg"
    second = source_b / "same.jpg"
    missing = source_b / "gone.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    destination = tmp_path / "exports"
    destination.mkdir()
    # Existing folders and files must never be overwritten.
    (destination / "Trip").mkdir()

    catalog = FakeCatalog([row(1, first), row(2, second), row(3, missing)])
    result = SafeExporter(
        catalog,
        LocalFilesystem(),
        "0.8.17",
    ).export_ids([1, 2, 3], str(destination), "Trip", "Trip selection")

    export_dir = Path(result.export_uri)
    assert export_dir.name == "Trip (2)"
    assert (export_dir / "same.jpg").read_bytes() == b"first"
    assert (export_dir / "same (2).jpg").read_bytes() == b"second"
    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"second"
    assert result.selected == 3
    assert result.processed == 3
    assert result.copied == 2
    assert result.missing == 1
    assert result.failed == 0
    assert result.collisions == 1
    assert result.cancelled is False

    manifest = json.loads((export_dir / "mypicsdb3-export-manifest.json").read_text())
    assert manifest["manifest_version"] == 1
    assert manifest["mypicsdb3_version"] == "0.8.17"
    assert manifest["status"] == "completed"
    assert manifest["selection"] == {"label": "Trip selection", "selected": 3}
    assert manifest["summary"]["copied"] == 2
    assert manifest["summary"]["missing"] == 1
    assert [entry["status"] for entry in manifest["items"]] == [
        "copied",
        "copied",
        "missing",
    ]
    assert manifest["items"][1]["renamed_for_collision"] is True


def test_safe_export_cancel_keeps_copied_files_and_final_cancelled_manifest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    first = source / "one.jpg"
    second = source / "two.jpg"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    destination = tmp_path / "exports"
    destination.mkdir()
    state = {"done": 0}

    def cancelled():
        return state["done"] >= 1

    def progress(done, total, filename):
        state["done"] = done
        assert total == 2
        assert filename

    result = SafeExporter(
        FakeCatalog([row(1, first), row(2, second)]),
        LocalFilesystem(),
        "0.8.17",
    ).export_ids(
        [1, 2],
        str(destination),
        "Partial",
        "Partial selection",
        cancelled=cancelled,
        progress=progress,
    )

    export_dir = Path(result.export_uri)
    assert result.cancelled is True
    assert result.processed == 1
    assert result.copied == 1
    assert (export_dir / "one.jpg").exists()
    assert not (export_dir / "two.jpg").exists()
    manifest = json.loads((export_dir / "mypicsdb3-export-manifest.json").read_text())
    assert manifest["status"] == "cancelled"
    assert manifest["selection"]["selected"] == 2
    assert manifest["summary"]["processed"] == 1


def test_export_name_is_portable_and_does_not_allow_path_components() -> None:
    assert normalize_export_name(r"../A:Trip?\\Summer*") == "Summer_"
    assert normalize_export_name("CON") == "_CON"


def test_safe_export_refuses_destination_inside_a_catalog_source(tmp_path: Path) -> None:
    source = tmp_path / "photos"
    source.mkdir()
    media = source / "one.jpg"
    media.write_bytes(b"one")
    catalog = FakeCatalog([row(1, media)], source_roots=(str(source),))

    try:
        SafeExporter(catalog, LocalFilesystem(), "0.8.17").export_ids(
            [1], str(source), "Export", "Unsafe destination"
        )
    except Exception as exc:
        assert "outside configured picture sources" in str(exc)
    else:
        raise AssertionError("Exports inside indexed picture sources must be rejected")
    assert not (source / "Export").exists()


def test_manifest_redacts_credentials_from_source_and_destination_uris(tmp_path: Path) -> None:
    class CredentialFilesystem(LocalFilesystem):
        def __init__(self, source_file: Path, destination_dir: Path):
            self.source_file = source_file
            self.destination_dir = destination_dir

        @staticmethod
        def _local(path: str) -> Path:
            from urllib.parse import urlsplit

            parts = urlsplit(path)
            if parts.scheme == "smb":
                if parts.path.endswith("/one.jpg"):
                    return source_file
                return destination_dir / Path(parts.path).name
            return Path(path)

        def exists(self, path: str) -> bool:
            return self._local(path).exists()

        def makedirs(self, path: str) -> bool:
            self._local(path).mkdir(parents=True, exist_ok=True)
            return True

        def copy(self, source: str, destination: str) -> bool:
            import shutil

            shutil.copy2(self._local(source), self._local(destination))
            return True

        def write_text(self, path: str, text: str) -> None:
            self._local(path).write_text(text, encoding="utf-8")

    source_file = tmp_path / "one.jpg"
    source_file.write_bytes(b"one")
    destination_dir = tmp_path / "Export"
    catalog = FakeCatalog(
        [
            {
                "id": 1,
                "uri": "smb://secret-user:secret-password@nas/photos/one.jpg?token=source-secret",
                "filename": "one.jpg",
                "media_type": "picture",
                "file_size": 3,
                "file_mtime": 1.0,
                "source_label": "Photos",
            }
        ]
    )
    filesystem = CredentialFilesystem(source_file, destination_dir)
    result = SafeExporter(catalog, filesystem, "0.8.17").export_ids(
        [1],
        "smb://export-user:export-password@nas/exports/",
        "Export",
        "Credential test",
    )

    manifest = json.loads(filesystem._local(result.manifest_uri).read_text(encoding="utf-8"))
    rendered = json.dumps(manifest)
    assert "secret-user" not in rendered
    assert "secret-password" not in rendered
    assert "export-user" not in rendered
    assert "export-password" not in rendered
    assert "source-secret" not in rendered
    assert manifest["items"][0]["source_uri"] == "smb://nas/photos/one.jpg"
    assert manifest["destination"].startswith("smb://nas/")


def test_source_tree_protection_ignores_vfs_credentials(tmp_path: Path) -> None:
    source = tmp_path / "one.jpg"
    source.write_bytes(b"one")

    class UriFilesystem(LocalFilesystem):
        def exists(self, path: str) -> bool:
            if path.startswith("smb://"):
                return False
            return super().exists(path)

        def makedirs(self, path: str) -> bool:
            raise AssertionError("unsafe source-tree destination must be rejected before mkdir")

    catalog = FakeCatalog(
        [row(1, source)],
        source_roots=("smb://reader:secret@nas/photos/",),
    )
    try:
        SafeExporter(catalog, UriFilesystem(), "0.8.17").export_ids(
            [1],
            "smb://writer:other@nas/photos/exports/",
            "Export",
            "Credential-root test",
        )
    except Exception as exc:
        assert "outside configured picture sources" in str(exc)
    else:
        raise AssertionError("source-tree check must ignore differing URI credentials")
