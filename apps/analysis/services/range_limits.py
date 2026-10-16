"""图表「取值区间」解析：把 range_type 映射成一对上下限。

与 ``services/statistics/limits.py`` 是两件事，别混（两者曾在 ``services/`` 下同名
并存 ``limits.py``，读代码时无法区分 —— 架构评审 P1-3，本模块因此改名）：

* 本模块从**已算好的 stats** 里按 ``RDL/DR/CL/S3/S4/S6`` 六种取数口径挑一对上下限，
  喂给直方图 / 序列图的 bin 网格；
* ``statistics/limits.py`` 管**规格限**：metadata 里 Min/Max 文本的解析、无效占位符
  判定、失败行检测与 per-bin / per-test-item 失效统计。

它取代了 histogram / serial_distribution / site_stats 等处重复的 switch-case。
"""


def resolve_limits(range_type: str, stats: dict) -> tuple:
    """Resolve lower/upper limits based on range_type.

    Args:
        range_type: One of 'RDL', 'DR', 'CL', 'S3', 'S4', 'S6'.
        stats: Dict with keys 'rdl', 'dr', 'cl', 's3', 's4', 's6',
               each a (lower, upper, gap) tuple from compute_range_statistics.

    Returns:
        (lower, upper) float tuple. Either value may be None if
        range_type is unrecognised.
    """
    if range_type == 'RDL':
        return stats['rdl'][0], stats['rdl'][1]
    elif range_type == 'DR':
        return stats['dr'][0], stats['dr'][1]
    elif range_type == 'CL':
        return stats['cl'][0], stats['cl'][1]
    elif range_type == 'S3':
        return stats['s3'][0], stats['s3'][1]
    elif range_type == 'S4':
        return stats['s4'][0], stats['s4'][1]
    elif range_type == 'S6':
        return stats['s6'][0], stats['s6'][1]
    return None, None
