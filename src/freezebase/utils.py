"""Small shared helpers: optional dependencies, directories, strings, credentials."""

from __future__ import annotations

from functools import wraps
import hashlib
from importlib.util import find_spec
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from platformdirs import user_cache_dir

if TYPE_CHECKING:
    from collections.abc import Callable

EPSG_WGS84 = 4326

logger_ = logging.getLogger(__name__)


def depends_on_optional[**P, T](
    module_name: str,
    install_hint: str | None = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Check if an optional dependency is installed.

    Parameters
    ----------
    module_name : str
        The name of the optional module to check for.
    install_hint : str or None, optional
        Custom install instruction appended to the error message.
        If ``None``, a generic message is used.

    Returns
    -------
    Callable[[Callable[P, T]], Callable[P, T]]
        A decorator that wraps a function and raises ``ImportError``
        if the specified module is not installed.

    Raises
    ------
    ImportError
        If the optional dependency is not found when the decorated
        function is called.
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            try:
                spec = find_spec(module_name)
            except (ModuleNotFoundError, ValueError):
                spec = None
            if spec is None:
                hint = f" Install with: {install_hint}" if install_hint else ""
                msg = f"The package '{module_name}' is required for '{func.__name__}()'.{hint}"
                raise ImportError(msg)
            return func(*args, **kwargs)

        return wrapper

    return decorator


def get_cache_dir(cache_dir: str | Path | None = None) -> Path:
    r"""
    Get cache directory with fallback to system cache.

    Determines the cache directory to use based on the following priority:
    1. Provided `cache_dir` parameter
    2. 'FREEZEBASE_CACHE' environment variable
    3. System cache directory (via platformdirs)

    Parameters
    ----------
    cache_dir : str, Path, or None, default: None
        Path to cache directory. If None, will check the environment
        variables and fall back to the system cache directory.

    Returns
    -------
    Path
        Path to the cache directory to use.

    Notes
    -----
    The system cache location varies by platform:

    - Linux: ~/.cache/freezebase
    - macOS: ~/Library/Caches/freezebase
    - Windows: %LOCALAPPDATA%\\freezebase\\Cache
    """
    cache_dir = cache_dir or os.getenv("FREEZEBASE_CACHE")
    if cache_dir:
        return Path(cache_dir).expanduser()

    # Fallback to system cache
    system_cache = user_cache_dir("freezebase")
    logger_.warning(
        "Using system cache directory: '%s' "
        "Set 'FREEZEBASE_CACHE' environment variable or pass `cache_dir` parameter "
        "to customize location.",
        system_cache,
    )
    return Path(system_cache)


def get_data_dir(data_dir: str | Path | None = None) -> Path:
    """
    Get data directory - must be explicitly provided.

    Determines the data directory to use for large datasets based on:
    1. Provided `data_dir` parameter
    2. 'FREEZEBASE_DATA' environment variable

    Parameters
    ----------
    data_dir : str, Path, or None, default: None
        Path to data directory. If None, will check the environment variables.

    Returns
    -------
    Path
        Path to the data directory to use.

    Raises
    ------
    ValueError
        If neither the data_dir parameter nor an environment variable
        is provided.

    """
    data_dir = data_dir or os.getenv("FREEZEBASE_DATA")
    if data_dir:
        return Path(data_dir).expanduser()
    msg = (
        "Data directory must be provided via 'data_dir' parameter "
        "or 'FREEZEBASE_DATA' environment variable"
    )
    raise ValueError(msg)


def shorten_string(string: str, n: int) -> str:
    """
    Shorten a string to length `n` with an ellipsis in the middle if needed.

    Parameters
    ----------
    string : str
        The string to shorten.
    n : int
        Maximum length of the returned string, including the ellipsis. Values
        below zero are treated as zero.

    Returns
    -------
    str
        The original string if its length is <= `n`, otherwise a shortened
        version with ``...`` inserted in the middle. The result never exceeds
        `n` characters. When `n` is too small to hold the ``...`` marker, the
        string is hard-truncated to `n` characters without a marker.
    """
    n = max(n, 0)
    if len(string) <= n:
        return string
    ellipsis_ = "..."
    if n <= len(ellipsis_):
        # No room for the marker; hard-truncate to satisfy the length contract.
        return string[:n]
    budget = n - len(ellipsis_)
    n_1 = budget // 2 + budget % 2
    n_2 = budget // 2
    return string[:n_1] + ellipsis_ + string[len(string) - n_2 :]


def get_credentials_from_env(username_key: str, password_key: str) -> tuple[str, str]:
    """
    Retrieve username and password credentials from environment variables.

    Parameters
    ----------
    username_key : str
        The environment variable name for the username
    password_key : str
        The environment variable name for the password

    Returns
    -------
    tuple[str, str]
        A tuple of (username, password)

    Raises
    ------
    KeyError
        If either credential is missing or empty.

    """
    username = os.getenv(username_key)
    password = os.getenv(password_key)

    # Treat empty strings as missing: an empty credential is never usable.
    if not username or not password:
        missing_keys = [
            key for key, value in ((username_key, username), (password_key, password)) if not value
        ]
        msg = f"Environment variables not set or empty: {', '.join(missing_keys)}"
        raise KeyError(msg)

    return username, password


_HASH_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def file_sha256(path: str | Path, *, chunk_size: int = _HASH_CHUNK_SIZE) -> str:
    """Compute the SHA-256 hex digest of a file, reading it in chunks.

    Parameters
    ----------
    path : str or Path
        File to hash.
    chunk_size : int, optional
        Number of bytes to read per iteration. Defaults to 1 MiB.

    Returns
    -------
    str
        The lowercase hexadecimal SHA-256 digest.
    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def format_valid_options(d: dict[Any, Any]) -> str:
    r"""
    Format the key-value pairs of a dictionary as a bullet list for error messages.

    Parameters
    ----------
    d : dict
        The dictionary whose items will be formatted as valid options.

    Returns
    -------
    str
        A string representing the dictionary items as a bullet list,
        suitable for inclusion in error messages about valid argument values.

    Examples
    --------
    >>> allowed = {"csv": "Comma-separated values", "json": "JavaScript Object Notation"}
    >>> print(format_valid_options(allowed))
    - 'csv':  Comma-separated values
    - 'json': JavaScript Object Notation

    """
    max_key_length = max(len(str(k)) for k in d)
    items = [f"- '{k}':{' ' * (max_key_length - len(str(k)) + 1)}{v}" for k, v in d.items()]
    return "\n".join(items)
