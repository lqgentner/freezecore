"""S3 integration tests against a live S3-compatible service (e.g. MinIO).

These exercise the credentialed ``_s3_env`` read/write paths in
``freezecore.raster`` that unit tests can't reach. They are skipped unless the
``FREEZECORE_TEST_S3_*`` environment variables point at a reachable endpoint;
CI provides them via a MinIO service container.

Configure with:

- ``FREEZECORE_TEST_S3_ENDPOINT``  (e.g. ``http://localhost:9000``)
- ``FREEZECORE_TEST_S3_KEY``
- ``FREEZECORE_TEST_S3_SECRET``
- ``FREEZECORE_TEST_S3_BUCKET``    (optional, default ``freezecore-test``)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING
import uuid

import numpy as np
import pytest
from rasterio.transform import from_origin

pytest.importorskip("s3fs")

if TYPE_CHECKING:
    from collections.abc import Iterator

    from upath import UPath

from freezecore.raster import (
    COG_PROFILE,
    rasterio_open,
    rewrite_tiff,
    write_cog,
)
from freezecore.s3 import make_s3_upath

_ENDPOINT = os.getenv("FREEZECORE_TEST_S3_ENDPOINT")
_KEY = os.getenv("FREEZECORE_TEST_S3_KEY")
_SECRET = os.getenv("FREEZECORE_TEST_S3_SECRET")
_BUCKET = os.getenv("FREEZECORE_TEST_S3_BUCKET", "freezecore-test")

_skip_reason = "FREEZECORE_TEST_S3_ENDPOINT/KEY/SECRET not set"
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not (_ENDPOINT and _KEY and _SECRET), reason=_skip_reason),
]

WIDTH, HEIGHT = 8, 6
_PROFILE = {
    "dtype": "float32",
    "count": 1,
    "width": WIDTH,
    "height": HEIGHT,
    "crs": "EPSG:32632",
    "transform": from_origin(500000, 5200000, 10, 10),
    "nodata": np.nan,
}


@pytest.fixture(scope="module")
def bucket_root() -> UPath:
    """Return a UPath rooted at the test bucket, creating it if needed."""
    root = make_s3_upath(
        f"s3://{_BUCKET}",
        key=_KEY,  # type: ignore[arg-type]
        secret=_SECRET,  # type: ignore[arg-type]
        endpoint_url=_ENDPOINT,  # type: ignore[arg-type]
    )
    if not root.exists():
        root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def s3_key(bucket_root: UPath) -> Iterator[UPath]:
    """Yield a unique object path inside the bucket, cleaned up afterwards."""
    path = bucket_root / f"{uuid.uuid4().hex}.tif"
    yield path
    path.unlink(missing_ok=True)


class TestWriteCogS3:
    def test_round_trip(self, s3_key: UPath) -> None:
        data = np.full((HEIGHT, WIDTH), 3.0, dtype=np.float32)

        write_cog(data, s3_key, _PROFILE, band_names=["VH"])

        assert s3_key.exists()
        with rasterio_open(s3_key) as ds:
            assert ds.descriptions == ("VH",)
            assert np.array_equal(ds.read(1), data)


class TestRewriteTiffS3:
    def test_local_to_s3_copy(self, tmp_path: Path, s3_key: UPath) -> None:
        src = tmp_path / "src.tif"
        data = np.full((HEIGHT, WIDTH), 1.0, dtype=np.float32)
        write_cog(data, src, _PROFILE, band_names=["VV"])

        rewrite_tiff(src, s3_key, profile=COG_PROFILE)

        assert src.exists()  # copy by default -- source preserved
        assert s3_key.exists()
        with rasterio_open(s3_key) as ds:
            assert ds.descriptions == ("VV",)
            assert np.array_equal(ds.read(1), data)

    def test_local_to_s3_move_deletes_source(self, tmp_path: Path, s3_key: UPath) -> None:
        src = tmp_path / "src.tif"
        data = np.full((HEIGHT, WIDTH), 2.0, dtype=np.float32)
        write_cog(data, src, _PROFILE)

        rewrite_tiff(src, s3_key, profile=COG_PROFILE, move=True)

        assert not src.exists()
        assert s3_key.exists()
