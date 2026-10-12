"""Source selection and URI shaping. Nothing here contacts Azure or reads a document."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from ai_employee.db.models import SourceConnection, SourceKind
from ai_employee.knowledge.sources import (
    AzureBlobSource,
    LocalSource,
    SourceConfigError,
    _etag,
    source_for,
)


@dataclass
class FakeProperties:
    """Stands in for a BlobProperties; only `etag` is read."""

    etag: str | None


class TestEtag:
    def test_quotes_are_stripped(self) -> None:
        assert _etag(FakeProperties(etag='"0x8DC1"')) == "0x8DC1"

    def test_unquoted_etag_is_unchanged(self) -> None:
        assert _etag(FakeProperties(etag="0x8DC1")) == "0x8DC1"

    def test_missing_etag_is_none(self) -> None:
        assert _etag(FakeProperties(etag=None)) is None

    def test_attribute_absent_entirely_is_none(self) -> None:
        assert _etag(object()) is None


class TestLocalSource:
    def test_uris_are_relative_to_the_root(self, tmp_path: Path) -> None:
        (tmp_path / "policies").mkdir()
        (tmp_path / "policies" / "refunds.md").write_text("content", encoding="utf-8")

        [item] = LocalSource(tmp_path).list_items()

        # Relative, so moving the directory does not re-index everything as new documents.
        assert item.uri == "policies/refunds.md"
        assert item.key == str(tmp_path.resolve() / "policies" / "refunds.md")

    def test_a_file_root_uses_its_name(self, tmp_path: Path) -> None:
        path = tmp_path / "doc.md"
        path.write_text("content", encoding="utf-8")

        assert [item.uri for item in LocalSource(path).list_items()] == ["doc.md"]

    def test_label_is_the_resolved_root(self, tmp_path: Path) -> None:
        assert LocalSource(tmp_path).label == str(tmp_path.resolve())

    def test_missing_root_is_reported_as_a_config_error(self, tmp_path: Path) -> None:
        source = LocalSource(tmp_path / "nope")

        with pytest.raises(SourceConfigError, match="does not exist"):
            source.list_items()

    def test_version_changes_when_the_file_changes(self, tmp_path: Path) -> None:
        path = tmp_path / "doc.md"
        path.write_text("one", encoding="utf-8")
        before = LocalSource._version(path)

        path.write_text("a much longer body", encoding="utf-8")

        # mtime_ns:size — the incremental sync skips a document whose version is unchanged.
        assert LocalSource._version(path) != before


class TestAzureBlobSourceLabel:
    def test_label_includes_the_prefix(self) -> None:
        assert AzureBlobSource("contracts", "policies").label == "azure://contracts/policies"

    def test_label_without_a_prefix_is_the_container(self) -> None:
        assert AzureBlobSource("contracts").label == "azure://contracts"


class TestSourceFor:
    def test_directory_connection_is_a_local_source(self, tmp_path: Path) -> None:
        connection = SourceConnection(kind=SourceKind.DIRECTORY, config={"path": str(tmp_path)})

        source = source_for(connection)

        assert isinstance(source, LocalSource)
        assert source.root == tmp_path.resolve()

    def test_blob_connection_carries_container_and_prefix(self) -> None:
        connection = SourceConnection(
            kind=SourceKind.AZURE_BLOB, config={"container": "contracts", "prefix": "policies"}
        )

        source = source_for(connection)

        assert isinstance(source, AzureBlobSource)
        assert (source.container, source.prefix) == ("contracts", "policies")

    def test_blob_prefix_is_optional(self) -> None:
        connection = SourceConnection(kind=SourceKind.AZURE_BLOB, config={"container": "c"})

        source = source_for(connection)

        assert isinstance(source, AzureBlobSource)
        assert source.prefix == ""
