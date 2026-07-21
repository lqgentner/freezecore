# freezecore

Shared geospatial core utilities for glacier-mapping projects.

- `freezecore.mgrs` — MGRS grid helpers (`MGRSGrid`, `MGRSGeoBox`, `mgrs_to_crs`)
- `freezecore.raster` — rasterio helpers with transparent S3 support
  (`rasterio_open`, profile/CRS utilities, `rewrite_tiff`, `merge_tiffs`, `write_cog`)
- `freezecore.vrt` — GDAL VRT generation (`create_decibel_vrt`, `create_rgb_vrt`,
  `build_vrt_mosaic`)
- `freezecore.download` — HTTP download tooling (`HTTPDownloader`,
  `retry_request`) with rich progress and UPath/S3 destinations
- `freezecore.s3` — S3 UPath construction and retry configuration
  (requires the `freezecore[s3]` extra)
- `freezecore.progress` — shared rich progress-bar layout
- `freezecore.vectools`, `freezecore.pandas_utils` — GeoDataFrame/DataFrame helpers
- `freezecore.vectordata` — download-and-cache base class for vector datasets
- `freezecore.utils` — small shared helpers

Extracted from [deepfreezer](https://github.com/lqgentner/deepfreezer) so that
packages like [s1bursts](https://github.com/lqgentner/s1bursts) can be
released on PyPI with a lean dependency set.

## Installation

Requires Python 3.12 or newer.

```bash
pip install freezecore
```

The S3 helpers (`freezecore.s3`, and the credentialed S3 paths used by
`freezecore.raster`) require the optional `s3` extra, which pulls in `s3fs`,
`fsspec`, and `boto3`:

```bash
pip install "freezecore[s3]"
```

## Quick start

Build the MGRS 10 km grid covering an area of interest:

```python
from shapely import box
from freezecore.mgrs import MGRSGrid

grid = MGRSGrid(box(8.4, 47.3, 8.6, 47.5))  # Zürich, WGS84
gdf = grid.to_geodataframe()                # mgrs_code, zone, epsg, geometry, ...
geobox = grid[0]                            # an odc.geo GeoBox per cell
```

Download a file to a local directory or an S3 bucket, with a progress bar:

```python
from freezecore.download import HTTPDownloader

download = HTTPDownloader(auth=("user", "pass"))
path = download("https://example.org/data.zip", "cache/")  # -> Path
```

Rewrite a GeoTIFF to a Cloud-Optimized GeoTIFF (local or S3):

```python
from freezecore.raster import rewrite_tiff, COG_PROFILE

rewrite_tiff("in.tif", "out.tif", profile=COG_PROFILE)  # copy by default
rewrite_tiff("in.tif", "out.tif", profile=COG_PROFILE, move=True)  # move
```

## API stability

`freezecore` is pre-1.0 (`0.x`). The public API may change between minor
versions; breaking changes are called out in [CHANGELOG.md](CHANGELOG.md).
Names prefixed with an underscore are private and may change at any time.

The package ships a `py.typed` marker, so downstream type checkers use its
inline annotations.

## Support

This is a small internal core library maintained on a best-effort basis.
Please file bugs and questions on the
[issue tracker](https://github.com/lqgentner/freezecore/issues).

## Development

Uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync --all-extras
uv run pytest
uv run ruff format && uv run ruff check --fix
uv run mypy src/freezecore
```
