"""Provides MGRS grid square generation and manipulation in 100 km and 10 km resolution."""

from __future__ import annotations

from copy import copy
from typing import TYPE_CHECKING, Any, overload

from affine import Affine
import geopandas as gpd
from geopandas import GeoSeries
import mgrs
import numpy as np
from odc.geo.geobox import GeoBox
import pandas as pd
from pyproj import CRS, Transformer
import shapely
from shapely import box, union_all
from shapely.geometry.base import BaseGeometry

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Any, Literal, Self

    from numpy.typing import ArrayLike, NDArray
    from odc.geo.geobox import SomeShape

    type GeoArray = NDArray[np.object_]

    Hemisphere = Literal["N", "S"]

WGS84 = CRS.from_epsg(4326)


@overload
def transform_shapely(
    geom: GeoArray,
    crs_from: CRS,
    crs_to: CRS,
) -> GeoArray: ...


@overload
def transform_shapely(
    geom: BaseGeometry,
    crs_from: CRS,
    crs_to: CRS,
) -> BaseGeometry: ...


def transform_shapely(
    geom: GeoArray | BaseGeometry,
    crs_from: CRS,
    crs_to: CRS,
) -> GeoArray | BaseGeometry:
    """Transform a shapely geometry using a pyproj Transformer.

    Parameters
    ----------
    geom : BaseGeometry | GeoArray
        The geometry or array of geometries to transform.
    crs_from : CRS
        Source coordinate reference system.
    crs_to : CRS
        Target coordinate reference system.

    Returns
    -------
    BaseGeometry | GeoArray
        The transformed geometry or array of geometries.
    """
    transformer = Transformer.from_crs(crs_from=crs_from, crs_to=crs_to, always_xy=True)
    return shapely.transform(geom, transformer.transform, interleaved=False)  # type: ignore[type-var, arg-type]


_SOUTHERN_BANDS: frozenset[str] = frozenset("CDEFGHJKLM")

_ZONE_31 = 31
_ZONE_32 = 32
_ZONE_33 = 33
_ZONE_34 = 34
_ZONE_35 = 35
_ZONE_36 = 36
_ZONE_37 = 37

_NORTHERN_EXCEPTION_ZONES = {
    _ZONE_31,
    _ZONE_32,
    _ZONE_33,
    _ZONE_34,
    _ZONE_35,
    _ZONE_36,
    _ZONE_37,
}


def utms_to_epsgs(zone: ArrayLike, hemisphere: ArrayLike) -> NDArray[np.integer]:
    """Convert a UTM zones and hemispheres to numeric EPSG codes.

    Returns
    -------
    NDArray[np.integer]
        EPSG codes (326xx for north, 327xx for south).
    """
    is_south = hemisphere == "S"
    base = np.where(is_south, 32700, 32600)
    return np.asarray(base + zone)


def utm_to_crs(zone: int, hemisphere: Hemisphere) -> CRS:
    """Convert a numeric UTM zone and hemisphere to a pyproj.CRS.

    Returns
    -------
    CRS
        The ``pyproj.CRS`` for the UTM zone.
    """
    base = 32700 if hemisphere == "S" else 32600
    epsg = base + int(zone)
    return CRS.from_epsg(epsg)


def mgrs_to_crs(mgrs_code: str) -> CRS:
    """Derive the UTM CRS from an MGRS grid reference string.

    Parameters
    ----------
    mgrs_code : str
        An MGRS grid reference (e.g. ``"32TMT64"``).

    Returns
    -------
    CRS
        The ``pyproj.CRS`` for the UTM zone.

    Raises
    ------
    ValueError
        If the reference is too short (fewer than 3 characters).
    """
    _min_mgrs_len = 3
    if len(mgrs_code) < _min_mgrs_len:
        msg = f"MGRS mgrs_code is too short: {mgrs_code!r}"
        raise ValueError(msg)
    zone = int(mgrs_code[:2])
    band = mgrs_code[2]
    epsg = (32700 if band in _SOUTHERN_BANDS else 32600) + zone
    return CRS.from_epsg(epsg)


