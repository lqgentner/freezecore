"""Tests for freezecore.vectordata cache lifecycle."""

from __future__ import annotations

from typing import TYPE_CHECKING

import geopandas as gpd
import pytest
import shapely

from freezecore.utils import file_sha256
from freezecore.vectordata import (
    DatasetMetadata,
    GeoVectorData,
    _get_path_lock,
    _path_locks,
)

if TYPE_CHECKING:
    from pathlib import Path


class _FakeDataset(GeoVectorData):
    """Minimal concrete dataset backed by local files under the cache dir."""

    #: Optional expected raw hash, surfaced through metadata for checksum tests.
    sha256: str | None = None

    @property
    def metadata(self) -> DatasetMetadata:
        return DatasetMetadata(
            name="fake",
            source_url="https://example.invalid/fake.geojson",
            attribution="test",
            sha256=self.sha256,
        )

    @property
    def raw_path(self) -> Path:
        return self.cache_dir / "raw.geojson"

    @property
    def processed_path(self) -> Path:
        return self.cache_dir / "processed.parquet"


@pytest.fixture
def dataset(tmp_path: Path) -> _FakeDataset:
    ds = _FakeDataset(cache_dir=tmp_path)
    gdf = gpd.GeoDataFrame({"geometry": [shapely.Point(0, 0)]}, crs="EPSG:4326")
    gdf.to_file(ds.raw_path, driver="GeoJSON")
    return ds


class TestCleanupResetsVerification:
    def test_get_data_after_full_wipe_reverifies(self, dataset: _FakeDataset) -> None:
        # Prime the cache: processed file is created and _verified becomes True.
        dataset.get_data()
        assert dataset.processed_path.exists()
        assert dataset._verified is True

        # Removing the processed file must invalidate the cached verification,
        # otherwise a later get_data() would try to read a deleted file.
        dataset.cleanup(raw=True, processed=True)
        assert dataset._verified is False

        with pytest.raises(FileNotFoundError):
            dataset.get_data(download=False)

    def test_remove_processed_only_resets_flag(self, dataset: _FakeDataset) -> None:
        dataset.get_data()
        assert dataset._verified is True

        dataset.cleanup(raw=False, processed=True)
        assert dataset._verified is False
        # The raw file survives, so a re-verify can re-prepare without download.
        assert dataset.raw_path.exists()
        regated = dataset.get_data(download=False)
        assert len(regated) == 1


class TestChecksumVerification:
    def test_matching_checksum_passes(self, dataset: _FakeDataset) -> None:
        dataset.sha256 = file_sha256(dataset.raw_path)
        # Should prepare without complaint.
        assert len(dataset.get_data(download=False)) == 1

    def test_mismatched_checksum_raises(self, dataset: _FakeDataset) -> None:
        dataset.sha256 = "0" * 64  # deliberately wrong
        with pytest.raises(ValueError, match="Checksum mismatch"):
            dataset.get_data(download=False)
        # A failed verification must not leave a processed file behind.
        assert not dataset.processed_path.exists()

    def test_no_checksum_is_noop(self, dataset: _FakeDataset) -> None:
        assert dataset.sha256 is None
        assert len(dataset.get_data(download=False)) == 1


class TestCleanupDefaults:
    def test_default_removes_raw_keeps_processed(self, dataset: _FakeDataset) -> None:
        dataset.get_data()
        assert dataset.raw_path.exists()

        dataset.cleanup()  # defaults: raw=True, processed=False

        assert not dataset.raw_path.exists()
        assert dataset.processed_path.exists()
        # Processed data is still valid, so verification stays primed.
        assert dataset._verified is True
        assert len(dataset.get_data(download=False)) == 1


class TestPathLock:
    def test_aliased_paths_share_one_lock(self, tmp_path: Path) -> None:
        direct = tmp_path / "sub" / "data.parquet"
        direct.parent.mkdir()
        aliased = tmp_path / "sub" / ".." / "sub" / "data.parquet"
        # Different Path spellings of the same file must map to the same lock.
        assert _get_path_lock(direct) is _get_path_lock(aliased)

    def test_registry_self_cleans(self, tmp_path: Path) -> None:
        path = tmp_path / "ephemeral.parquet"
        assert _get_path_lock(path) is not None
        # With no strong reference held, the weak registry drops the entry.
        assert path.resolve() not in _path_locks
