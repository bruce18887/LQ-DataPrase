"""Backward-compatible re-exports.

This module used to contain all Gage R&R Excel layout logic in a single
1200-line file. It has been split into three focused modules:

- ``gage_styles``      – constants and style factories
- ``gage_summary_builder``  – summary + per-file sheet builders
- ``gage_legacy_builder``   – the original monolithic ``build_gage_summary_excel``

All public names are re-exported here so existing imports keep working.
"""

from .gage_styles import (  # noqa: F401
    NON_NUMERIC_KEYWORDS,
    FILL_GRAY_HEX,
    FILL_LIGHT_BLUE_HEX,
    make_info_label_style,
    make_info_value_style,
    make_warning_style,
    make_good_rate_style,
    make_bad_rate_style,
    make_rr_pct_style,
    make_red_rr_pct_style,
    _set_cell,
)

from .gage_summary_builder import (  # noqa: F401
    build_summary_sheet,
    build_per_file_sheets,
)

from .gage_legacy_builder import build_gage_summary_excel  # noqa: F401
