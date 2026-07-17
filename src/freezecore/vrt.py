"""Creation of GDAL Virtual Datasets (VRTs) for compositing and mosaicking rasters."""

from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

from rasterio.coords import BoundingBox
from upath import UPath

from freezecore.raster import rasterio_open

type AnyPath = str | Path | UPath

_GDAL_DTYPE_NAMES = {
    "uint8": "Byte",
    "int8": "Int8",
    "uint16": "UInt16",
    "int16": "Int16",
    "uint32": "UInt32",
    "int32": "Int32",
    "uint64": "UInt64",
    "int64": "Int64",
    "float32": "Float32",
    "float64": "Float64",
}


def _get_raster_metadata(path: AnyPath) -> tuple[int, int, str, str]:
    """Get GDAL-compatible raster metadata.

    Parameters
    ----------
    path : str | Path | UPath
        Path to the raster file.

    Returns
    -------
    tuple of (int, int, str, str)
        A tuple of (x_size, y_size, geo_transform, projection) where
        geo_transform is a comma-separated GDAL affine transform string and
        projection is a WKT CRS string.
    """
    with rasterio_open(path) as ds:
        x_size = ds.width
        y_size = ds.height
        geo_transform = ", ".join(str(v) for v in ds.transform.to_gdal())
        projection = ds.crs.to_wkt()
    return x_size, y_size, geo_transform, projection


def create_decibel_vrt(
    src_path: AnyPath,
    output_vrt: AnyPath,
    *,
    from_intensity: bool = True,
) -> None:
    """Create a VRT file that applies a decibel conversion pixel function.

    Parameters
    ----------
    src_path : str | Path | UPath
        Path to the source raster file (linear scale).
    output_vrt : str | Path | UPath
        Path where the output VRT file will be written.
    from_intensity : bool, optional
        If True, uses a factor of 10 (intensity: 10*log10).
        If False, uses a factor of 20 (amplitude: 20*log10).
    """
    src_path = UPath(src_path)
    x_size, y_size, geo_transform, projection = _get_raster_metadata(src_path)
    fact = 10 if from_intensity else 20
    vrt_content = f"""<VRTDataset rasterXSize="{x_size}" rasterYSize="{y_size}">
  <SRS>{projection}</SRS>
  <GeoTransform>{geo_transform}</GeoTransform>

  <VRTRasterBand dataType="Float32" band="1" subClass="VRTDerivedRasterBand">
    <ColorInterp>Gray</ColorInterp>
    <Description>dB</Description>
    <NoDataValue>nan</NoDataValue>
    <PixelFunctionType>dB</PixelFunctionType>
    <PixelFunctionArguments fact="{fact}" />
    <SourceTransferType>Float32</SourceTransferType>
    <SimpleSource>
      <SourceFilename relativeToVRT="1">{src_path.name}</SourceFilename>
      <SourceBand>1</SourceBand>
    </SimpleSource>
  </VRTRasterBand>
</VRTDataset>"""

    UPath(output_vrt).write_text(vrt_content)


def create_rgb_vrt(
    vv_path: AnyPath,
    vh_path: AnyPath,
    output_vrt: AnyPath,
    *,
    decibel_scale: bool = False,
) -> None:
    """Create a 3-band RGB VRT from VV and VH rasters.

    The input scale can be linear or decibel.

    Band assignments:

    - Linear scale: Red=VV, Green=VH, Blue=VV/VH.
    - Decibel scale: Red=VV, Green=VH, Blue=VV-VH.

    Parameters
    ----------
    vv_path : str | Path | UPath
        Path to the VV polarization raster.
    vh_path : str | Path | UPath
        Path to the VH polarization raster.
    output_vrt : str | Path | UPath
        Path where the output VRT file will be written.
    decibel_scale : bool, optional
        Whether the input rasters are in decibel scale. Selects the band
        expressions and descriptions accordingly.
    """
    vv_path, vh_path = UPath(vv_path), UPath(vh_path)
    x_size, y_size, geo_transform, projection = _get_raster_metadata(vv_path)
    band_desc = ["VV_dB", "VH_dB", "VV_dB-VH_dB"] if decibel_scale else ["VV", "VH", "VV/VH"]
    operator = "diff" if decibel_scale else "div"

    vrt_content = f"""<VRTDataset rasterXSize="{x_size}" rasterYSize="{y_size}">
  <SRS>{projection}</SRS>
  <GeoTransform>{geo_transform}</GeoTransform>

  <VRTRasterBand dataType="Float32" band="1">
    <ColorInterp>Red</ColorInterp>
    <Description>{band_desc[0]}</Description>
    <NoDataValue>nan</NoDataValue>
    <SimpleSource>
      <SourceFilename relativeToVRT="1">{vv_path.name}</SourceFilename>
      <SourceBand>1</SourceBand>
    </SimpleSource>
  </VRTRasterBand>

  <VRTRasterBand dataType="Float32" band="2">
    <ColorInterp>Green</ColorInterp>
    <Description>{band_desc[1]}</Description>
    <NoDataValue>nan</NoDataValue>
    <SimpleSource>
      <SourceFilename relativeToVRT="1">{vh_path.name}</SourceFilename>
      <SourceBand>1</SourceBand>
    </SimpleSource>
  </VRTRasterBand>

  <VRTRasterBand dataType="Float32" band="3" subClass="VRTDerivedRasterBand">
    <ColorInterp>Blue</ColorInterp>
    <Description>{band_desc[2]}</Description>
    <NoDataValue>nan</NoDataValue>
    <PixelFunctionType>{operator}</PixelFunctionType>
    <SourceTransferType>Float32</SourceTransferType>
    <SimpleSource>
      <SourceFilename relativeToVRT="1">{vv_path.name}</SourceFilename>
      <SourceBand>1</SourceBand>
    </SimpleSource>
    <SimpleSource>
      <SourceFilename relativeToVRT="1">{vh_path.name}</SourceFilename>
      <SourceBand>1</SourceBand>
    </SimpleSource>
  </VRTRasterBand>
</VRTDataset>"""

    UPath(output_vrt).write_text(vrt_content)


