# freezecore

Shared geospatial core utilities for glacier-mapping projects:

- `freezecore.mgrs` — MGRS grid helpers (`MGRSGrid`, `MGRSGeoBox`, `mgrs_to_crs`)
- `freezecore.raster` — rasterio helpers with transparent S3 support
  (`rasterio_open`, profile/CRS utilities, `rewrite_tiff`, `merge_tiffs`)
- `freezecore.download` — HTTP download tooling (`HTTPDownloader`,
  `retry_request`) with rich progress and UPath/S3 destinations
- `freezecore.s3` — S3 UPath construction and retry configuration
  (requires the `freezecore[s3]` extra)
- `freezecore.progress` — shared rich progress-bar layout
- `freezecore.vectools` — GeoDataFrame helpers
- `freezecore.vectordata` — download-and-cache base class for vector datasets
- `freezecore.pandas_utils`, `freezecore.utils` — small shared helpers

Extracted from [deepfreezer](https://github.com/lqgentner/deepfreezer) so that
packages like [s1bursts](https://github.com/lqgentner/s1bursts) can be
released on PyPI with a lean, wheel-only dependency set (no GDAL).

## Development

Uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync --all-extras
uv run pytest
uv run ruff format && uv run ruff check --fix
uv run dmypy run src/freezecore
```
