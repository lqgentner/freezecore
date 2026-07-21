"""Tests for freezecore.raster."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from freezecore.raster import (
    COG_PROFILE,
    get_epsg_string,
    get_utm_zone_string,
    merge_tiffs,
    rewrite_tiff,
    utm_zone_to_crs,
    write_cog,
)

WIDTH, HEIGHT = 8, 6


def assert_is_cog(path: Path) -> None:
    """Lightweight COG check via plain rasterio (no rio_cogeo dependency)."""
    with rasterio.open(path) as ds:
        assert ds.driver == "GTiff"
        assert ds.profile["tiled"] is True
        assert ds.tags(ns="IMAGE_STRUCTURE").get("LAYOUT") == "COG"


def make_tiff(
    path: Path,
    *,
    fill: float = 1.0,
    origin: tuple[float, float] = (500000, 5200000),
    crs: str = "EPSG:32632",
    description: str | None = "VV",
) -> None:
    data = np.full((HEIGHT, WIDTH), fill, dtype=np.float32)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=WIDTH,
        height=HEIGHT,
        count=1,
        dtype="float32",
        crs=crs,
        transform=from_origin(origin[0], origin[1], 10, 10),
        nodata=np.nan,
    ) as dst:
        dst.write(data, 1)
        if description is not None:
            dst.set_band_description(1, description)


class TestCrsHelpers:
    def test_get_utm_zone_string_valid(self) -> None:
        assert get_utm_zone_string("EPSG:32601") == "01N"
        assert get_utm_zone_string("EPSG:32732") == "32S"

    def test_get_utm_zone_string_invalid_raises_valueerror(self) -> None:
        # Previously raised UnboundLocalError referencing an unassigned `crs`.
        with pytest.raises(ValueError, match="Invalid `projparams`"):
            get_utm_zone_string("not-a-crs")

    def test_get_epsg_string_valid(self) -> None:
        assert get_epsg_string("EPSG:4326") == "EPSG:4326"

    def test_get_epsg_string_invalid_raises_valueerror(self) -> None:
        with pytest.raises(ValueError, match="Invalid `projparams`"):
            get_epsg_string("not-a-crs")

    def test_utm_zone_to_crs_valid(self) -> None:
        assert utm_zone_to_crs("32N").to_epsg() == 32632
        assert utm_zone_to_crs("01S").to_epsg() == 32701

    def test_utm_zone_to_crs_rejects_bad_hemisphere(self) -> None:
        # Previously returned EPSG:32732 for the invalid hemisphere 'X'.
        with pytest.raises(ValueError, match="hemisphere"):
            utm_zone_to_crs("32X")

    def test_utm_zone_to_crs_rejects_bad_zone(self) -> None:
        with pytest.raises(ValueError, match="UTM zone"):
            utm_zone_to_crs("99N")


class TestRewriteTiffLocal:
    def test_copies_between_paths_by_default(self, tmp_path: Path) -> None:
        src = tmp_path / "src.tif"
        dst = tmp_path / "dst.tif"
        make_tiff(src)

        rewrite_tiff(src, dst, profile=COG_PROFILE)

        # Source is preserved by default (move=False).
        assert src.exists()
        assert_is_cog(dst)
        with rasterio.open(dst) as ds:
            assert ds.descriptions == ("VV",)
            assert (ds.read(1) == 1.0).all()

    def test_move_deletes_source(self, tmp_path: Path) -> None:
        src = tmp_path / "src.tif"
        dst = tmp_path / "dst.tif"
        make_tiff(src)

        rewrite_tiff(src, dst, profile=COG_PROFILE, move=True)

        assert not src.exists()
        assert_is_cog(dst)

    def test_preserves_existing_destination_on_failure(self, tmp_path: Path) -> None:
        src = tmp_path / "src.tif"
        dst = tmp_path / "dst.tif"
        make_tiff(src, fill=1.0)
        make_tiff(dst, fill=9.0)

        with pytest.raises(RuntimeError):
            rewrite_tiff(src, dst, profile={"driver": "NotARealDriver"})

        # The pre-existing destination must survive the failed rewrite intact,
        # and the source must not be deleted.
        assert src.exists()
        assert not list(tmp_path.glob(f".{dst.name}.*.tmp"))
        with rasterio.open(dst) as ds:
            assert (ds.read(1) == 9.0).all()

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

        assert not list(tmp_path.glob(f".{path.name}.*.tmp"))
        # original file must still be intact -- the failed write never
        # touched it, since it happens on a separate temp file locally.
        with rasterio.open(path) as ds:
            assert (ds.read(1) == 1.0).all()


class TestMergeTiffs:
    def test_merges_same_crs_tiles(self, tmp_path: Path) -> None:
        a = tmp_path / "a.tif"
        b = tmp_path / "b.tif"
        make_tiff(a, fill=1.0, origin=(500000, 5200000))
        make_tiff(b, fill=2.0, origin=(500000 + WIDTH * 10, 5200000))
        dst = tmp_path / "merged.tif"

        merge_tiffs([a, b], dst)

        with rasterio.open(dst) as ds:
            assert ds.width == WIDTH * 2
            assert ds.descriptions == ("VV",)

    def test_rejects_mismatched_crs(self, tmp_path: Path) -> None:
        a = tmp_path / "a.tif"
        b = tmp_path / "b.tif"
        make_tiff(a, crs="EPSG:32632")
        make_tiff(b, crs="EPSG:32633")
        dst = tmp_path / "merged.tif"

        with pytest.raises(ValueError, match="share a CRS"):
            merge_tiffs([a, b], dst)

    def test_handles_missing_descriptions(self, tmp_path: Path) -> None:
        # A source without band descriptions must not crash metadata injection.
        a = tmp_path / "a.tif"
        make_tiff(a, description=None)
        dst = tmp_path / "merged.tif"

        merge_tiffs([a], dst)

        with rasterio.open(dst) as ds:
            assert ds.descriptions == (None,)

    def test_rejects_empty_input(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            merge_tiffs([], tmp_path / "merged.tif")


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
