"""Tests for freezebase.mgrs - MGRS grid system."""

from affine import Affine
import numpy as np
from pyproj import CRS
import pytest
from shapely import Point, box

from freezebase.mgrs import (
    MGRSGeoBox,
    MGRSGrid,
    UTMZones,
    mgrs_to_crs,
    utm_to_crs,
    utms_to_epsgs,
)

# ---------------------------------------------------------------------------
# utm_to_epsg
# ---------------------------------------------------------------------------


class TestUtmToEpsg:
    """Tests for ``utms_to_epsgs``."""

    def test_northern_hemisphere(self) -> None:
        assert utms_to_epsgs(32, "N") == 32632

    def test_southern_hemisphere(self) -> None:
        assert utms_to_epsgs(34, "S") == 32734

    def test_list_inputs_broadcast_per_element(self) -> None:
        # Previously returned [32632, 32634] because the scalar hemisphere
        # comparison never matched the list.
        result = utms_to_epsgs([32, 34], ["N", "S"])
        assert result.tolist() == [32632, 32734]

    def test_array_inputs(self) -> None:
        result = utms_to_epsgs(np.array([1, 60]), np.array(["N", "S"]))
        assert result.tolist() == [32601, 32760]

    def test_rejects_invalid_zone(self) -> None:
        with pytest.raises(ValueError, match="UTM zone"):
            utms_to_epsgs([0, 61], ["N", "S"])

    def test_rejects_invalid_hemisphere(self) -> None:
        with pytest.raises(ValueError, match="Hemisphere"):
            utms_to_epsgs([32], ["X"])


class TestUtmToCrs:
    """Tests for ``utm_to_crs``."""

    def test_valid(self) -> None:
        assert utm_to_crs(32, "N").to_epsg() == 32632
        assert utm_to_crs(32, "S").to_epsg() == 32732

    def test_rejects_invalid_hemisphere(self) -> None:
        with pytest.raises(ValueError, match="Hemisphere"):
            utm_to_crs(32, "X")

    def test_rejects_invalid_zone(self) -> None:
        with pytest.raises(ValueError, match="UTM zone"):
            utm_to_crs(61, "N")


# ---------------------------------------------------------------------------
# UTMZoneGenerator
# ---------------------------------------------------------------------------


class TestUTMZoneGenerator:
    """Tests for ``UTMZoneGenerator.generate``."""

    def test_returns_120_zones(self) -> None:
        gdf = UTMZones().gdf
        assert len(gdf) == 120

    def test_correct_columns(self) -> None:
        gdf = UTMZones().gdf
        assert list(gdf.columns) == ["name", "zone", "hemisphere", "epsg", "geometry"]

    def test_crs_is_wgs84(self) -> None:
        gdf = UTMZones().gdf
        assert str(gdf.crs) == "EPSG:4326"

    def test_get_zone_geometry_rejects_invalid_zone(self) -> None:
        # Previously exposed an opaque `iloc[0]` IndexError.
        with pytest.raises(ValueError, match="UTM zone"):
            UTMZones().get_zone_geometry(99, "N")

    def test_get_zone_geometry_rejects_invalid_hemisphere(self) -> None:
        with pytest.raises(ValueError, match="Hemisphere"):
            UTMZones().get_zone_geometry(32, "X")

    def test_find_intersecting_scalar_geometry(self) -> None:
        # Previously raised IndexError for a scalar geometry query.
        hits = UTMZones().find_intersecting(Point(8.5, 47.4))
        assert len(hits) >= 1
        assert (hits.zone == 32).any()

    def test_find_intersecting_array_geometry(self) -> None:
        geoms = np.array([Point(8.5, 47.4), Point(-100.0, 40.0)])
        hits = UTMZones().find_intersecting(geoms)
        assert len(hits) >= 2


# ---------------------------------------------------------------------------
# MGRSGrid
# ---------------------------------------------------------------------------

ZURICH_AOI = box(8.4, 47.3, 8.6, 47.5)


