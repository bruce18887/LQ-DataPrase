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


# 导出 DataFrame 为 CSV：返回整份 bytes 的「字节判据」（oracle），保留给
# 测试（site_filter / passfail_filter 两个参数已无调用方；过滤由视图侧的
# apply_export_filters 完成）。生产路径改走 export_to_csv_file 分块写盘，
# 二者输出逐字节相同。
def export_to_csv(df: pd.DataFrame, metadata: Dict, site_filter=None, passfail_filter=None) -> bytes:
    return df.to_csv(index=False).encode('utf-8-sig')


# 写盘时的行分块：pandas 一次写整帧会在内部攒出接近输出体积的缓冲
# （本机 120k×5 实测 to_csv 峰值 ≈1.7× 输出体积）；按固定行数分块后
# 峰值降到 ~1MB，而字节输出与 export_to_csv 逐字相同（由
# test_csv_download_streaming 的字节相等判据钉住）。
CSV_WRITE_CHUNK_ROWS = 1000


def export_to_csv_file(df: pd.DataFrame, metadata: Dict, path_or_buf) -> None:
    """把 DataFrame 分块写成 UTF-8-SIG CSV，不返回全量 bytes。

    与 ``export_to_csv`` 的输出逐字节等价（同一 ``to_csv(index=False)`` +
    ``utf-8-sig``），供 to_csv 视图写临时文件后由 ``FileResponse`` 直接读盘，
    避免「整串 str → 整份 bytes → BytesIO 再拷一份」的三份全量驻留。
    ``metadata`` 与 ``export_to_csv`` 保持同形，当前不参与序列化。
    """
    df.to_csv(path_or_buf, index=False, encoding='utf-8-sig',
              chunksize=CSV_WRITE_CHUNK_ROWS)
