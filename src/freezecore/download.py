"""HTTP download tooling: retry helpers and the HTTPDownloader."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
import logging
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, TypeVar, overload
from urllib.parse import unquote, urljoin, urlparse

import requests
from rich.progress import (
    BarColumn,
    DownloadColumn,
    ProgressColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
import tenacity

from freezecore.progress import create_progress
from freezecore.utils import shorten_string

if TYPE_CHECKING:
    from collections.abc import Iterable

    from requests.auth import AuthBase
    from upath import UPath

DEFAULT_TIMEOUT = 30
CHUNK_SIZE = 1024 * 1024  # 1 MiB
REMOTE_BLOCK_SIZE = 64 * 1024 * 1024  # 64 MiB

logger = logging.getLogger(__name__)

# HTTP status codes considered transient and worth retrying.
TRANSIENT_HTTP_STATUS_CODES = frozenset({408, 429, 502, 503, 504})

# Return type for retry_request
WrappedFn = TypeVar("WrappedFn", bound=Callable[..., Any])

# Byte-oriented progress bar layout for HTTP downloads.
_DOWNLOAD_COLUMNS: list[str | ProgressColumn] = [
    TextColumn("{task.fields[filename]}"),
    BarColumn(),
    TaskProgressColumn(),
    "•",
    DownloadColumn(),
    "•",
    TransferSpeedColumn(),
    "•",
    TimeElapsedColumn(),
    "•",
    TimeRemainingColumn(),
]


def _is_transient_request_error(
    exception: BaseException,
    *,
    extra_status_codes: frozenset[int] = frozenset(),
) -> bool:
    """Check whether an exception raised by `requests` is worth retrying."""
    if isinstance(exception, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return True
    if isinstance(exception, requests.exceptions.HTTPError):
        response = exception.response
        return response is not None and (
            response.status_code in TRANSIENT_HTTP_STATUS_CODES
            or response.status_code in extra_status_codes
        )
    return False


def retry_request(
    logger: logging.Logger,
    *,
    extra_status_codes: frozenset[int] = frozenset(),
) -> Callable[[WrappedFn], WrappedFn]:
    """
    Create a `tenacity` retry decorator for HTTP requests using the `requests` library.

    This decorator will automatically retry functions that make HTTP requests
    when they encounter transient network or server-side errors. It is a
    pre-configured `tenacity.retry` function with the following behaviors:

    - ``reraise=True`` to see encountered exception at the end of the stack trace
    - Retries ``ConnectionError`` and ``Timeout`` errors of the ``requests``
      library, as well as HTTP Errors 408, 429, 502, 503, 504 (plus any status
      codes passed via ``extra_status_codes``).
    - Maximum attempts: 3
    - Wait strategy: Exponential backoff with jitter (the latter for resolving
      contention between multiple processes)

    Parameters
    ----------
    logger : logging.Logger
        Logger instance used to log retry attempts before each sleep.
    extra_status_codes : frozenset of int, optional
        Additional HTTP status codes to treat as transient for this call site,
        on top of the codes in ``TRANSIENT_HTTP_STATUS_CODES``. Use this rather
        than widening ``TRANSIENT_HTTP_STATUS_CODES`` itself when a status code
        (e.g. 500) is only known to be transient for one particular endpoint.

    Returns
    -------
    Callable[[WrappedFn], WrappedFn]
        A tenacity retry decorator configured for HTTP request retries.
    """
    return tenacity.retry(
        reraise=True,
        stop=tenacity.stop_after_attempt(3),
        wait=tenacity.wait_exponential(multiplier=1, min=4, max=10) + tenacity.wait_random(0, 2),
        retry=tenacity.retry_if_exception(
            partial(_is_transient_request_error, extra_status_codes=extra_status_codes),
        ),
        before_sleep=tenacity.before_sleep_log(logger, logging.INFO),
    )


class HTTPDownloader:
    """
    Download manager for fetching files over HTTP/HTTPS.

    Built upon `requests`. Inspired by `pooch.HTTPDownloader`.
    Supports downloading with GET and POST requests.
    """

    def __init__(
        self,
        *,
        auth: tuple[str, str] | AuthBase | None = None,
        trusted_hosts: str | Iterable[str] | None = None,
        progress: bool = True,
        **kwargs,
    ) -> None:
        """
        Initialize an HTTPDownloader instance.

        Parameters
        ----------
        auth : tuple[str, str] or instance of AuthBase subclass, optional
            HTTP authentication object (default is None). For HTTP Basic Authentication,
            provide `(user, pass)` tuple
        trusted_hosts : str or iterable of str, optional
            Hostnames for which auth should be preserved during redirects. If not specified,
            auth is only sent to the original host.
        progress : bool
            If True, show a progress bar during download.
        **kwargs : dict[str, Any]
            Keyword arguments that will be passed to `requests.request`.

        """
        self.session = requests.Session()
        if auth is not None:
            # Handle redirects manually to allow for auth preservation
            kwargs.setdefault("allow_redirects", False)
            self.session.auth = auth
        if trusted_hosts is None:
            trusted_hosts = []
        elif isinstance(trusted_hosts, str):
            trusted_hosts = [trusted_hosts]
        self.trusted_hosts = trusted_hosts
        # Set defaults for requests.request() kwargs
        kwargs.setdefault("method", "GET")
        kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
        kwargs.setdefault("stream", True)
        self.kwargs = kwargs
        self.show_progress = progress

    @overload
    def __call__(
        self,
        url: str,
        save_dir: str | Path,
        filename: str | None = None,
    ) -> Path: ...
    @overload
    def __call__(
        self,
        url: str,
        save_dir: UPath,
        filename: str | None = None,
    ) -> UPath: ...
    @retry_request(logger=logger)
    def __call__(
        self,
        url: str,
        save_dir: str | Path | UPath,
        filename: str | None = None,
    ) -> Path | UPath:
        """
        Download a file from a URL to a directory with optional progress bar.

        Supports both local paths and remote paths (e.g. UPath for S3).

        Parameters
        ----------
        url : str
            The URL of the file to download.
        save_dir : str, Path, or UPath
            The directory to save the downloaded file. Can be a local path
            or a remote UPath (e.g. S3).
        filename : str, optional
            The filename of the downloaded file.
            If not provided, the filename will be inferred from the HTML header or URL.

        Returns
        -------
        Path or UPath
            The path of the downloaded file.

        """
        response = self._follow_redirects(url)
        response.raise_for_status()

        if not _is_downloadable_content(response):
            msg = (
                f"No downloadable file found for URL: '{url}'. "
                "Make sure the authentication is correct."
            )
            raise RuntimeError(msg)

        if not filename:
            cd = response.headers.get("Content-Disposition")
            filename = _extract_filename_from_cd(cd) or _extract_filename_from_url(url)
            if not filename:
                msg = "Could not infer filename. Please specify with `filename=` argument."
                raise RuntimeError(msg)

        if isinstance(save_dir, str):
            save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        filepath = save_dir / filename
        logger.info("Downloading '%s' from '%s' to '%s'.", filename, url, str(save_dir))
        return _write_file(response, filepath, show_progress=self.show_progress)

    def _follow_redirects(self, url: str) -> requests.Response:
        """Follow redirects, dropping auth when leaving trusted hosts."""
        with self.session as session:
            response = session.request(url=url, **self.kwargs)
            if not response.is_redirect:
                return response
            location = response.headers["Location"]
            new_url = urljoin(response.url, location)
            new_host = urlparse(new_url).hostname
            prev_host = urlparse(response.url).hostname
            if new_host is None:
                msg = "Hostname not found in redirect Location header."
                raise RuntimeError(msg)

            is_trusted = new_host == prev_host or new_host in self.trusted_hosts
            if not is_trusted:
                self.session.auth = None
            return self._follow_redirects(new_url)


def _is_downloadable_content(response: requests.Response) -> bool:
    """Check if a file is downloadable."""
    cd = response.headers.get("Content-Disposition")
    if cd:
        # File is always downloadable if Content-Disposition exists
        return True
    content_type = response.headers.get("Content-Type", "").lower()
    # Common downloadable MIME types
    downloadable_types = [
        "application/",
        "audio/",
        "video/",
        "image/",
        "text/csv",
        "text/plain",
    ]
    return any(content_type.startswith(mime) for mime in downloadable_types)


def _get_filesize(response: requests.Response) -> float | None:
    """Get the filesize in bytes."""
    total = response.headers.get("content-length")
    if total is None:
        return total
    return float(total)


def _write_file[T: Path | UPath](
    response: requests.Response,
    filepath: T,
    *,
    show_progress: bool = True,
) -> T:
    """
    Stream a response body to a file with an optional rich progress bar.

    Local destinations stream to a sibling ``.partial`` file and rename
    on success. Remote destinations (e.g. ``UPath`` on S3) write directly
    to the final path with an increased fsspec ``block_size``.

    """
    filename = shorten_string(filepath.name, 30)
    progress = create_progress(show_progress=show_progress, columns=_DOWNLOAD_COLUMNS)
    total = _get_filesize(response)

    # `UPath("/tmp/x")` is a Path subclass (PosixUPath), `UPath("s3://...")` is not,
    # so isinstance(_, Path) separates local from remote.
    if isinstance(filepath, Path):
        partial_filepath = filepath.with_suffix(filepath.suffix + ".partial")
        try:
            with progress:
                task_id = progress.add_task("Download", filename=filename, total=total)
                with partial_filepath.open("wb") as f:
                    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                        f.write(chunk)
                        progress.update(task_id, advance=len(chunk))
                progress.update(task_id, refresh=True)
            partial_filepath.rename(str(filepath))
        except BaseException:
            partial_filepath.unlink(missing_ok=True)
            raise
        return filepath

    with progress:
        task_id = progress.add_task("Download", filename=filename, total=total)
        with filepath.open("wb", block_size=REMOTE_BLOCK_SIZE) as f:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                f.write(chunk)
                progress.update(task_id, advance=len(chunk))
        progress.update(task_id, refresh=True)
    return filepath


def _extract_filename_from_cd(cd: str | None) -> str | None:
    """
    Extract the filename from the Content-Disposition HTML headers field.

    Handles both RFC 5987 encoded filename* and plain filename parameters,
    preferring filename* when both are present.
    """
    if not cd:
        return None

    # RFC 5987: filename*=charset'language'encoded-value (e.g. UTF-8''name.zip)
    rfc5987_match = re.search(r"filename\*=([^']+)'[^']*'([^;\s]+)", cd, re.IGNORECASE)
    if rfc5987_match:
        return rfc5987_match.group(2)

    # Plain filename= with optional quotes
    plain_match = re.search(r'filename="([^"]+)"|filename=([^;\s]+)', cd, re.IGNORECASE)
    if plain_match:
        return plain_match.group(1) or plain_match.group(2)

    return None


def _extract_filename_from_url(
    url: str | None,
) -> None | str:
    """Extract the filename from an URL."""
    if not url:
        return None
    path = unquote(urlparse(url).path)
    filename = path.split("/")[-1]
    # Only return if it has extension
    if "." not in filename:
        return None
    return filename
