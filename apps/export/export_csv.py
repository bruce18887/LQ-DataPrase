"""CSV export functions."""

import pandas as pd
from typing import Dict
from apps.analysis.services.statistics import (
    ensure_numeric, get_bin_column_name, get_site_column,
)


def _convert_to_native_type(val):
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (ValueError, TypeError):
        pass
    if isinstance(val, (bool,)):
        return val
    if isinstance(val, (int,)):
        return int(val) if hasattr(val, 'item') else val
    if isinstance(val, (float,)):
        if hasattr(val, 'item'):
            native = val.item()
        else:
            native = val
        if pd.isna(native):
            return ""
        return native
    if hasattr(val, 'item'):
        native = val.item()
        try:
            if pd.isna(native):
                return ""
        except (ValueError, TypeError):
            pass
        return native
    return str(val) if val is not None else ""


# 导出DataFrame为CSV，支持Site过滤、Pass/Fail过滤。
# 历史参数 keep_header / match_original_format / raw_lines（原始格式还原导出）
# 在 API 路径从未启用（调用方恒传默认值），已删除——如需原始格式导出请重新设计。
def export_to_csv(df: pd.DataFrame, metadata: Dict, site_filter=None, passfail_filter=None) -> bytes:
    export_df = df.copy()

    if site_filter and site_filter != "全部":
        site_col = get_site_column(df)
        if site_col:
            export_df = export_df[export_df[site_col].astype(str) == str(site_filter)]

    if passfail_filter and passfail_filter != "全部":
        format_type = metadata.get('format', 'CTA8290D')
        bin_col = get_bin_column_name(format_type)

        if bin_col in export_df.columns:
            if passfail_filter == "Pass":
                export_df = export_df[ensure_numeric(export_df, bin_col) == 1]
            elif passfail_filter == "Fail":
                export_df = export_df[ensure_numeric(export_df, bin_col) != 1]

    return export_df.to_csv(index=False).encode('utf-8-sig')
