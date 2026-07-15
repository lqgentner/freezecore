"""Utilities for pandas and geopandas."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, overload

if TYPE_CHECKING:
    import geopandas as gpd
    import pandas as pd


@overload
def clean_names(df: gpd.GeoDataFrame, case_type: str = ...) -> gpd.GeoDataFrame: ...
@overload
def clean_names(df: pd.DataFrame, case_type: str = ...) -> pd.DataFrame: ...
def clean_names(
    df: pd.DataFrame | gpd.GeoDataFrame,
    case_type: str = "lower",
) -> pd.DataFrame | gpd.GeoDataFrame:
    """
    Clean DataFrame column names by normalizing whitespace and adjusting case.

    Parameters
    ----------
    df : pd.DataFrame | gpd.GeoDataFrame
        The DataFrame whose column names to clean.
    case_type : str, optional
        How to transform the case of column names. One of:

        - ``"lower"``    : all characters lowercase (default)
        - ``"upper"``    : all characters uppercase
        - ``"snake"``    : CamelCase/camelCase to snake_case
        - ``"preserve"`` : no case change, only spaces replaced

    Returns
    -------
    df : pd.DataFrame | gpd.GeoDataFrame
        A new DataFrame with cleaned column names. The original is not mutated.

    Raises
    ------
    ValueError
        If ``case_type`` is not one of the accepted values.

    Examples
    --------
    >>> import pandas as pd
    >>> df = pd.DataFrame({"Aloha": [1], "Bell Chart": [2], "CamelCase": [3]})
    >>> clean_names(df)
       aloha  bell_chart  camelcase
    0      1           2          3
    >>> clean_names(df, case_type="snake")
       aloha  bell_chart  camel_case
    0      1           2           3
    """

    def to_snake(name: str) -> str:
        name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
        name = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", name)
        return name.lower()

    def transform(name: str) -> str:
        name = str(name).strip()
        name = re.sub(r"\s+", "_", name)
        match case_type:
            case "lower":
                return name.lower()
            case "upper":
                return name.upper()
            case "snake":
                return to_snake(name)
            case "preserve":
                return name
            case _:
                msg = f"Unknown case_type: {case_type!r}"
                raise ValueError(msg)

    return df.rename(columns=transform)
