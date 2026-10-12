"""Request-id handling and log-line hygiene."""

from __future__ import annotations

from ai_employee.observability import (
    clean_request_id,
    current_request_id,
    request_context,
    truncate,
)


class TestCleanRequestId:
    def test_a_usable_id_passes_through(self) -> None:
        assert clean_request_id("abc-123_x.y") == "abc-123_x.y"

    def test_newlines_are_stripped(self) -> None:
        # An id arrives from a caller's header and lands in a log line; a newline through it
        # would forge a second record.
        assert clean_request_id("abc\nFAKE LOG LINE") == "abcFAKELOGLINE"

    def test_id_is_capped_at_64_characters(self) -> None:
        assert clean_request_id("a" * 200) == "a" * 64

    def test_empty_input_is_none(self) -> None:
        assert clean_request_id("") is None

    def test_none_input_is_none(self) -> None:
        assert clean_request_id(None) is None

    def test_id_with_nothing_usable_left_is_none(self) -> None:
        assert clean_request_id("!!!@@@") is None


class TestRequestContext:
    def test_no_id_is_bound_outside_a_context(self) -> None:
        assert current_request_id() is None

    def test_supplied_id_is_bound(self) -> None:
        with request_context("caller-id") as request_id:
            assert request_id == "caller-id"
            assert current_request_id() == "caller-id"

    def test_an_id_is_generated_when_the_caller_supplies_none(self) -> None:
        with request_context(None) as request_id:
            assert request_id
            assert current_request_id() == request_id

    def test_a_nested_context_inherits_the_outer_id(self) -> None:
        # A CLI turn generates an id; the same turn under the API keeps the HTTP one.
        with request_context("outer"), request_context(None) as inner:
            assert inner == "outer"

    def test_the_binding_is_released_on_exit(self) -> None:
        with request_context("temporary"):
            pass

        assert current_request_id() is None

    def test_the_binding_is_released_when_the_body_raises(self) -> None:
        try:
            with request_context("temporary"):
                raise RuntimeError("boom")
        except RuntimeError:
            pass

        assert current_request_id() is None

    def test_an_unusable_supplied_id_is_replaced_rather_than_rejected(self) -> None:
        with request_context("!!!") as request_id:
            assert request_id
            assert "!" not in request_id


class TestTruncate:
    def test_short_text_is_unchanged(self) -> None:
        assert truncate("a short line") == "a short line"

    def test_whitespace_is_collapsed(self) -> None:
        assert truncate("two   lines\nhere") == "two lines here"

    def test_long_text_is_cut_and_marked(self) -> None:
        result = truncate("a" * 300)

        assert result == "a" * 200 + "…"

    def test_the_limit_is_configurable(self) -> None:
        assert truncate("abcdef", limit=3) == "abc…"

    def test_text_exactly_at_the_limit_is_not_marked(self) -> None:
        assert truncate("abc", limit=3) == "abc"
