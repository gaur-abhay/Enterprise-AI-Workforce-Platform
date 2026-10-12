"""Chunking. Pure text in, chunks out — no loader, no database, no embedding call."""

from __future__ import annotations

from pathlib import Path

from ai_employee.knowledge.chunking import CHUNK_SIZE, MIN_CHUNK_CHARS, _merge_undersized, chunk
from ai_employee.knowledge.loaders import LoadedDocument, Page


def document(*pages: Page) -> LoadedDocument:
    """A LoadedDocument built in memory; `path` is never read by the chunker."""
    return LoadedDocument(
        path=Path("doc.md"),
        uri="doc.md",
        title="doc.md",
        mime_type="text/markdown",
        content_hash="0" * 64,
        pages=list(pages),
    )


class TestMergeUndersized:
    def test_fragment_is_folded_into_the_passage_that_follows(self) -> None:
        heading = "# Refund policy"
        body = "b" * MIN_CHUNK_CHARS

        assert _merge_undersized([heading, body]) == [f"{heading}\n\n{body}"]

    def test_trailing_fragment_is_folded_backwards(self) -> None:
        body = "b" * MIN_CHUNK_CHARS
        tail = "see appendix"

        assert _merge_undersized([body, tail]) == [f"{body}\n\n{tail}"]

    def test_input_that_is_entirely_undersized_survives_as_one_passage(self) -> None:
        assert _merge_undersized(["a", "b"]) == ["a\n\nb"]

    def test_passages_above_the_minimum_are_left_alone(self) -> None:
        first = "a" * MIN_CHUNK_CHARS
        second = "b" * MIN_CHUNK_CHARS

        assert _merge_undersized([first, second]) == [first, second]

    def test_empty_input_produces_nothing(self) -> None:
        assert _merge_undersized([]) == []


class TestChunk:
    def test_indices_are_sequential_across_pages(self) -> None:
        doc = document(Page(text="alpha " * 400, number=1), Page(text="beta " * 400, number=2))

        chunks = chunk(doc)

        assert [c.index for c in chunks] == list(range(len(chunks)))

    def test_chunks_carry_their_page_number(self) -> None:
        doc = document(Page(text="alpha " * 400, number=1), Page(text="beta " * 400, number=2))

        chunks = chunk(doc)

        # The reason for splitting page by page: a citation can name a page.
        assert {c.page_number for c in chunks} == {1, 2}

    def test_no_chunk_straddles_a_page_boundary(self) -> None:
        doc = document(Page(text="alpha", number=1), Page(text="beta", number=2))

        chunks = chunk(doc)

        for c in chunks:
            assert not ("alpha" in c.content and "beta" in c.content)

    def test_short_page_still_produces_a_chunk(self) -> None:
        doc = document(Page(text="Too short to stand alone.", number=1))

        chunks = chunk(doc)

        assert [c.content for c in chunks] == ["Too short to stand alone."]

    def test_blank_pages_are_dropped(self) -> None:
        doc = document(Page(text="   \n\n  ", number=1), Page(text="real content here", number=2))

        chunks = chunk(doc)

        assert len(chunks) == 1
        assert chunks[0].page_number == 2

    def test_unpaginated_document_keeps_a_null_page_number(self) -> None:
        doc = document(Page(text="plain text file, no pages", number=None))

        assert chunk(doc)[0].page_number is None

    def test_long_page_splits_into_bounded_chunks(self) -> None:
        doc = document(Page(text="word " * 2000, number=1))

        chunks = chunk(doc)

        assert len(chunks) > 1
        # The splitter targets CHUNK_SIZE but may overshoot on an unbreakable run; the
        # assertion that matters is that no chunk grows without bound.
        assert all(c.char_count <= CHUNK_SIZE * 1.2 for c in chunks)

    def test_document_with_no_pages_produces_no_chunks(self) -> None:
        assert chunk(document()) == []

    def test_char_count_matches_the_content(self) -> None:
        doc = document(Page(text="word " * 500, number=1))

        assert all(c.char_count == len(c.content) for c in chunk(doc))
