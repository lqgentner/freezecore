"""Tests for freezecore.mgrs - MGRS grid system."""

from affine import Affine
from pyproj import CRS
import pytest
from shapely import box

from freezecore.mgrs import (
    MGRSGeoBox,
    MGRSGrid,
    UTMZones,
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
