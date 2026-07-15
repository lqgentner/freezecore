"""Tests for freezecore.vectools module."""

from pathlib import Path
import tempfile

import geopandas as gpd
import pytest
import shapely

from freezecore.vectools import (
    drop_z_if_zero,
    is_z_axis_zero,
    save_and_read_parquet,
    simplify_multipolygons,
)


@pytest.fixture
def polygon_3d() -> shapely.Polygon:
    """Create a sample 3d polygon."""
    return shapely.Polygon([(0, 0, 1), (1, 0, 2), (1, 1, 3), (0, 1, 4), (0, 0, 1)])


@pytest.fixture
def sample_gdf() -> gpd.GeoDataFrame:
    """Create a sample GeoDataFrame."""
    point = shapely.Point(1, 2)
    line = shapely.LineString([(0, 0, 1), (1, 1, 2), (2, 2, 3)])
    poly_2d = shapely.Polygon([(0, 0), (1, 0), (1, 1), (0, 0)])
    poly_3d = shapely.Polygon([(0, 0, 1), (1, 0, 2), (1, 1, 3), (0, 0, 1)])
    multipolygon = shapely.MultiPolygon([poly_2d, poly_3d])
    geomcoll = shapely.GeometryCollection([point, line, poly_3d])

    return gpd.GeoDataFrame(
        {
            "name": ["A", "B", "C", "D", "E", "F"],
            "geometry": [point, line, poly_2d, poly_3d, multipolygon, geomcoll],
        },
        crs="EPSG:4326",
    )


class TestSaveAndReadParquet:
    """Test save_and_read_parquet function."""

    def test_save_and_read_basic(self, sample_gdf: gpd.GeoDataFrame) -> None:
        """Test basic save and read functionality."""
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "test.parquet"
            result_gdf = save_and_read_parquet(sample_gdf, out_path)

            # Check that file was created
            assert out_path.exists()

            # Check that returned GeoDataFrame matches original
            assert sample_gdf.equals(result_gdf)

    def test_save_creates_directory(self, sample_gdf: gpd.GeoDataFrame) -> None:
        """Test that function creates parent directories if they don't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "nested" / "dir" / "test.parquet"
            result_gdf = save_and_read_parquet(sample_gdf, out_path)

            # Check that nested directories were created
            assert out_path.exists()

            # Check data integrity
            assert sample_gdf.equals(result_gdf)

    def test_save_with_string_path(self, sample_gdf: gpd.GeoDataFrame) -> None:
        """Test function works with string path."""
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = str(Path(temp_dir) / "test.parquet")
            result_gdf = save_and_read_parquet(sample_gdf, out_path)

            assert Path(out_path).exists()
            assert sample_gdf.equals(result_gdf)


class TestIsZAxisZeros:
    """Test is_z_axis_zero function."""

    def test_all_z_zero(self, sample_gdf: gpd.GeoDataFrame) -> None:
        """Test when all Z coordinates are zero."""
        gdf_allzero = sample_gdf.copy()
        gdf_allzero.geometry = gdf_allzero.force_2d().force_3d()
        assert gdf_allzero.has_z.all()

        assert is_z_axis_zero(gdf_allzero) is True

    def test_some_z_nonzero(self, sample_gdf: gpd.GeoDataFrame) -> None:
        """Test when some Z coordinates are non-zero."""
        gdf_nonzero = sample_gdf.copy()
        gdf_nonzero.geometry = gdf_nonzero.force_3d()
        assert gdf_nonzero.has_z.all()

        assert is_z_axis_zero(gdf_nonzero) is False

    def test_no_z(self, sample_gdf: gpd.GeoDataFrame) -> None:
        """Test when not all geometries have z axes."""
        assert sample_gdf.has_z.any()
        assert not sample_gdf.has_z.all()

        with pytest.raises(ValueError, match="Geometry has no Z axis"):
            is_z_axis_zero(sample_gdf)


class TestDropZIfZero:
    """Test drop_z_if_zero function."""

    def test_all_z_zero(self, sample_gdf: gpd.GeoDataFrame) -> None:
        """Test when all Z coordinates are zero."""
        gdf_allzero = sample_gdf.copy()
        gdf_allzero.geometry = gdf_allzero.force_2d().force_3d()
        assert gdf_allzero.has_z.all()

        gdf_copy = gdf_allzero.copy()

        result = drop_z_if_zero(gdf_allzero)
        assert not result.has_z.all()

        # Assert that the data is not modified inplace
        assert gdf_allzero.equals(gdf_copy)

    def test_some_z_nonzero(self, sample_gdf: gpd.GeoDataFrame) -> None:
        """Test when some Z coordinates are non-zero."""
        gdf_nonzero = sample_gdf.copy()
        gdf_nonzero.geometry = gdf_nonzero.force_3d()
        assert gdf_nonzero.has_z.all()

        result = drop_z_if_zero(gdf_nonzero)
        assert result.equals(gdf_nonzero)

    def test_no_z(self, sample_gdf: gpd.GeoDataFrame) -> None:
        """Test when not all geometries have z axes."""
        assert sample_gdf.has_z.any()
        assert not sample_gdf.has_z.all()

        with pytest.raises(ValueError, match="Geometry has no Z axis"):
            is_z_axis_zero(sample_gdf)


def test_simplify_multipolygons() -> None:
    """Test simplify_multipolygons function."""
    polygon = shapely.Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
    multi_single = shapely.MultiPolygon([polygon])
    multi_multi = shapely.MultiPolygon([polygon, polygon])
    point = shapely.Point(1, 2)

    gdf = gpd.GeoDataFrame(
        {
            "name": ["A", "B", "C"],
            "geometry": [multi_single, multi_multi, point],
        },
    )
    gdf_copy = gdf.copy()

    result = simplify_multipolygons(gdf)

    # Check that MultiPolygon with single polygon was converted to Polygon
    assert result.geometry.iloc[0].equals(polygon)

    # Check that a MultiPolygon with multiple polygons was not changed
    assert result.geometry.iloc[1].equals(multi_multi)

    # Check that a different geometry was not changed
    assert result.geometry.iloc[2].equals(point)

    # Check that the original input was not modified
    assert gdf.equals(gdf_copy)
