"""Tests for freezecore.pandas_utils.clean_names."""

from __future__ import annotations

import pandas as pd
import pytest

from freezecore.pandas_utils import clean_names


class TestCleanNames:
    def test_lower(self) -> None:
        df = pd.DataFrame({"Aloha": [1], "Bell Chart": [2]})
        assert list(clean_names(df).columns) == ["aloha", "bell_chart"]

    def test_snake(self) -> None:
        df = pd.DataFrame({"CamelCase": [1]})
        assert list(clean_names(df, case_type="snake").columns) == ["camel_case"]

    def test_preserve(self) -> None:
        df = pd.DataFrame({"Mixed Case": [1]})
        assert list(clean_names(df, case_type="preserve").columns) == ["Mixed_Case"]

    def test_does_not_mutate_input(self) -> None:
        df = pd.DataFrame({"A B": [1]})
        clean_names(df)
        assert list(df.columns) == ["A B"]

    def test_rejects_invalid_case_type_even_for_empty_df(self) -> None:
        # Previously the case_type was only checked while visiting columns, so a
        # zero-column DataFrame silently accepted an invalid case_type.
        with pytest.raises(ValueError, match="Unknown case_type"):
            clean_names(pd.DataFrame(), case_type="bogus")

    def test_rejects_normalization_collision(self) -> None:
        # "A" and "a" both normalize to "a"; pandas would silently drop one.
        df = pd.DataFrame([[1, 2]], columns=["A", "a"])
        with pytest.raises(ValueError, match="map"):
            clean_names(df)
