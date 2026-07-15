"""Tests for shared helpers in freezecore.utils and freezecore.download."""

from __future__ import annotations

import pytest
import requests

from freezecore.download import _is_transient_request_error
from freezecore.utils import format_valid_options, shorten_string


class TestTransientRequestError:
    def _http_error(self, status_code: int) -> requests.exceptions.HTTPError:
        response = requests.Response()
        response.status_code = status_code
        return requests.exceptions.HTTPError(response=response)

    @pytest.mark.parametrize("status_code", [408, 429, 502, 503, 504])
    def test_transient_status_codes(self, status_code: int) -> None:
        assert _is_transient_request_error(self._http_error(status_code))

    @pytest.mark.parametrize("status_code", [400, 401, 404, 500])
    def test_non_transient_status_codes(self, status_code: int) -> None:
        assert not _is_transient_request_error(self._http_error(status_code))

    def test_extra_status_codes(self) -> None:
        assert _is_transient_request_error(
            self._http_error(500),
            extra_status_codes=frozenset({500}),
        )

    def test_connection_and_timeout_errors(self) -> None:
        assert _is_transient_request_error(requests.exceptions.ConnectionError())
        assert _is_transient_request_error(requests.exceptions.Timeout())

    def test_unrelated_exception(self) -> None:
        assert not _is_transient_request_error(ValueError("nope"))


class TestShortenString:
    def test_short_string_unchanged(self) -> None:
        assert shorten_string("short.zip", 30) == "short.zip"

    def test_long_string_shortened_with_ellipsis(self) -> None:
        result = shorten_string("a" * 20 + "b" * 20, 21)

        assert len(result) == 21
        assert "..." in result


def test_format_valid_options() -> None:
    formatted = format_valid_options({"IW": "Interferometric Wide", "EW": "Extra Wide"})

    assert formatted == "- 'IW': Interferometric Wide\n- 'EW': Extra Wide"
