"""Tests for freezecore.s3 transient-error classification."""

from __future__ import annotations

import pytest

pytest.importorskip("s3fs")
pytest.importorskip("botocore")

from botocore.exceptions import ClientError

from freezecore.s3 import TRANSIENT_S3_ERROR_CODES, _retry_transient_s3_errors


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "x"}}, "HeadObject")


class TestTransientS3Errors:
    @pytest.mark.parametrize("code", sorted(TRANSIENT_S3_ERROR_CODES))
    def test_transient_codes_retry(self, code: str) -> None:
        assert _retry_transient_s3_errors(_client_error(code)) is True

    @pytest.mark.parametrize("code", ["AccessDenied", "403", "NoSuchKey", "InvalidAccessKeyId"])
    def test_permanent_codes_not_retried(self, code: str) -> None:
        # A permanent authorization failure must not be retried (previously a
        # bare "403" was treated as transient and retried up to ten times).
        assert _retry_transient_s3_errors(_client_error(code)) is False

    def test_non_client_error_not_retried(self) -> None:
        assert _retry_transient_s3_errors(ValueError("nope")) is False