class TestMGRSGrid:
    """Tests for ``MGRSGrid``."""

    @pytest.fixture
    def grid(self) -> MGRSGrid:
        return MGRSGrid(ZURICH_AOI)

    def test_zurich_nonempty(self, grid: MGRSGrid) -> None:
        assert len(grid) > 0

    def test_len_consistent(self, grid: MGRSGrid) -> None:
        assert len(grid) == len(list(grid))

    def test_iter_yields_grid_squares(self, grid: MGRSGrid) -> None:
        for cell in grid:
            assert isinstance(cell, MGRSGeoBox)

    def test_getitem_int(self, grid: MGRSGrid) -> None:
        assert isinstance(grid[0], MGRSGeoBox)

    def test_getitem_slice(self, grid: MGRSGrid) -> None:
        sliced = grid[0:3]
        assert isinstance(sliced, MGRSGrid)
        assert len(sliced) == min(3, len(grid))

    def test_slice_to_geodataframe(self, grid: MGRSGrid) -> None:
        # Previously raised an unequal-array ValueError because the geometry
        # array was not sliced alongside the other backing arrays.
        gdf = grid[:1].to_geodataframe()
        assert len(gdf) == 1
        assert gdf.geometry.notna().all()

    def test_accepts_ndarray_filter_geometry(self) -> None:
        # Previously raised UnboundLocalError for an ndarray input.
        grid = MGRSGrid(np.array([ZURICH_AOI]))
        assert len(grid) > 0

    def test_to_geodataframe_columns(self, grid: MGRSGrid) -> None:
        gdf = grid.to_geodataframe()
        expected = ["mgrs_code", "zone", "hemisphere", "easting", "northing", "epsg", "geometry"]
        assert list(gdf.columns) == expected

    def test_to_geodataframe_crs(self, grid: MGRSGrid) -> None:
        gdf = grid.to_geodataframe()
        assert str(gdf.crs) == "EPSG:4326"

    def test_no_duplicate_mgrs_codes(self, grid: MGRSGrid) -> None:
        codes = [cell.mgrs_code for cell in grid]
        assert len(codes) == len(set(codes))

    def test_mgrs_codes_sorted(self, grid: MGRSGrid) -> None:
        codes = [cell.mgrs_code for cell in grid]
        assert codes == sorted(codes)

    def test_geometries_intersect_aoi(self, grid: MGRSGrid) -> None:
        gdf = grid.to_geodataframe()
        assert gdf.geometry.intersects(ZURICH_AOI).all()

    def test_geobox_matches_from_mgrs(self, grid: MGRSGrid) -> None:
        """GeoBox from grid index must match MGRSGeoBox.from_mgrs."""
        for i in range(len(grid)):
            geobox_grid = grid[i]
            geobox_mgrs = MGRSGeoBox.from_mgrs(geobox_grid.mgrs_code)
            assert geobox_grid.affine == geobox_mgrs.affine, (
                f"{geobox_grid.mgrs_code}: grid affine {geobox_grid.affine} "
                f"!= from_mgrs affine {geobox_mgrs.affine}"
            )
            assert geobox_grid.crs == geobox_mgrs.crs
            assert geobox_grid.shape == geobox_mgrs.shape

    def test_geodataframe_geometry_sorted_with_codes(self) -> None:
        """Geometry column must stay aligned with MGRS codes after sorting."""
        geom = box(-158.5, 20.5, -157.0, 21.8)
        grid = MGRSGrid(geom)
        gdf = grid.to_geodataframe()

        row = gdf[gdf.mgrs_code == "04QFJ15"].iloc[0]

        assert row.easting == 610000
        assert row.northing == 2350000
        assert row.geometry.contains(box(-157.9, 21.28, -157.88, 21.30))


# ---------------------------------------------------------------------------
# MGRSGeoBox
# ---------------------------------------------------------------------------


class TestMGRSGeoBox:
    """Tests for ``MGRSGeoBox``."""

    def test_mgrs_code_attribute(self) -> None:
        crs = CRS.from_epsg(32632)
        affine = Affine(10, 0, 400000, 0, -10, 5300000)
        cell = MGRSGeoBox("32TMT64", (1000, 1000), affine, crs)
        assert cell.mgrs_code == "32TMT64"

    def test_from_mgrs(self) -> None:
        cell = MGRSGeoBox.from_mgrs("32TMT64")
        assert cell.mgrs_code == "32TMT64"
        assert cell.crs is not None
        assert cell.crs.to_epsg() == 32632

    def test_from_mgrs_rejects_non_positive_resolution(self) -> None:
        with pytest.raises(ValueError, match="resolution must be positive"):
            MGRSGeoBox.from_mgrs("32TMT64", resolution=0)

    def test_from_mgrs_rejects_indivisible_resolution(self) -> None:
        # 3 m does not evenly divide the 10 km cell.
        with pytest.raises(ValueError, match="evenly divide"):
            MGRSGeoBox.from_mgrs("32TMT64", resolution=3)

    def test_from_mgrs_rejects_wrong_precision(self) -> None:
        # A 100 km reference must not be silently treated as a 10 km cell.
        with pytest.raises(ValueError, match="10 km MGRS reference"):
            MGRSGeoBox.from_mgrs("32TMT")


class TestMgrsToCrs:
    """Tests for ``mgrs_to_crs``."""

    def test_two_digit_zone(self) -> None:
        assert mgrs_to_crs("32TMT64").to_epsg() == 32632

    def test_single_digit_zone(self) -> None:
        # Previously failed because a two-digit zone was assumed.
        assert mgrs_to_crs("4QFJ15").to_epsg() == 32604

    def test_southern_band(self) -> None:
        assert mgrs_to_crs("34DEF12").to_epsg() == 32734

    def test_rejects_malformed(self) -> None:
        with pytest.raises(ValueError, match="Malformed MGRS"):
            mgrs_to_crs("not-mgrs")
