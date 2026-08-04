# freezecore

Lightweight geospatial helpers for reproducible MGRS grids and S3-backed raster workflows.

freezecore grew out of large-scale glacier mapping, where scattered areas of
interest require several local projections and large raster collections live
in object storage.

The centrepiece of freezecore is **`MGRSGrid`**: a 10 km grid for the UTM-covered
world that gives every MGRS code a dataset-independent target backed by an
[`odc.geo.GeoBox`](https://odc-geo.readthedocs.io/en/latest/intro-geobox.html).
Rasters resampled to the same code and resolution share their CRS, transform,
and shape. See
[The MGRS grid](https://lqgentner.github.io/freezecore/user-guide/mgrs-grid.html)
for the reasoning.

The S3 helpers bridge
[Universal Pathlib](https://universal-pathlib.readthedocs.io/) and
[Rasterio](https://rasterio.readthedocs.io/), so filesystem operations and
GDAL raster I/O use the same per-path credentials and endpoint configuration.

## Installation

Requires Python 3.12 or newer, and [uv](https://docs.astral.sh/uv/) or pip.

freezecore is not published on PyPI yet — install it from GitHub:

```bash
# uv
uv add "freezecore @ git+https://github.com/lqgentner/freezecore.git"

# pip
pip install "freezecore @ git+https://github.com/lqgentner/freezecore.git"
```

Pin a release tag for reproducible environments:

```bash
uv add "freezecore @ git+https://github.com/lqgentner/freezecore.git@v0.1.0"
```

### The `s3` extra

If you want to interact with S3-style object storage, install the optional dependencies `s3fs`, `fsspec`, and `boto3` with:

```bash
uv add "freezecore[s3] @ git+https://github.com/lqgentner/freezecore.git"
```

## Quick start

Build the 10 km grid covering an area of interest:

```python
from shapely import box

from freezecore.mgrs import MGRSGrid

grid = MGRSGrid(box(8.4, 47.3, 8.6, 47.5))  # Zürich, WGS84
gdf = grid.to_geodataframe()                # mgrs_code, zone, epsg, geometry, ...
square = grid[0]                            # an odc.geo GeoBox per grid square
```

Each square is an `MGRSGeoBox` — a subclass of
[`odc.geo.GeoBox`](https://odc-geo.readthedocs.io/en/latest/intro-geobox.html)
carrying the CRS, affine transform, and shape needed to resample any raster onto
it. Reconstruct one from its code alone, without building a grid:

```python
from freezecore.mgrs import MGRSGeoBox

square = MGRSGeoBox.from_mgrs("32TMS35", resolution=10.0)  # 1000 x 1000 px, EPSG:32632
```

Read a raster from local disk or S3 through one call:

```python
from freezecore.raster import rasterio_open
from freezecore.s3 import make_s3_upath

path = make_s3_upath("s3://my-bucket/scene.tif", key=..., secret=...)
with rasterio_open(path) as src:
    data = src.read(1)
```

The credentials travel with the path, so pathlib-like methods (`exists()`, `iterdir()`, `glob()`) and GDAL (the
raster reader) always agree on them. Public buckets need `anon=True`:

```python
tile = "Copernicus_DSM_COG_10_N46_00_E008_00_DEM"
dem_path = make_s3_upath(
    f"s3://copernicus-dem-30m/{tile}/{tile}.tif",
    anon=True,
    region="eu-central-1",
)

```

Download a file to a local directory or a bucket, with a progress bar:

```python
from freezecore.download import HTTPDownloader

download = HTTPDownloader(auth=("user", "pass"))
path = download("https://example.org/data.zip", "cache/")  # -> Path
```

Rewrite a GeoTIFF as a Cloud-Optimized GeoTIFF (local or S3):

```python
from freezecore.raster import COG_PROFILE, rewrite_tiff

rewrite_tiff("in.tif", "out.tif", profile=COG_PROFILE)              # copy by default
rewrite_tiff("in.tif", "out.tif", profile=COG_PROFILE, move=True)   # move
```

## Documentation

Full documentation, including the MGRS grid guide and the S3 raster guide, is at
**<https://lqgentner.github.io/freezecore/>**.

## Support

This is a small internal core library maintained on a best-effort basis. Please
file bugs and questions on the
[issue tracker](https://github.com/lqgentner/freezecore/issues).

## Contributing

```bash
git clone https://github.com/lqgentner/freezecore.git
cd freezecore
uv sync --all-extras
uv run pytest
```

See the [contributing guide](https://lqgentner.github.io/freezecore/user-guide/contributing.html)
for the full checks, the S3 integration tests, and how to build these docs.
