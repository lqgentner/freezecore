"""Provides vector geometry related tools."""

from pathlib import Path
from secrets import token_hex

import geopandas as gpd
from shapely import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from shapely.geometry.base import BaseGeometry


def save_and_read_parquet(gdf: gpd.GeoDataFrame, out_path: str | Path) -> gpd.GeoDataFrame:
    """
    Save a GeoDataFrame as a GeoParquet file and read it back for verification.

    Parameters
    ----------
    gdf : gpd.GeoDataFrame
        The GeoDataFrame to be saved.
    out_path : str or Path
        The file path where the GeoParquet file will be saved.

    Returns
    -------
    gpd.GeoDataFrame
        The GeoDataFrame read back from the saved GeoParquet file.

    Notes
    -----
    The function ensures that the output directory exists before saving.
    It uses the 'pyarrow' engine for writing the Parquet file. The write is
    staged to a unique sibling temp file and atomically moved into place, so a
    crash mid-write cannot leave a truncated file at ``out_path``.

    """
    out_path = Path(out_path)
    # Make sure the location exists
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_name(f".{out_path.name}.{token_hex(8)}.tmp")
    try:
        gdf.to_parquet(tmp_path, engine="pyarrow")
        tmp_path.replace(out_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return gpd.read_parquet(out_path)


def drop_z_if_zero(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Remove the Z coordinate from all geometries in a GeoDataFrame if all Z coordinates are zero.

    Parameters
    ----------
    gdf : geopandas.GeoDataFrame
        GeoDataFrame containing geometries with potential Z coordinates.

    Returns
    -------
    geopandas.GeoDataFrame
        GeoDataFrame with Z coordinates removed if they are all zero.

    Raises
    ------
    ValueError
        If the geometry does not have a Z axis.
    TypeError
        If the geometry type is unknown.

    """
    gdf_copy = gdf.copy()
    if is_z_axis_zero(gdf):
        gdf_copy.geometry = gdf_copy.force_2d()
    return gdf_copy


def is_z_axis_zero(gdf: gpd.GeoDataFrame) -> bool:
    """
    Check if the Z axis in a GeoDataFrame is always zero.

    Parameters
    ----------
    gdf : geopandas.GeoDataFrame
        GeoDataFrame containing geometries with potential Z coordinates.

    Returns
    -------
    bool
        True if all Z values are zero, False otherwise.

    Raises
    ------
    ValueError
        If the geometry does not have a Z axis.
    TypeError
        If the geometry type is unknown.

    """
    z_values = gdf.geometry.map(_extract_z_values)
    return all(all(z == 0 for z in z_list) for z_list in z_values)


def _extract_z_values(geom: BaseGeometry) -> list[float]:
    """
    Extract all Z values from a shapely geometry.

    Parameters
    ----------
    geom : shapely.geometry.base.BaseGeometry
        Geometry with Z coordinates.

    Returns
    -------
    list[float]
        List of Z values.

    Raises
    ------
    ValueError
        If the geometry does not have a Z axis.
    TypeError
        If the geometry type is unknown.

    """
    if geom.is_empty:
        return []
    if not geom.has_z:
        msg = "Geometry has no Z axis"
        raise ValueError(msg)
    match geom:
        case Point():
            z = [geom.z]
        case LineString():
            z = [coord[2] for coord in geom.coords]
        case Polygon():
            z = _polygon_z_values(geom)
        case MultiPoint():
            z = [point.z for point in geom.geoms]
        case MultiLineString():
            z = [coord[2] for line in geom.geoms for coord in line.coords]
        case MultiPolygon():
            z = [value for poly in geom.geoms for value in _polygon_z_values(poly)]
        case GeometryCollection():
            z = _collection_z_values(geom)
        case _:
            msg = f"Unsupported geometry type '{type(geom).__name__}'."
            raise TypeError(msg)
    return z


def _polygon_z_values(geom: Polygon) -> list[float]:
    """Extract Z values from a polygon's exterior and every interior ring."""
    z = [coord[2] for coord in geom.exterior.coords]
    for ring in geom.interiors:
        z.extend(coord[2] for coord in ring.coords)
    return z


def _collection_z_values(geom: GeometryCollection) -> list[float]:
    """Extract Z from collection members that carry it.

    A collection may mix 2D and 3D members; skipping the members without Z
    keeps a 2D sibling from aborting the whole traversal.
    """
    z: list[float] = []
    for sub_geom in geom.geoms:
        if sub_geom.is_empty or not sub_geom.has_z:
            continue
        z.extend(_extract_z_values(sub_geom))
    return z


def simplify_multipolygons(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Convert single-polygon MultiPolygons to Polygons.

    Parameters
    ----------
    gdf : geopandas.GeoDataFrame
        GeoDataFrame containing geometries.

    Returns
    -------
    geopandas.GeoDataFrame
        GeoDataFrame with single-polygon MultiPolygons converted to Polygons.

    """
    gdf_copy = gdf.copy()
    gdf_copy.geometry = [
        geom.geoms[0] if isinstance(geom, MultiPolygon) and len(geom.geoms) == 1 else geom
        for geom in gdf_copy.geometry
    ]
    return gdf_copy
