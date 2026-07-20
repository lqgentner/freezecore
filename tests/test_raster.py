"""Tests for freezecore.raster."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from freezecore.raster import COG_PROFILE, rewrite_tiff, write_cog

WIDTH, HEIGHT = 8, 6


def assert_is_cog(path: Path) -> None:
    """Lightweight COG check via plain rasterio (no rio_cogeo dependency)."""
    with rasterio.open(path) as ds:
        assert ds.driver == "GTiff"
        assert ds.profile["tiled"] is True
        assert ds.tags(ns="IMAGE_STRUCTURE").get("LAYOUT") == "COG"


def make_tiff(path: Path, *, fill: float = 1.0) -> None:
    data = np.full((HEIGHT, WIDTH), fill, dtype=np.float32)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=WIDTH,
        height=HEIGHT,
        count=1,
        dtype="float32",
        crs="EPSG:32632",
        transform=from_origin(500000, 5200000, 10, 10),
        nodata=np.nan,
    ) as dst:
        dst.write(data, 1)
        dst.set_band_description(1, "VV")


class TestRewriteTiffLocal:
    def test_moves_between_paths(self, tmp_path: Path) -> None:
        src = tmp_path / "src.tif"
        dst = tmp_path / "dst.tif"
        make_tiff(src)

        rewrite_tiff(src, dst, profile=COG_PROFILE)

        assert not src.exists()
        assert_is_cog(dst)
        with rasterio.open(dst) as ds:
            assert ds.descriptions == ("VV",)
            assert (ds.read(1) == 1.0).all()

    def test_rewrites_in_place_to_cog(self, tmp_path: Path) -> None:
        path = tmp_path / "tile.tif"
        make_tiff(path)

        rewrite_tiff(path, path, profile=COG_PROFILE)

        assert path.exists()
        assert not (tmp_path / f".{path.name}.tmp").exists()
        assert_is_cog(path)
        with rasterio.open(path) as ds:
            assert ds.descriptions == ("VV",)
            assert (ds.read(1) == 1.0).all()

    def test_in_place_preserves_band_names_override(self, tmp_path: Path) -> None:
        path = tmp_path / "tile.tif"
        make_tiff(path)

        rewrite_tiff(path, path, profile=COG_PROFILE, band_names=["renamed"])

        with rasterio.open(path) as ds:
            assert ds.descriptions == ("renamed",)

    def test_no_leftover_temp_file_on_failure(self, tmp_path: Path) -> None:
        path = tmp_path / "tile.tif"
        make_tiff(path)

        with pytest.raises(RuntimeError):
            rewrite_tiff(path, path, profile={"driver": "NotARealDriver"})

        assert not (tmp_path / f".{path.name}.tmp").exists()
        # original file must still be intact -- the failed write never
        # touched it, since it happens on a separate temp file locally.
        with rasterio.open(path) as ds:
            assert (ds.read(1) == 1.0).all()


class TestWriteCog:
    def test_writes_valid_cog(self, tmp_path: Path) -> None:
        dst = tmp_path / "out.tif"
        data = np.full((HEIGHT, WIDTH), 3.0, dtype=np.float32)
        profile = {
            "dtype": "float32",
            "count": 1,
            "width": WIDTH,
            "height": HEIGHT,
            "crs": "EPSG:32632",
            "transform": from_origin(500000, 5200000, 10, 10),
            "nodata": np.nan,
        }

        write_cog(data, dst, profile, band_names=["VH"])

        assert_is_cog(dst)
        assert not (tmp_path / f".{dst.name}.tmp").exists()
        with rasterio.open(dst) as ds:
            assert ds.descriptions == ("VH",)
            assert (ds.read(1) == 3.0).all()

    def test_no_leftover_temp_file_or_dst_on_failure(self, tmp_path: Path) -> None:
        dst = tmp_path / "out.tif"
        data = np.full((HEIGHT, WIDTH), 3.0, dtype=np.float32)
        profile = {
            "dtype": "float32",
            "count": 1,
            "width": WIDTH,
            "height": HEIGHT,
            "crs": "EPSG:32632",
            "transform": from_origin(500000, 5200000, 10, 10),
            "nodata": np.nan,
        }

        with pytest.raises(RuntimeError):
            write_cog(data, dst, {**profile, "dtype": "not-a-real-dtype"})

        assert not dst.exists()
        assert not (tmp_path / f".{dst.name}.tmp").exists()