class _TileInfo(NamedTuple):
    name: str
    bounds: BoundingBox
    width: int
    height: int
    px: float
    py: float
    dtype: str
    nodata: float | None
    description: str
    crs_wkt: str


def _read_tile_info(path: UPath) -> _TileInfo:
    with rasterio_open(path) as ds:
        return _TileInfo(
            name=path.name,
            bounds=ds.bounds,
            width=ds.width,
            height=ds.height,
            px=ds.transform.a,
            py=-ds.transform.e,
            dtype=ds.dtypes[0],
            nodata=ds.nodata,
            description=ds.descriptions[0] or "",
            crs_wkt=ds.crs.to_wkt(),
        )


def build_vrt_mosaic(files: Sequence[AnyPath], dst_vrt: AnyPath) -> None:
    """Mosaic same-resolution, single-band tiles into a VRT.

    Tiles are placed within the mosaic by their own bounds, and referenced by
    bare filename (``relativeToVRT``), so ``files`` must all share the same
    CRS, pixel size, dtype and band count, and live in the same directory as
    ``dst_vrt`` -- the mosaic and its tiles then stay valid together if the
    directory is moved.

    Parameters
    ----------
    files : Sequence[str | Path | UPath]
        Source tile files, all in the same directory as ``dst_vrt``.
    dst_vrt : str | Path | UPath
        Output VRT path.

    Raises
    ------
    ValueError
        If ``files`` is empty, or tiles have inconsistent pixel size.
    """
    if not files:
        msg = "files must not be empty"
        raise ValueError(msg)

    tiles = [_read_tile_info(UPath(f)) for f in files]

    px, py = tiles[0].px, tiles[0].py
    tolerance = 1e-6
    if any(abs(t.px - px) > tolerance or abs(t.py - py) > tolerance for t in tiles):
        msg = "All tiles must share the same pixel size to be mosaicked into a VRT"
        raise ValueError(msg)

    minx = min(t.bounds.left for t in tiles)
    maxy = max(t.bounds.top for t in tiles)
    maxx = max(t.bounds.right for t in tiles)
    miny = min(t.bounds.bottom for t in tiles)
    mosaic_w = round((maxx - minx) / px)
    mosaic_h = round((maxy - miny) / py)

    gdal_dtype = _GDAL_DTYPE_NAMES.get(tiles[0].dtype, "Float32")
    nodata = tiles[0].nodata
    tag = "ComplexSource" if nodata is not None else "SimpleSource"

    sources = []
    for t in tiles:
        xoff = round((t.bounds.left - minx) / px)
        yoff = round((maxy - t.bounds.top) / py)
        nodata_elem = f"\n      <NODATA>{nodata}</NODATA>" if nodata is not None else ""
        sources.append(f"""    <{tag}>
      <SourceFilename relativeToVRT="1">{t.name}</SourceFilename>
      <SourceBand>1</SourceBand>
      <SrcRect xOff="0" yOff="0" xSize="{t.width}" ySize="{t.height}" />
      <DstRect xOff="{xoff}" yOff="{yoff}" xSize="{t.width}" ySize="{t.height}" />{nodata_elem}
    </{tag}>""")

    nodata_band_elem = f"\n    <NoDataValue>{nodata}</NoDataValue>" if nodata is not None else ""
    vrt_content = f"""<VRTDataset rasterXSize="{mosaic_w}" rasterYSize="{mosaic_h}">
  <SRS>{tiles[0].crs_wkt}</SRS>
  <GeoTransform>{minx}, {px}, 0, {maxy}, 0, {-py}</GeoTransform>
  <VRTRasterBand dataType="{gdal_dtype}" band="1">{nodata_band_elem}
    <ColorInterp>Gray</ColorInterp>
    <Description>{tiles[0].description}</Description>
{chr(10).join(sources)}
  </VRTRasterBand>
</VRTDataset>"""

    UPath(dst_vrt).write_text(vrt_content)
