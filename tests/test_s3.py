"""Tests for freezecore.s3 UPath construction, env injection, and retries."""

from __future__ import annotations

import pytest

pytest.importorskip("s3fs")
pytest.importorskip("botocore")
pytest.importorskip("boto3")

from botocore.exceptions import ClientError
from rasterio.env import getenv

from freezecore.s3 import (
    TRANSIENT_S3_ERROR_CODES,
    _retry_transient_s3_errors,
    make_s3_upath,
    s3_env,
)


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


class TestMakeS3Upath:
    def test_region_goes_into_client_kwargs_not_top_level(self) -> None:
        # Regression: a top-level ``region`` kwarg reaches aiobotocore's session
        # and raises; it must live in client_kwargs as ``region_name``.
        so = make_s3_upath("s3://b/k", key="a", secret="b", region="eu-central-1").storage_options
        assert so["client_kwargs"]["region_name"] == "eu-central-1"
        assert "region" not in so

    def test_endpoint_url_forwarded(self) -> None:
        so = make_s3_upath(
            "s3://b/k",
            key="a",
            secret="b",
            endpoint_url="https://ceph.example.org",
        ).storage_options
        assert so["endpoint_url"] == "https://ceph.example.org"
        assert so["client_kwargs"]["endpoint_url"] == "https://ceph.example.org"

    def test_token_forwarded(self) -> None:
        so = make_s3_upath("s3://b/k", key="a", secret="b", token="TK").storage_options
        assert so["token"] == "TK"

    def test_anonymous_when_no_credentials(self) -> None:
        so = make_s3_upath("s3://public/k").storage_options
        assert so["key"] is None
        assert so["secret"] is None

    def test_protocol_forced_for_bare_string(self) -> None:
        assert make_s3_upath("bucket/key.tif", key="a", secret="b").protocol == "s3"

    def test_caller_region_name_takes_precedence(self) -> None:
        so = make_s3_upath(
            "s3://b/k",
            key="a",
            secret="b",
            region="us-east-1",
            client_kwargs={"region_name": "eu-west-1"},
        ).storage_options
        assert so["client_kwargs"]["region_name"] == "eu-west-1"


@pytest.fixture
def captured_session(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Patch ``AWSSession`` in :mod:`freezecore.s3` to record its kwargs."""
    from rasterio.session import AWSSession  # noqa: PLC0415

    captured: dict[str, object] = {}

    def spy(**kwargs: object) -> AWSSession:
        captured.update(kwargs)
        return AWSSession(**kwargs)

    monkeypatch.setattr("freezecore.s3.AWSSession", spy)
    return captured


class TestS3Env:
    def test_https_endpoint_options(self) -> None:
        p = make_s3_upath("s3://b/k", key="a", secret="b", endpoint_url="https://ceph.example.org")
        with s3_env(p):
            env = getenv()
        assert env["AWS_S3_ENDPOINT"] == "ceph.example.org"  # scheme stripped
        assert env["AWS_VIRTUAL_HOSTING"] == "FALSE"
        assert env.get("AWS_HTTPS") != "NO"
        assert env["GDAL_DISABLE_READDIR_ON_OPEN"] == "EMPTY_DIR"
        assert "403" in env["GDAL_HTTP_RETRY_CODES"]

    def test_http_endpoint_flags_plaintext(self) -> None:
        p = make_s3_upath("s3://b/k", key="a", secret="b", endpoint_url="http://minio:9000")
        with s3_env(p):
            env = getenv()
        assert env["AWS_S3_ENDPOINT"] == "minio:9000"
        assert env["AWS_HTTPS"] == "NO"

    def test_no_endpoint_omits_endpoint_options(self) -> None:
        p = make_s3_upath("s3://b/k", key="a", secret="b")
        with s3_env(p):
            env = getenv()
        assert "AWS_S3_ENDPOINT" not in env
        assert "AWS_VIRTUAL_HOSTING" not in env

    def test_session_receives_region_and_credentials(
        self,
        captured_session: dict[str, object],
    ) -> None:
        p = make_s3_upath("s3://b/k", key="AK", secret="SK", token="TK", region="eu-central-1")
        with s3_env(p):
            pass
        assert captured_session["aws_access_key_id"] == "AK"
        assert captured_session["aws_secret_access_key"] == "SK"
        assert captured_session["aws_session_token"] == "TK"
        assert captured_session["region_name"] == "eu-central-1"
        assert captured_session["aws_unsigned"] is False

    def test_session_unsigned_without_credentials(
        self,
        captured_session: dict[str, object],
    ) -> None:
        p = make_s3_upath("s3://public/k", region="eu-central-1")
        with s3_env(p):
            pass
        assert captured_session["aws_unsigned"] is True
        # Region still applies for public, region-scoped buckets.
        assert captured_session["region_name"] == "eu-central-1"
