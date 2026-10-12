"""Document sources. A source lists items and materialises each one as a local file.

The loaders and the chunker only ever see a readable path, so adding a source is a matter
of implementing list_items/open rather than touching the pipeline.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from ai_employee.config import get_settings
from ai_employee.ingestion.loaders import SUPPORTED_SUFFIXES, discover

if TYPE_CHECKING:
    # Imported lazily at runtime inside _client, so a missing SDK fails with a
    # SourceConfigError rather than at import time.
    from azure.storage.blob import ContainerClient

logger = logging.getLogger(__name__)

AZURE_SCHEME = "azure://"


class SourceConfigError(RuntimeError):
    """Raised when a source is selected but cannot be reached with the current settings."""


def _etag(properties: object) -> str | None:
    """ETag off a BlobProperties, normalised. Absent only on a blob being written."""
    etag = getattr(properties, "etag", None)
    return etag.strip('"') if etag else None


@dataclass(frozen=True)
class SourceItem:
    # Stable, globally unique identity. Stored as documents.source_path, so it is also the
    # dedupe key across re-ingestion runs.
    uri: str
    # Provider-native locator: an absolute path locally, a blob name in Azure.
    key: str
    # File name, including the suffix. Drives loader selection and the document title.
    name: str
    # Cheap change token available from the listing alone - an Azure ETag, or mtime:size
    # locally. Lets an unchanged document be skipped without being read.
    version: str | None = None


@dataclass(frozen=True)
class Materialized:
    path: Path
    # The version observed while reading, which is not necessarily the one from the listing:
    # a blob can be rewritten between the two calls.
    version: str | None


class Source(Protocol):
    """A place documents are read from."""

    @property
    def label(self) -> str:
        """Human-readable description of what this source points at."""

    @property
    def uri_prefix(self) -> str:
        """URI prefix covering exactly what list_items() can return. Bounds pruning."""

    def list_items(self) -> list[SourceItem]:
        """Every supported document available from this source."""

    def open(self, item: SourceItem) -> AbstractContextManager[Materialized]:
        """Yield a local readable copy, valid inside the context only."""


class LocalSource:
    """Files on the local filesystem."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    @property
    def label(self) -> str:
        return str(self.root)

    @property
    def uri_prefix(self) -> str:
        # discover() recurses into a directory but returns a file root unchanged, so the
        # trailing separator is what keeps /data/doc.md from covering /data/documents/.
        return str(self.root) if self.root.is_file() else f"{self.root}/"

    @staticmethod
    def _version(path: Path) -> str:
        stat = path.stat()
        return f"{stat.st_mtime_ns}:{stat.st_size}"

    def list_items(self) -> list[SourceItem]:
        if not self.root.exists():
            raise SourceConfigError(f"{self.root} does not exist")
        return [
            SourceItem(uri=str(path), key=str(path), name=path.name, version=self._version(path))
            for path in discover(self.root)
        ]

    @contextmanager
    def open(self, item: SourceItem) -> Iterator[Materialized]:
        # Already local; nothing to materialise.
        path = Path(item.key)
        yield Materialized(path=path, version=self._version(path))


class AzureBlobSource:
    """Blobs in one Azure Blob Storage container, optionally under a prefix."""

    def __init__(self, container: str, prefix: str = "") -> None:
        self.container = container
        self.prefix = prefix

    @property
    def label(self) -> str:
        suffix = f"/{self.prefix}" if self.prefix else ""
        return f"{AZURE_SCHEME}{self.container}{suffix}"

    @cached_property
    def _client(self) -> ContainerClient:
        """ContainerClient built from whichever credential style is configured."""
        try:
            from azure.storage.blob import ContainerClient
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise SourceConfigError("azure-storage-blob is not installed") from exc

        settings = get_settings()
        if settings.azure_storage_connection_string:
            return ContainerClient.from_connection_string(
                settings.azure_storage_connection_string, container_name=self.container
            )

        if not settings.azure_storage_account_url:
            raise SourceConfigError(
                "set AZURE_STORAGE_CONNECTION_STRING, or AZURE_STORAGE_ACCOUNT_URL to "
                "authenticate with Entra ID"
            )

        try:
            from azure.identity import DefaultAzureCredential
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise SourceConfigError("azure-identity is not installed") from exc

        # Resolves a managed identity on Azure, the AZURE_CLIENT_ID/SECRET service principal
        # anywhere else, or the local az login session.
        return ContainerClient(
            account_url=settings.azure_storage_account_url,
            container_name=self.container,
            credential=DefaultAzureCredential(),
        )

    def _uri(self, blob_name: str) -> str:
        # The account is part of the identity: the same container name in two storage
        # accounts holds different documents.
        return f"{AZURE_SCHEME}{self._client.account_name}/{self.container}/{blob_name}"

    @property
    def uri_prefix(self) -> str:
        # Mirrors name_starts_with exactly, so this covers every URI the listing can produce
        # and nothing outside it.
        return self._uri(self.prefix)

    def list_items(self) -> list[SourceItem]:
        client = self._client
        try:
            blobs = list(client.list_blobs(name_starts_with=self.prefix or None))
        except Exception as exc:
            # Wrong container, expired credential, or a data-plane role the identity lacks.
            raise SourceConfigError(f"cannot list {self.label}: {exc}") from exc

        items = []
        for blob in blobs:
            name = blob.name.rsplit("/", 1)[-1]
            # Hierarchical namespaces expose directories as zero-length blobs.
            if not name or Path(name).suffix.lower() not in SUPPORTED_SUFFIXES:
                logger.debug("skipping blob %s", blob.name)
                continue
            items.append(
                SourceItem(
                    uri=self._uri(blob.name),
                    key=blob.name,
                    name=name,
                    version=_etag(blob),
                )
            )
        return sorted(items, key=lambda item: item.key)

    @contextmanager
    def open(self, item: SourceItem) -> Iterator[Materialized]:
        """Download the blob to a temporary file, removed when the context exits."""
        blob = self._client.get_blob_client(item.key)
        with tempfile.TemporaryDirectory(prefix="ai-employee-blob-") as directory:
            # Keep the original file name so the suffix still selects the loader.
            local_path = Path(directory) / item.name
            logger.debug("downloading %s", item.uri)
            downloader = blob.download_blob()
            with local_path.open("wb") as handle:
                downloader.readinto(handle)
            # The ETag of the bytes actually read, not the one from the listing. A blob
            # rewritten between the two would otherwise be stored under a stale token and
            # skipped for good.
            yield Materialized(path=local_path, version=_etag(downloader.properties))


def from_spec(spec: str) -> Source:
    """Build a source from a CLI argument: a filesystem path, or azure://container/prefix.

    With no container in the spec, AZURE_STORAGE_CONTAINER and AZURE_STORAGE_PREFIX are used.
    """
    if not spec.startswith(AZURE_SCHEME):
        return LocalSource(Path(spec))

    settings = get_settings()
    container, _, prefix = spec[len(AZURE_SCHEME) :].partition("/")
    container = container or settings.azure_storage_container
    if not container:
        raise SourceConfigError(f"no container in '{spec}' and AZURE_STORAGE_CONTAINER is unset")
    return AzureBlobSource(container=container, prefix=prefix or settings.azure_storage_prefix)