class MGRSGeoBox(GeoBox):
    """A 10x10 km MGRS grid square backed by ``odc.geo.GeoBox``.

    Parameters
    ----------
    mgrs_code : str
        MGRS grid reference (e.g. ``"32TMT64"``).
    shape : SomeShape
        Raster dimensions ``(height, width)`` in pixels.
    affine : Affine
        Affine transformation from pixel to CRS coordinates.
    crs : CRS
        The coordinate reference system of the cell.
    """

    def __init__(
        self,
        mgrs_code: str,
        shape: SomeShape,
        affine: Affine,
        crs: CRS,
    ) -> None:
        self.mgrs_code = mgrs_code
        super().__init__(shape, affine, crs)

    @classmethod
    def from_mgrs(cls, mgrs_code: str, resolution: float = 10.0) -> Self:
        """Create a grid square from an MGRS reference string.

        Parameters
        ----------
        mgrs_code : str
            MGRS grid reference (e.g. ``"32TMT64"``).
        resolution : float
            Pixel resolution in metres. Default is 10.0.

        Returns
        -------
        MGRSGeoBox
            The grid square as a GeoBox.
        """
        converter = mgrs.MGRS()
        zone, hemisphere, easting, northing = converter.MGRSToUTM(mgrs_code)
        crs = utm_to_crs(zone, hemisphere)

        n_pixels = int(_10KM_SIZE / resolution)
        nw_northing = northing + _10KM_SIZE
        affine = Affine(resolution, 0, easting, 0, -resolution, nw_northing)

        return cls(mgrs_code, (n_pixels, n_pixels), affine, crs)

    def __repr__(self) -> str:
        """Return a string representation of the MGRSGeoBox."""
        return f"MGRSGeoBox({self.mgrs_code!r})"


class UTMZones:
    """Generate all 120 UTM zones (60 north + 60 south) in WGS84.

    Handles the Norway (zone 31V/32V) and Svalbard (band X)
    exceptions where UTM zone boundaries deviate from the
    standard 6° longitudinal width.
    """

    def __init__(self) -> None:
        self.gdf = self._build_zones()

    def get_zone_geometry(self, zone: int, hemisphere: Hemisphere) -> BaseGeometry:
        """Return the WGS84 geometry of a single UTM zone."""
        gdf = self.gdf
        return gdf[(gdf.zone == zone) & (gdf.hemisphere == hemisphere)].iloc[0].geometry

    def find_intersecting(self, geometry: GeoArray | GeoSeries | BaseGeometry) -> gpd.GeoDataFrame:
        """Return UTM zones that intersect the given geometry."""
        # if isinstance(geometry, np.ndarray):
        #     geometry = gpd.GeoSeries(geometry)
        hits = self.gdf.sindex.query(geometry, predicate="intersects")[1]
        mask = pd.Series(data=False, index=self.gdf.index)
        mask[hits] = True

        return self.gdf[mask]

    def _build_zones(self) -> gpd.GeoDataFrame:
        """Generate a GeoDataFrame containing all UTM zones."""
        parts: list[dict[str, Any]] = []

        for zone in range(1, 61):
            west = (zone - 1) * 6 - 180
            east = west + 6

            parts.append(
                {
                    "name": f"{zone}S",
                    "zone": zone,
                    "hemisphere": "S",
                    "epsg": utms_to_epsgs(zone, "S"),
                    "geometry": box(west, -80, east, 0),
                },
            )

            if zone in _NORTHERN_EXCEPTION_ZONES:
                geom = self._build_north_exception(zone, west, east)
            else:
                geom = box(west, 0, east, 84)

            parts.append(
                {
                    "name": f"{zone}N",
                    "zone": zone,
                    "hemisphere": "N",
                    "epsg": utms_to_epsgs(zone, "N"),
                    "geometry": geom,
                },
            )

        return gpd.GeoDataFrame(parts, crs=WGS84)

    @classmethod
    def _build_north_exception(cls, zone: int, west: float, east: float) -> BaseGeometry:
        """Build geometry for a northern UTM zone with Norway/Svalbard exceptions.

        Parameters
        ----------
        zone : int
            UTM zone number (must be in 31-37).
        west : float
            Standard western boundary of the zone in degrees longitude.
        east : float
            Standard eastern boundary of the zone in degrees longitude.

        Returns
        -------
        Polygon
            Merged zone geometry in WGS84.
        """
        parts = [box(west, 0, east, 56)]

        if zone == _ZONE_31:
            parts.append(box(west, 56, 3, 64))
        elif zone == _ZONE_32:
            parts.append(box(3, 56, east, 64))
        else:
            parts.append(box(west, 56, east, 64))

        parts.append(box(west, 64, east, 72))

        if zone in (_ZONE_32, _ZONE_34, _ZONE_36):
            pass
        elif zone == _ZONE_31:
            parts.append(box(west, 72, 9, 84))
        elif zone == _ZONE_33:
            parts.append(box(9, 72, 21, 84))
        elif zone == _ZONE_35:
            parts.append(box(21, 72, 33, 84))
        elif zone == _ZONE_37:
            parts.append(box(33, 72, east, 84))

        return union_all(parts)


