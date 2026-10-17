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


def site_table_limits(range_type: str, stats: dict,
                      custom_low=None, custom_high=None) -> tuple:
    """Site 统计表的判定限：与分箱用的 bin 区间**不是**一件事，别共用。

    CL 且用户两侧都填了 → 用用户输入；否则按 ``range_type`` 取 stats 里那一对。
    这是 histogram 与 ``/statistics/site_stats/`` 的唯一口径来源：2026-09-05 审查
    契约#4 撞过「CL 各自解释 → Site 表 Fail 恒 0、Yield 恒 100%」，同一屏两个数字
    互相矛盾，所以宁可单列一个函数也不要再抄一遍 if/else。

    与 ``resolve_limits`` 的差别只在 CL 那一支；分箱区间另外还要为退化限值
    （单边缺失、零宽、std==0）回退到数据范围——那是画图的事，不该动 fail 判定。
    """
    if range_type == 'CL' and custom_low is not None and custom_high is not None:
        return float(custom_low), float(custom_high)
    return resolve_limits(range_type, stats)
