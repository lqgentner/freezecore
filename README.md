# freezecore

Shared geospatial core utilities for glacier-mapping projects.

freezecore is the common base extracted from
[deepfreezer](https://github.com/lqgentner/deepfreezer), so that packages like
[s1bursts](https://github.com/lqgentner/s1bursts) can depend on a small, stable
set of helpers instead of re-implementing them.

Its centrepiece is **`MGRSGrid`**: a 10 km MGRS grid that gives every project a
single, dataset-independent target to resample onto, so rasters from different
sources stack without pairwise alignment. See
[The MGRS grid](https://lqgentner.github.io/freezecore/user-guide/mgrs-grid.html)
for the reasoning.

## Installation

Requires Python 3.12 or newer, and [uv](https://docs.astral.sh/uv/) or pip.

freezecore is not published on PyPI — install it from GitHub:

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

`freezecore.s3` and the credentialed S3 paths used by `freezecore.raster` need
`s3fs`, `fsspec`, and `boto3`. They are optional and lazily imported, so the base
install stays lean:

```bash
uv add "freezecore[s3] @ git+https://github.com/lqgentner/freezecore.git"
```

## Modules

| Module | Contents |
|---|---|
| `freezecore.mgrs` | MGRS grid squares — `MGRSGrid`, `MGRSGeoBox`, `mgrs_to_crs` |
| `freezecore.raster` | rasterio helpers with transparent S3 support — `rasterio_open`, `rewrite_tiff`, `merge_tiffs`, `write_cog` |
| `freezecore.vrt` | GDAL VRT generation — `create_decibel_vrt`, `create_rgb_vrt`, `build_vrt_mosaic` |
| `freezecore.download` | HTTP downloads with retries and progress — `HTTPDownloader`, `retry_request` |
| `freezecore.s3` | S3 `UPath` construction and retry policy (needs the `s3` extra) |
| `freezecore.vectordata` | Download-and-cache base class for vector datasets |
| `freezecore.vectools`, `freezecore.pandas_utils` | GeoDataFrame / DataFrame helpers |
| `freezecore.progress`, `freezecore.utils` | Shared progress-bar layout and small helpers |

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

## API stability

freezecore is pre-1.0 (`0.x`). The public API may change between minor versions;
breaking changes are called out in the
[changelog](https://github.com/lqgentner/freezecore/blob/main/CHANGELOG.md). Names prefixed
with an underscore are private and may change at any time.

The package ships a `py.typed` marker, so downstream type checkers use its inline
annotations.

## Support

This is a small internal core library maintained on a best-effort basis. Please
file bugs and questions on the
[issue tracker](https://github.com/lqgentner/freezecore/issues).

## Development

Uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync --all-extras
uv run pytest
uv run ruff format && uv run ruff check --fix
uv run mypy src/freezecore
```

### Building the docs

The documentation is built with [Great Docs](https://posit-dev.github.io/great-docs/),
which renders through [Quarto](https://quarto.org/docs/get-started/) — install
Quarto separately, then:

```bash
uv sync --group docs
uv run great-docs build      # writes great-docs/_site/
uv run great-docs preview    # live-reloading local server
```

The user guide executes its code at build time, reading a public S3 bucket and
fetching basemap tiles. Those outputs are cached in the tracked `_freeze/`
directory, so a page is only re-executed when its own `.qmd` changes — an edit
to the README or a docstring rebuilds without touching the network.

To force a refresh after changing library behaviour rather than page source:

```bash
uv run great-docs freeze --info                       # what is cached and stale
uv run great-docs freeze user_guide/01-mgrs-grid.qmd  # re-execute one page
git add _freeze/                                      # commit the new outputs
```