_100KM_SIZE = 100_000
_10KM_SIZE = 10_000
_FALSE_EASTING = 500_000
_FALSE_NORTHING_SOUTH = 10_000_000
_MGRS_PRECISION_10KM = 1


class MGRSGrid:
    """MGRS grid squares at 10 km resolution."""

    def __init__(
        self,
        filter_geometry: GeoSeries | GeoArray | BaseGeometry,
        resolution: float = 10.0,
    ) -> None:
        self._filter_tree = self._strtree_from_geometry(filter_geometry)
        self.resolution = resolution

        self._fine_template = self._make_subdivision_template()
        self.utm_zones = UTMZones()

        self.northings: NDArray[np.int32] = np.empty(0, dtype=np.int32)
        self.eastings: NDArray[np.int32] = np.empty(0, dtype=np.int32)
        self.zones: NDArray[np.uint8] = np.empty(0, dtype=np.uint8)
        self.hemispheres: NDArray[np.str_] = np.empty(0, dtype=np.str_)
        self.geometries: NDArray[np.object_] = np.empty(0, dtype=np.object_)

        self._materialize()

    @staticmethod
    def _strtree_from_geometry(
        geometry: gpd.GeoDataFrame | GeoSeries | GeoArray | BaseGeometry,
    ) -> shapely.STRtree:
        """Create a new STRtree spatial index from a geometry."""
        if hasattr(geometry, "crs") and geometry.crs != WGS84:
            name = geometry.crs.name if isinstance(geometry.crs, CRS) else str(geometry.crs)
            msg = f"`filter_geometry must be '{WGS84.name}', got '{name}'"
            raise ValueError(msg)
        if isinstance(geometry, gpd.GeoDataFrame):
            geoms = geometry.geometry.to_numpy()
        if isinstance(geometry, GeoSeries):
            geoms = geometry.to_numpy()
        if isinstance(geometry, BaseGeometry):
            geoms = np.array([geometry])
        # set empty geometries to None to maintain indexing
        non_empty = geoms.copy()
        non_empty[shapely.is_empty(non_empty)] = None
        return shapely.STRtree(non_empty)

    def _make_subdivision_template(self) -> NDArray[np.int32]:
        """Create a template of 10 km cells anchored at origin (0, 0).

        Returns
        -------
        NDArray[np.int32]
            Array of shape (100, 4) with columns ``[x_min, y_min, x_max, y_max]``
            for each 10 km cell within a single 100 km cell.
        """
        n = int(_100KM_SIZE / _10KM_SIZE)
        offsets = np.arange(n, dtype=np.int32) * _10KM_SIZE
        xx, yy = np.meshgrid(offsets, offsets)
        sw_x = xx.ravel()
        sw_y = yy.ravel()
        return np.column_stack([sw_x, sw_y, sw_x + _10KM_SIZE, sw_y + _10KM_SIZE])

    def _intersects_any(self, geoms: GeoArray) -> NDArray[np.bool_]:
        """Return a boolean mask of geometries that intersect any filter geometry."""
        hits = self._filter_tree.query(geoms, predicate="intersects")[0]
        mask = np.zeros(len(geoms), dtype=np.bool_)
        mask[hits] = True
        return mask

    def _materialize(self) -> None:
        filter_geom = self._filter_tree.geometries
        matched_utm_zones = self.utm_zones.find_intersecting(filter_geom)
        for _, zone_row in matched_utm_zones.iterrows():
            zone: int = zone_row["zone"]
            hemisphere: Hemisphere = zone_row["hemisphere"]
            self._materialize_zone(zone, hemisphere)

        # Add Identifier
        mgrs_codes = self._compute_mgrs_codes(
            self.eastings,
            self.northings,
            zones=self.zones,
            hemispheres=self.hemispheres,
        )
        # Sort
        idxs = np.argsort(mgrs_codes)
        self.mgrs_codes = mgrs_codes[idxs]
        self.eastings = self.eastings[idxs]
        self.northings = self.northings[idxs]
        self.zones = self.zones[idxs]
        self.hemispheres = self.hemispheres[idxs]
        self.geometries = self.geometries[idxs]

    def _materialize_zone(self, zone: int, hemisphere: Hemisphere) -> None:
        utm_crs = utm_to_crs(zone, hemisphere)
        zone_geom_wgs = self.utm_zones.get_zone_geometry(zone, hemisphere)
        # Stage 1: Coarse 100 km cells
        coarse_x, coarse_y = self._build_coarse_coords(zone, hemisphere)
        # Only keep intersecting geometries
        coarse_boxes_utm = shapely.box(
            coarse_x,
            coarse_y,
            coarse_x + _100KM_SIZE,
            coarse_y + _100KM_SIZE,
        )
        coarse_boxes_wgs = transform_shapely(coarse_boxes_utm, utm_crs, WGS84)
        intersects_geom = self._intersects_any(coarse_boxes_wgs)
        intersects_zone = shapely.intersects(coarse_boxes_wgs, zone_geom_wgs)
        mask = intersects_geom & intersects_zone
        coarse_x = coarse_x[mask]
        coarse_y = coarse_y[mask]

        # Stage 2: Subdivide coarse hits into 10 km cells
        fine_x, fine_y = self._subdivide_coarse_coords(coarse_x, coarse_y)
        # Only keep intersecting geometries
        fine_boxes_utm = shapely.box(
            fine_x,
            fine_y,
            fine_x + _10KM_SIZE,
            fine_y + _10KM_SIZE,
        )
        fine_boxes_wgs = transform_shapely(fine_boxes_utm, utm_crs, WGS84)
        intersects_geom = self._intersects_any(fine_boxes_wgs)
        intersects_zone = shapely.intersects(fine_boxes_wgs, zone_geom_wgs)
        mask = intersects_geom & intersects_zone

        n = len(mask[mask])
        self.eastings = np.concat([self.eastings, fine_x[mask]])
        self.northings = np.concat([self.northings, fine_y[mask]])
        self.zones = np.concat([self.zones, np.full(n, zone, dtype=np.uint8)])
        self.hemispheres = np.concat([self.hemispheres, np.full(n, hemisphere, dtype=np.str_)])
        self.geometries = np.concat([self.geometries, fine_boxes_wgs[mask]])

    def _build_coarse_coords(
        self,
        zone: int,
        hemisphere: Hemisphere,
    ) -> tuple[NDArray[np.int32], NDArray[np.int32]]:
        """Build a 100 km-spaced MGRS grid in local UTM coordinates.

        Parameters
        ----------
        zone : int
            UTM zone number (1-60).
        hemisphere : Hemisphere
            ``'N'`` for north or ``'S'`` for south.

        Returns
        -------
        tuple[NDArray[np.int32], NDArray[np.int32]]
            100 km-spaced eastings and northings.
        """
        cell_size = _100KM_SIZE
        zone_geom_wgs = self.utm_zones.get_zone_geometry(zone=zone, hemisphere=hemisphere)
        utm_crs = utm_to_crs(zone, hemisphere)
        zone_geom_utm = transform_shapely(zone_geom_wgs, WGS84, utm_crs)
        minx, miny, maxx, maxy = zone_geom_utm.bounds

        false_northing = _FALSE_NORTHING_SOUTH if hemisphere == "S" else 0

        easting_start = _FALSE_EASTING + np.floor((minx - _FALSE_EASTING) / cell_size) * cell_size
        northing_start = false_northing + np.floor((miny - false_northing) / cell_size) * cell_size
        easting_end = _FALSE_EASTING + np.ceil((maxx - _FALSE_EASTING) / cell_size) * cell_size
        northing_end = false_northing + np.ceil((maxy - false_northing) / cell_size) * cell_size

        easting_coords = np.arange(easting_start, easting_end, cell_size, dtype=np.int32)
        northing_coords = np.arange(northing_start, northing_end, cell_size, dtype=np.int32)

        easting_grid, northing_grid = np.meshgrid(easting_coords, northing_coords)

        return easting_grid.ravel(), northing_grid.ravel()

    def _subdivide_coarse_coords(
        self,
        eastings: NDArray[np.int32],
        northings: NDArray[np.int32],
    ) -> tuple[NDArray[np.int32], NDArray[np.int32]]:
        """Subdivide the 100 km-spaced grid into a 10 km grid using the template.

        Returns
        -------
        tuple[NDArray[np.int32], NDArray[np.int32]]
            10 km-spaced eastings and northings.
        """
        tpl = self._fine_template.T
        x = eastings[..., np.newaxis]
        y = northings[..., np.newaxis]

        fine_x = (x + tpl[0]).ravel()
        fine_y = (y + tpl[1]).ravel()

        return fine_x, fine_y

    def _compute_mgrs_codes(
        self,
        eastings: NDArray[np.int32],
        northings: NDArray[np.int32],
        *,
        zones: NDArray[np.uint8],
        hemispheres: NDArray[np.str_],
        precision: int = _MGRS_PRECISION_10KM,
    ) -> NDArray[np.str_]:
        """Compute MGRS references from UTM coordinates.

        Parameters
        ----------
        eastings : NDArray[np.int32]
            UTM eastings.
        northings : NDArray[np.int32]
            UTM northings.
        zones : NDArray[np.uint8]
            UTM zone numbers.
        hemispheres : NDArray[np.str_]
            Hemisphere letters ('N' or 'S').
        precision : int
            MGRS precision level (0 = 100 km, 1 = 10 km).

        Returns
        -------
        NDArray[np.str_]
            Array of MGRS reference strings.
        """
        self.utm_to_mgrs = np.vectorize(
            mgrs.MGRS().UTMToMGRS,
            otypes=[str],
            excluded={"MGRSPrecision"},
        )

        return self.utm_to_mgrs(
            zones,
            hemispheres,
            eastings,
            northings,
            MGRSPrecision=precision,
        )

    def to_geodataframe(
        self,
    ) -> gpd.GeoDataFrame:
        """Build a GeoDataFrame from filtered arrays in WGS84.

        Returns
        -------
        gpd.GeoDataFrame
            GeoDataFrame in WGS84 with standard columns.
        """
        return gpd.GeoDataFrame(
            {
                "mgrs_code": self.mgrs_codes,
                "zone": self.zones,
                "hemisphere": self.hemispheres,
                "easting": self.eastings,
                "northing": self.northings,
                "epsg": utms_to_epsgs(self.zones, self.hemispheres),
                "geometry": self.geometries,
            },
            crs=WGS84,
        )

    def __len__(self) -> int:
        """Return the number of grid squares."""
        return len(self.eastings)

    @overload
    def __getitem__(self, index: int) -> MGRSGeoBox: ...
    @overload
    def __getitem__(self, index: slice) -> Self: ...

    def __getitem__(self, index: int | slice) -> MGRSGeoBox | Self:
        """Return an MGRSGeoBox by index or a sliced MGRSGrid."""
        if isinstance(index, slice):
            new = copy(self)
            new.mgrs_codes = self.mgrs_codes[index]
            new.eastings = self.eastings[index]
            new.northings = self.northings[index]
            new.zones = self.zones[index]
            new.hemispheres = self.hemispheres[index]
            return new
        return self._entry_to_geobox(index)

    def __iter__(self) -> Iterator[MGRSGeoBox]:
        """Iterate over all grid squares as MGRSGeoBox instances."""
        for idx in range(len(self)):
            yield self._entry_to_geobox(idx)

    def _entry_to_geobox(self, index: int) -> MGRSGeoBox:
        """Convert an entry by index to an MGRSGeoBox."""
        resolution = self.resolution
        mgrs_code = str(self.mgrs_codes[index])
        zone = self.zones[index]
        hemisphere = self.hemispheres[index]
        crs = utm_to_crs(zone, hemisphere)
        n_pixels = int(_10KM_SIZE / resolution)
        sw_easting = self.eastings[index]
        nw_northing = self.northings[index] + _10KM_SIZE
        affine = Affine(resolution, 0, sw_easting, 0, -resolution, nw_northing)
        return MGRSGeoBox(
            mgrs_code=mgrs_code,
            shape=(n_pixels, n_pixels),
            affine=affine,
            crs=crs,
        )
