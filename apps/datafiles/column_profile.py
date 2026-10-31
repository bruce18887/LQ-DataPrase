"""首屏列级元信息（`column_profile`）的口径本体 —— **Django-free 模块**。

本模块只做纯 pandas 计算：除了 `pandas` 与本仓两张权威表（`SYSTEM_COLUMNS`、
序列列优先级），**不许 import 任何 Django 相关**（`django.*` / models / views /
settings）。理由与 `apps/jobs/runner.py` 的头注、`apps/analysis/services/statistics/
helpers.py` 同一条前提：导出/作业的 CPU worker 跑在 spawn 子进程里，那里没有
`django.setup()`，import 期撞上未配置的 Django 就直接起不来（判据见
`apps/jobs/tests_jobs.py` 的 `WorkerModuleIsolationTests`，规则原文在
`.claude/CLAUDE.md`「CPU worker 侧禁 Django」）。

「挂载与体积记账」（`_column_profile_for_storage` / `_column_profile_bytes`）在
`apps/datafiles/parse_cache_sizing.py`：那是解析缓存的职责，不是口径的职责。
（2026-10-28 波次 G2 前它们在 `services.py`；为给 fail 检测缓存腾 600 行额度搬走，
一句断言没改。）
"""
from typing import Optional

import pandas as pd

from apps.analysis.services.statistics.helpers import get_serial_column, get_site_column
from apps.datafiles.parsers.base import SYSTEM_COLUMNS

# 首屏列级元信息的四个响应键：视图侧的回落判定与体积核算都读这张表，
# 别在第二处再写一遍键名清单（写第二份必漂）。
COLUMN_PROFILE_KEYS = ('site_options', 'numeric_columns', 'system_columns', 'serial_column')


def build_column_profile(df, format_type) -> dict:
    """随解析只算一次的列级元信息（四键见 `COLUMN_PROFILE_KEYS`）。

    口径是**逐字**从 `browse_views` 首屏那段现算搬来的（等价性钉在
    `test/backend/test_column_profile_cache.py`，基线是那段代码的原样副本）：

    * `site_options`：`get_site_column` 找到站点列后取 `dropna().astype(str).unique()`，
      再排除 `''` 与 `'nan'`；
    * `numeric_columns`：object 列走**值级**判定（`pd.to_numeric(...).notna().any()`），
      数字字符串列要能进来；数值 dtype 列要求非 bool 且至少有一个非空值（全 NaN 列、
      `Dut_Pass` 这类 bool 列都不算）；
    * `system_columns`：文件列序 ∩ `SYSTEM_COLUMNS[format_type]`（按格式权威列表，
      不是列名前缀启发式）；
    * `serial_column`：`get_serial_column(df)`（全项目唯一的序列列优先级）。

    两点不许「顺手改」：
    ① 那句注释点名的 `NON_NUMERIC_COLUMNS` 是**解析器**用来决定「哪些 object 列不做数值强制」
       的（`parsers/base.py:210`），本函数从不读它——旧写法也没读。一旦开始按它筛，
       `numeric_columns` 的集合就变了，而那是前端可选参数集（契约）。
       object 分支在生产里确实会走到：那张表里的列（Site_No/SW_Bin/QR_Code…）只要出现缺失值，
       `read_csv` 就留它 object dtype 且永不被强制成数值。
    ② 必须在**过滤前的全量帧**上算（调用点就是解析刚结束的那一刻），
       与旧写法「筛选前先算」的语义一致。

    与直方图的参数候选（`analysis_views` 那份纯 dtype 口径 + 排除序列/site 列 +
    行收窄后再判空）**不是同一个集合**，所以那边不许复用这只 profile；
    差异本身钉在 `HistogramCaliberDivergenceTests`。
    """
    site_options: list = []
    numeric_columns: list = []
    system_columns: list = []
    serial_column: Optional[str] = None
    site_col_full = get_site_column(df)
    if site_col_full:
        site_options = [
            str(v) for v in df[site_col_full].dropna().astype(str).unique()
            if str(v) not in ('', 'nan')
        ]
    for col in df.columns:
        if df[col].dtype == object:
            # 值级判定（镜像旧前端 Number.isFinite 语义）：SW_Bin/X_COORD 等
            # 数字字符串列保持 object dtype（NON_NUMERIC_COLUMNS），纯 dtype 判定会漏
            if pd.to_numeric(df[col], errors='coerce').notna().any():
                numeric_columns.append(col)
        elif (pd.api.types.is_numeric_dtype(df[col])
              and not pd.api.types.is_bool_dtype(df[col])
              and df[col].notna().any()):
            # 排除 bool（Dut_Pass，TRUE/FALSE 非数值）与全 NaN 列（QR_Code 解析后）
            numeric_columns.append(col)
    # 记录级列（系统列）：按格式权威列表（SYSTEM_COLUMNS）∩ 文件列，
    # 保持文件列序——前端据此恒显+前置，不再用名称前缀启发式
    # （Device_Fused_Flag1/2、SITE_CHECK 等测试项与记录列同名前缀，2026-08-25）。
    sys_set = set(SYSTEM_COLUMNS.get(format_type, []))
    system_columns = [c for c in df.columns if c in sys_set]
    # 序列列：四种格式名字各不相同（Serial_No / Serial # / PART_ID），且 Dut_No
    # 也是每只 DUT 一个号 —— 前端不许再用名称猜，统一由后端权威解析下发。
    # get_serial_candidates 是全项目唯一的序列列优先级（serial_distribution /
    # wafer_map / file_correlation 共用），这里只是多消费一次。
    serial_column = get_serial_column(df)
    return {
        'site_options': site_options,
        'numeric_columns': numeric_columns,
        'system_columns': system_columns,
        'serial_column': serial_column,
    }
