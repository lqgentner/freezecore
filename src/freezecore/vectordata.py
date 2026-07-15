"""Download-and-cache base classes for geospatial vector datasets."""

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
import logging
from pathlib import Path
import threading

import geopandas as gpd
import pandas as pd

from freezecore.download import HTTPDownloader
from freezecore.utils import get_cache_dir
from freezecore.vectools import save_and_read_parquet

logger = logging.getLogger(__name__)

_path_locks: dict[Path, threading.Lock] = {}
_path_locks_mutex = threading.Lock()


def _get_path_lock(path: Path) -> threading.Lock:
    with _path_locks_mutex:
        return _path_locks.setdefault(path, threading.Lock())


@dataclass(frozen=True)
class DatasetMetadata:
    """Metadata container for dataset attribution and licensing."""

    name: str
    source_url: str
    attribution: str
    license: str | None = None
    license_url: str | None = None
    version: str | None = None
    description: str | None = None
    doi: str | None = None
    # Catch-all for additional fields (specific to subclass)
    additional_fields: dict[str, str] = field(default_factory=dict)

    def to_display_dict(self) -> dict[str, str]:
        """Get all fields for display purposes."""
        # Standard fields
        standard = asdict(self)
        standard.pop("additional_fields")  # Remove the additional_fields dict

        # Add additional fields
        for k, v in self.additional_fields.items():
            standard[k] = v

        return {k: v for k, v in standard.items() if v is not None}


class GeoVectorData(ABC):
    """Abstract class for datasets containing geospatial vector data."""

    def __init__(self, cache_dir: str | Path | None = None) -> None:
        """
        Initialize the dataset.

        Parameters
        ----------
        cache_dir : str or Path or None, default: None
            The root directory where the dataset is stored. Defaults to the 'FREEZECORE_CACHE'
            environment variable or the system cache directory (in that order).

        """
        self.cache_dir = get_cache_dir(cache_dir)
        self._verified: bool = False

    @property
    @abstractmethod
    def metadata(self) -> DatasetMetadata:
        """Metadata container for dataset attribution and licensing."""

    @property
    @abstractmethod
    def raw_path(self) -> Path:
        """Path to the raw downloaded data."""

    @property
    @abstractmethod
    def processed_path(self) -> Path:
        """Path to the processed data."""

    def _prepare(self) -> None:
        """
        Process the raw data and save as GeoParquet.

        Overwrite this method to implement additional processing steps.
        """
        logger.info(
            "Processing data and saving '%s' to '%s'.",
            self.processed_path.name,
            self.processed_path.parent,
        )
        # Open downloaded file
        data = gpd.read_file(self.raw_path)
        # Save as GeoParquet
        save_and_read_parquet(data, self.processed_path)

    def _download(self) -> None:
        """
        Download the dataset.

        Overwrite this method to implement custom downloading logic.
        """
        url = self.metadata.source_url
        save_dir = self.raw_path.parent
        filename = self.raw_path.name

        downloader = HTTPDownloader()
        downloader(url=url, save_dir=save_dir, filename=filename)

    def get_data(self, *, download: bool = False) -> gpd.GeoDataFrame:
        """Return the processed data, preparing it if necessary."""
        if not self._verified:
            self._verify(download=download)
        return self._load_data()

    def remove(self, *, raw: bool = True, processed: bool = True) -> None:
        """
        Remove raw and/or processed dataset files.

        Overwrite this method if the raw or processed paths are directories
        (e.g., an extracted ZIP) instead of single files.
        """

        def _remove_file_and_cleanup_dir(path: Path) -> None:
            if path.exists():
                path.unlink()
                # Remove directory if empty
                if not any(path.parent.iterdir()):
                    path.parent.rmdir()

        if raw:
            _remove_file_and_cleanup_dir(self.raw_path)
        if processed:
            _remove_file_and_cleanup_dir(self.processed_path)

    def _load_data(self) -> gpd.GeoDataFrame:
        """Return the GeoDataFrame."""
        if self.processed_path.suffix == ".parquet":
            # Read GeoParquet
            gdf = gpd.read_parquet(self.processed_path)
        else:
            # Assume Shapefile or GeoPackage
            gdf = gpd.read_file(self.processed_path)
        return gdf

    def _verify(self, *, download: bool) -> None:
        """
        Verify the integrity of the dataset.

        Download and prepare the dataset if specified by the user.
        """
        if self.processed_path.exists():
            self._verified = True
            return
        with _get_path_lock(self.processed_path):
            # Re-check: another thread may have finished while we waited for the lock
            if self.processed_path.exists():
                self._verified = True
                return
            if self.raw_path.exists():
                self._prepare()
            elif download:
                self._download()
                self._prepare()
            else:
                msg = "Dataset not found. Set `download=True` to automatically download."
                raise FileNotFoundError(msg)
            self._verified = True

    def __repr__(self) -> str:
        """Return the technical string representation."""
        return (
            self.__class__.__name__
            + "("
            + ", ".join(f"{k}={v}" for k, v in self.metadata.additional_fields.items())
            + ")"
        )

    def _repr_html_(self) -> str:
        """Return the HTML representation for Jupyter notebooks."""
        meta_dict = self.metadata.to_display_dict()
        df_metadata = pd.DataFrame.from_dict(meta_dict, orient="index", columns=["Value"])
        table_html = df_metadata.to_html(header=False, justify="left", render_links=True)

        # Wrap header and table in one container with fit-content width
        return f"""
        <div class='data-container'>
            <div class='data-header'>{type(self).__module__}.{type(self).__name__}</div>
            {table_html}
        </div>
        <style>
        .data-container {{
            font-family: sans-serif;
            width: fit-content;

        }}
        .data-header {{
            padding: 6px 0 6px 3px;
            color: #888;
            margin-bottom: 2px;
            border-bottom: 1px solid #555;
        }}
            .data-container table td,
            .data-container table th {{
            text-align: left;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 540px;
        }}
        </style>
        """
