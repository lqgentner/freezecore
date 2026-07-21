# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the project is pre-1.0 (`0.x`), minor releases may contain breaking changes.

## [Unreleased]

### Added

- `py.typed` marker so downstream type checkers use the inline annotations.
- Optional `DatasetMetadata.sha256` to verify a raw download against a known
  hash (`freezecore.vectordata`).
- `freezecore.utils.file_sha256` helper.
- Packaging metadata: project URLs, keywords, and classifiers.
- GitHub Actions CI (lint, type-check, test matrix on 3.12/3.13, a
  lowest-bound dependency job, a MinIO-backed S3 integration job, and a build +
  wheel smoke-test) and a Trusted-Publishing release workflow.
- S3 integration tests (`tests/test_s3_integration.py`, `integration` marker),
  skipped unless `FREEZECORE_TEST_S3_*` is set.

### Changed

- Dependency lower bounds corrected to the oldest versions that actually
  install and work on Python 3.12: notably `numpy>=2.0` (code uses `np.concat`),
  `shapely>=2.1.0` (`transform(interleaved=...)`), `pyarrow>=17.0` (NumPy 2 ABI),
  `pyproj>=3.6.1`, `boto3>=1.36`, and `s3fs>=2026.2.0`/`fsspec>=2026.2.0`
  (`set_custom_error_handler`).
- Licensing metadata modernized to PEP 639 (`license = "MIT"` +
  `license-files`), and the sdist no longer ships `.python-version`/`uv.lock`.

### Changed

- **Breaking:** `GeoVectorData.remove()` is renamed to `cleanup()` and now
  defaults to removing only the raw download (`raw=True, processed=False`),
  keeping the processed data.
- **Breaking:** `rewrite_tiff()` no longer deletes the source by default; pass
  `move=True` for the previous move semantics.
- `HTTPDownloader.__call__` gained an `overwrite` keyword (default `False`) and
  now rejects unsafe/inferred filenames that would escape the destination.
- S3 transient-retry codes narrowed so a permanent `AccessDenied`/403 is no
  longer retried.

### Fixed

- Filename confinement and redirect credential handling in the downloader.
- Destination/source preservation on failure in `rewrite_tiff`.
- Numerous MGRS/UTM/CRS validation and parsing defects.
- VRT/merge input validation and XML-safe VRT generation.
- Z-coordinate detection across polygon interior rings and mixed collections.
- Atomic cache writes and verification-state reset on removal.
