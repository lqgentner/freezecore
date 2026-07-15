"""Shared S3 UPath construction and retry configuration.

Single source of truth for which S3/botocore errors are transient and how many
times to retry them. Build every S3 bucket via :func:`make_s3_upath` rather than
constructing a bare `UPath` directly.

Importing this module registers a `s3fs.core.set_custom_error_handler` callback,
which is what gates `ClientError` retries inside s3fs's own retry loop -- separate
from (and consulted after) botocore's `retries.max_attempts` config.
"""

from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError
from s3fs.core import set_custom_error_handler
from upath import UPath

# Observed as transient on both the CDSE eodata gateway and Ceph-based S3
# gateways: 403/SignatureDoesNotMatch under clock-skew or auth-refresh races,
# 408/RequestTimeout under load.
TRANSIENT_S3_ERROR_CODES = frozenset({"403", "SignatureDoesNotMatch", "408", "RequestTimeout"})

# botocore retry budget for a single S3 API call (e.g. one HeadObject). "adaptive"
# mode adds client-side rate limiting on top of exponential backoff, which helps
# when a gateway is transiently overloaded rather than fully down.
S3_MAX_ATTEMPTS = 10
S3_RETRY_MODE = "adaptive"


def _retry_transient_s3_errors(exc: Exception) -> bool:
    """s3fs custom error handler that retries transient `ClientError` responses.

    See the module docstring for why this -- not `retries.max_attempts` -- is the
    layer that actually gates whether s3fs retries a `ClientError` at all.
    """
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        return code in TRANSIENT_S3_ERROR_CODES
    return False


set_custom_error_handler(_retry_transient_s3_errors)


def make_s3_upath(
    root: str,
    *,
    key: str,
    secret: str,
    endpoint_url: str,
    request_checksum_calculation: str = "when_required",
    response_checksum_validation: str = "when_required",
    client_kwargs: dict[str, Any] | None = None,
) -> UPath:
    """Build an S3 `UPath` with the shared retry policy.

    Parameters
    ----------
    root : str
        S3 URI to root the path at, e.g. ``"s3://my-bucket"``.
    key, secret : str
        S3 access key ID and secret access key.
    endpoint_url : str
        S3-compatible endpoint URL.
    request_checksum_calculation, response_checksum_validation : str, default "when_required"
        boto3 >=1.36 checksum behavior. ``"when_required"`` avoids the
        ``x-amz-checksum-*`` trailers that some S3-compatible gateways (e.g.
        Ceph) reject; it's a safe default even for gateways not known to need it.
    client_kwargs : dict, optional
        Extra kwargs forwarded to the underlying botocore client (e.g. a second,
        explicit ``endpoint_url`` some callers pass for clarity). Defaults to
        ``{"endpoint_url": endpoint_url}``.

    Returns
    -------
    UPath
        An S3 `UPath` configured with :data:`S3_MAX_ATTEMPTS` botocore retries in
        :data:`S3_RETRY_MODE` mode, on top of the s3fs-level retry handler
        registered by this module.
    """
    return UPath(
        root,
        key=key,
        secret=secret,
        endpoint_url=endpoint_url,
        client_kwargs=client_kwargs or {"endpoint_url": endpoint_url},
        config_kwargs={
            "request_checksum_calculation": request_checksum_calculation,
            "response_checksum_validation": response_checksum_validation,
            "retries": {"max_attempts": S3_MAX_ATTEMPTS, "mode": S3_RETRY_MODE},
        },
    )
