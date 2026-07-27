"""Shared S3 UPath construction, retry configuration, and rasterio env.

Single source of truth for building S3-backed `UPath` instances, for which
S3/botocore errors are transient and how many times to retry them, and for the
GDAL/rasterio environment used to read and write rasters on S3-compatible
object storage. Build every S3 path via :func:`make_s3_upath` rather than
constructing a bare `UPath` directly, and wrap raster I/O in :func:`s3_env`.

Importing this module registers a `s3fs.core.set_custom_error_handler` callback,
which is what gates `ClientError` retries inside s3fs's own retry loop -- separate
from (and consulted after) botocore's `retries.max_attempts` config.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from botocore.exceptions import ClientError
import rasterio
from rasterio.session import AWSSession
from s3fs.core import set_custom_error_handler
from upath import UPath

from freezecore.download import TRANSIENT_HTTP_STATUS_CODES

if TYPE_CHECKING:
    from collections.abc import Generator

# Observed as transient on both the CDSE eodata gateway and Ceph-based S3
# gateways under clock-skew, auth-refresh races, or load.
TRANSIENT_S3_ERROR_CODES = frozenset(
    {"SignatureDoesNotMatch", "RequestTimeTooSkewed", "RequestTimeout"},
)

# botocore retry budget for a single S3 API call (e.g. one HeadObject). "adaptive"
# mode adds client-side rate limiting on top of exponential backoff, which helps
# when a gateway is transiently overloaded rather than fully down.
S3_MAX_ATTEMPTS = 10
S3_RETRY_MODE = "adaptive"

# GDAL's own /vsis3 read/write path has a retry budget separate from botocore's
# (which only covers s3fs metadata calls). Shared transient codes, plus 403
# (S3 can return this transiently under auth-refresh races).
GDAL_HTTP_RETRY_CODES = ",".join(str(code) for code in sorted({403, *TRANSIENT_HTTP_STATUS_CODES}))
GDAL_HTTP_MAX_RETRY = 5
GDAL_HTTP_RETRY_DELAY_S = 1


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
    path: str,
    *,
    key: str | None = None,
    secret: str | None = None,
    token: str | None = None,
    region: str | None = None,
    endpoint_url: str | None = None,
    request_checksum_calculation: str = "when_required",
    response_checksum_validation: str = "when_required",
    client_kwargs: dict[str, Any] | None = None,
) -> UPath:
    """Build an S3 `UPath` with the shared retry policy.

    Parameters
    ----------
    path : str
        S3 URI or prefix, e.g. ``"s3://my-bucket/some/key.tif"``. The ``s3``
        protocol is forced, so a bare ``"my-bucket/key"`` also works.
    key, secret : str, optional
        S3 access key ID and secret access key. Omit both for anonymous
        (unsigned) access to a public bucket.
    token : str, optional
        S3 session token, for temporary/STS credentials.
    region : str, optional
        AWS region name. Relevant for region-scoped AWS-native buckets.
    endpoint_url : str, optional
        S3-compatible endpoint URL. Omit for AWS-native S3.
    request_checksum_calculation, response_checksum_validation : str, default "when_required"
        boto3 >=1.36 checksum behavior. ``"when_required"`` avoids the
        ``x-amz-checksum-*`` trailers that some S3-compatible gateways (e.g.
        Ceph) reject; it's a safe default even for gateways not known to need it.
    client_kwargs : dict, optional
        Extra kwargs forwarded to the underlying botocore client. Defaults to
        ``{"endpoint_url": endpoint_url}``. ``region`` is injected here as
        ``region_name``.

    Returns
    -------
    UPath
        An S3 `UPath` configured with :data:`S3_MAX_ATTEMPTS` botocore retries in
        :data:`S3_RETRY_MODE` mode, on top of the s3fs-level retry handler
        registered by this module. Pair it with :func:`s3_env` for raster I/O.
    """
    # `region` is not an s3fs constructor argument; s3fs would forward it to
    # botocore's session and raise. The region belongs in the botocore client
    # config as `region_name`, which is what `client_kwargs` feeds.
    resolved_client_kwargs = (
        client_kwargs if client_kwargs is not None else {"endpoint_url": endpoint_url}
    )
    if region is not None and "region_name" not in resolved_client_kwargs:
        resolved_client_kwargs = {**resolved_client_kwargs, "region_name": region}
    return UPath(
        path,
        protocol="s3",
        key=key,
        secret=secret,
        token=token,
        endpoint_url=endpoint_url,
        client_kwargs=resolved_client_kwargs,
        config_kwargs={
            "request_checksum_calculation": request_checksum_calculation,
            "response_checksum_validation": response_checksum_validation,
            "retries": {"max_attempts": S3_MAX_ATTEMPTS, "mode": S3_RETRY_MODE},
        },
    )


@contextmanager
def s3_env(path: UPath) -> Generator[None]:
    """Enter a rasterio (bundled GDAL) environment for S3-compatible storage.

    Extracts credentials and endpoint configuration from the fsspec storage
    options attached to ``path`` and applies them to rasterio for the duration
    of the ``with`` block. When ``key`` and ``secret`` are both absent, requests
    are sent unsigned, allowing anonymous reads of public buckets.

    Parameters
    ----------
    path : UPath
        A UPath with ``protocol="s3"`` whose ``storage_options`` carry
        fsspec/s3fs credentials (``key``, ``secret``, ``token``), an optional
        ``client_kwargs["region_name"]``, and an optional custom
        ``endpoint_url`` (as produced by :func:`make_s3_upath`).
    """
    so = path.storage_options
    key = so.get("key")
    secret = so.get("secret")
    unsigned = key is None and secret is None
    session = AWSSession(
        aws_unsigned=unsigned,
        aws_access_key_id=key,
        aws_secret_access_key=secret,
        aws_session_token=so.get("token"),
        region_name=(so.get("client_kwargs") or {}).get("region_name"),
    )

    options: dict[str, str] = {
        # Don't probe for sidecar files on open.
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        # /vsis3/ has no native random-write support; needed for writes.
        "CPL_VSIL_USE_TEMP_FILE_FOR_RANDOM_WRITE": "YES",
        # Retry transient HTTP failures on the /vsis3 read/write path.
        "GDAL_HTTP_MAX_RETRY": str(GDAL_HTTP_MAX_RETRY),
        "GDAL_HTTP_RETRY_DELAY": str(GDAL_HTTP_RETRY_DELAY_S),
        "GDAL_HTTP_RETRY_CODES": GDAL_HTTP_RETRY_CODES,
    }
    if endpoint_url := so.get("endpoint_url"):
        # Pass the host without scheme so this works on GDAL < 3.11 too, and
        # flag plain-HTTP endpoints explicitly.
        options["AWS_S3_ENDPOINT"] = endpoint_url.removeprefix("https://").removeprefix("http://")
        options["AWS_VIRTUAL_HOSTING"] = "FALSE"
        if endpoint_url.startswith("http://"):
            options["AWS_HTTPS"] = "NO"

    with rasterio.Env(session=session, **options):
        yield
