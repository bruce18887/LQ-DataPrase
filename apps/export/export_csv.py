"""CSV export functions."""

import pandas as pd
from typing import Dict


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


# 导出DataFrame为CSV。调用方（ExportViewSet.to_csv）已用
# _apply_export_filters 按 /browse/ 语义（site/filter_model/passfail/sort）
# 预过滤，旧 site_filter/passfail_filter 参数仅为签名兼容保留，不再使用——
# 旧 bin==1 直判语义与表格 detect_fail_data 不一致，已废弃。
def export_to_csv(df: pd.DataFrame, metadata: Dict, site_filter=None, passfail_filter=None) -> bytes:
    return df.to_csv(index=False).encode('utf-8-sig')
