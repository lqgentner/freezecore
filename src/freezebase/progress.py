"""Shared rich progress-bar layout and helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    ProgressColumn,
    ProgressType,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


def create_progress(
    *,
    show_progress: bool = True,
    add_description: bool = True,
    columns: list[str | ProgressColumn] | None = None,
    **kwargs,
) -> Progress:
    """
    Create a rich progress bar with a custom column layout.

    Parameters
    ----------
    show_progress : bool, default: True
        Whether to display the progress bar. If False, the progress bar
        is created but disabled.
    add_description : bool
        Whether to prepend a text column with the task description to
        the progress bar. Ignored when ``columns`` is provided.
    columns : list of str or ProgressColumn, optional
        Override the default column layout. When set, the columns are
        used as-is and ``add_description`` is ignored.
    **kwargs : Any
        Additional keyword arguments passed to `rich.progress.Progress`.

    Returns
    -------
    Progress
        A configured rich Progress instance.
    """
    if columns is None:
        columns = (
            [TextColumn("[progress.description]{task.description}")] if add_description else []
        )
        columns.extend(
            [
                BarColumn(),
                TaskProgressColumn(),
                "•",
                MofNCompleteColumn(),
                "•",
                TimeElapsedColumn(),
                "•",
                TimeRemainingColumn(),
            ],
        )

    return Progress(*columns, disable=(not show_progress), **kwargs)


def track_progress(
    sequence: Iterable[ProgressType],
    description: str = "Working...",
    *,
    total: float | None = None,
    completed: int = 0,
    update_period: float = 0.1,
    show_progress: bool = True,
    **progress_kwargs,
) -> Iterable[ProgressType]:
    """
    Track progress by iterating over a sequence.

    Wraps `rich.progress.Progress.track` with the standard column layout
    from `create_progress`.

    Parameters
    ----------
    sequence : Iterable[ProgressType]
        The iterable to track progress over.
    description : str, default: "Working..."
        Label displayed alongside the progress bar.
    total : float or None, default: None
        Total number of steps. If None, the length of `sequence` is used
        when available.
    completed : int, default: 0
        Number of steps already completed at the start.
    update_period : float, default: 0.1
        Minimum time in seconds between progress bar updates.
    show_progress : bool, default: True
        Whether to display the progress bar.
    **progress_kwargs : Any
        Additional keyword arguments passed to `rich.progress.Progress`.

    Yields
    ------
    ProgressType
        Items from `sequence`.
    """
    progress = create_progress(
        show_progress=show_progress,
        add_description=bool(description),
        **progress_kwargs,
    )

    with progress:
        yield from progress.track(
            sequence,
            total=total,
            completed=completed,
            description=description,
            update_period=update_period,
        )
