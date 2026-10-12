"""Source selection and URI shaping. Nothing here contacts Azure or reads a document."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from ai_employee.ingestion.sources import (
    AzureBlobSource,
    LocalSource,
    SourceConfigError,
    _etag,
    from_spec,
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
    def test_directory_prefix_ends_with_a_separator(self, tmp_path: Path) -> None:
        source = LocalSource(tmp_path)

        # Without the trailing separator, /data/doc would also cover /data/documents/.
        assert source.uri_prefix == f"{tmp_path.resolve()}/"

    def test_file_prefix_is_the_path_itself(self, tmp_path: Path) -> None:
        path = tmp_path / "doc.md"
        path.write_text("content", encoding="utf-8")

        assert LocalSource(path).uri_prefix == str(path.resolve())

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


class TestFromSpec:
    def test_bare_path_is_a_local_source(self, tmp_path: Path) -> None:
        source = from_spec(str(tmp_path))

        assert isinstance(source, LocalSource)
        assert source.root == tmp_path.resolve()

    def test_azure_spec_splits_container_and_prefix(self) -> None:
        source = from_spec("azure://contracts/policies/2024")

        assert isinstance(source, AzureBlobSource)
        assert source.container == "contracts"
        assert source.prefix == "policies/2024"

    def test_azure_spec_without_a_prefix(self) -> None:
        source = from_spec("azure://contracts")

        assert isinstance(source, AzureBlobSource)
        assert source.container == "contracts"
        assert source.prefix == ""

    def test_bare_azure_spec_falls_back_to_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AZURE_STORAGE_CONTAINER", "default-container")
        monkeypatch.setenv("AZURE_STORAGE_PREFIX", "default-prefix")

        source = from_spec("azure://")

        assert isinstance(source, AzureBlobSource)
        assert source.container == "default-container"
        assert source.prefix == "default-prefix"

    def test_spec_container_wins_over_the_configured_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AZURE_STORAGE_CONTAINER", "default-container")

        source = from_spec("azure://explicit")

        assert isinstance(source, AzureBlobSource)
        assert source.container == "explicit"

    def test_bare_azure_spec_without_a_configured_container_is_an_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AZURE_STORAGE_CONTAINER", "")

        with pytest.raises(SourceConfigError, match="AZURE_STORAGE_CONTAINER is unset"):
            from_spec("azure://")
