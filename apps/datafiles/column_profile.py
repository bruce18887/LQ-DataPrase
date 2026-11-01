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

from apps.analysis.services.statistics.helpers import (
    get_serial_candidates,
    get_serial_column,
    get_site_column,
)
from apps.datafiles.parsers.base import SYSTEM_COLUMNS

# 首屏列级元信息的四个响应键：视图侧的回落判定与体积核算都读这张表，
# 别在第二处再写一遍键名清单（写第二份必漂）。
COLUMN_PROFILE_KEYS = ('site_options', 'numeric_columns', 'system_columns', 'serial_column')

# histogram 专用候选列（A4b）：随解析写透缓存的**内部键**，不在 `COLUMN_PROFILE_KEYS` 里
# ——那是 browse 响应四键契约，page==1 才下发；这一只只给 histogram fast path 消费
# （`resolve_histogram_candidates`），绝不能渗进响应。
HISTOGRAM_PROFILE_KEY = 'histogram_numeric_columns'


def keep_columns_with_values(df, cols) -> list:
    """`cols` 里在 `df` 上至少有一个非空值的那些列，按 `cols` 原序返回**新列表**。

    向量化口径（本机实测 1,702 列那档）：逐列 `dropna().empty` 要 205ms（每列都新建
    一次 dropna 的 Series 再判空），`notna().any()` 一遍 91ms，逐列结果实测相同——
    等价性由 `apps/analysis/tests_param_list_scan.py` 的逐列对照钉住，不是口头承诺。

    范围限定（别把这句话读大）：本函数是**候选池判空**的唯一归属点。全仓还有别的
    `.notna().any()`，形态与口径都不同——`build_column_profile` 里 browse 那份是逐列
    循环里的单列判定（值级口径，要和 `pd.to_numeric` 分流），`analysis/views/_helpers.py`
    的 `_sanitize_numeric_params` 要把判空结果留成 Series 继续和 dtype 一起逐列用。
    后两者与本函数合并属于 I 波「重复实现合并」的面，不在本刀。
    """
    has_value = df[list(cols)].notna().any().to_numpy()
    return [c for c, ok in zip(cols, has_value) if ok]


def build_histogram_param_candidates(df) -> list:
    """histogram fast path 的候选参数列口径（A4b 前它是视图里的现算代码）。

    口径是**逐字**从改动前 `analysis_views.py` 那段（``data_only_bin1`` 为假时的形状）
    搬来的（等价性钉在 `test/backend/test_histogram_candidates_fastpath.py`，基线是那段
    代码的原样副本；与 browse 口径的差异钉在 `HistogramCaliberDivergenceTests`）：

    * 排除 `get_serial_candidates(df)` 的**全部**候选（Serial_No 与 Dut_No 并存时两者
      都不能当参数）与 `get_site_column(df)` 命中的站点列——它们是元信息不是数据参数；
    * 纯 dtype 口径：`is_numeric_dtype` 且非 bool（`Dut_Pass` 的 TRUE/FALSE 不可测）；
      object 数字串列（`SW_Bin`）**不收**——这与 browse 的值级判定是两套集合；
    * 列序 = `df.columns`；候选非空时经 `keep_columns_with_values` 一次向量化剔掉全空列。

    两个序列/site 判定与 dtype 判定都只看**列名/列 dtype**，与行内容无关——所以
    `data_only_bin1` 收窄行后复用全帧候选做池是安全的：行过滤不会让 object/bool 列
    变可测数值（不新增），但可能让原本非空的列变全空（消费侧要在过滤后帧上再筛一次，
    判据见 fast path 测试的第④条）。
    """
    meta_cols = set(get_serial_candidates(df))
    site_col = get_site_column(df)
    if site_col:
        meta_cols.add(site_col)
    numeric_cols = [c for c in df.columns
                    if pd.api.types.is_numeric_dtype(df[c])
                    and not pd.api.types.is_bool_dtype(df[c])
                    and c not in meta_cols]
    return keep_columns_with_values(df, numeric_cols)


def resolve_histogram_candidates(df, metadata, *, rows_filtered=False) -> list:
    """histogram fast path 的取数：缓存优先，名单不描述当前帧就整只现算。

    三条规则都是这只 profile 自己的知识，所以住在口径模块里，不给视图抄一遍：

    * **缺席才回落**：`None`（没 profile / 没该键）走现算；**空列表是合法值**，
      按真值判回落会让每请求白扫一遍帧（判据 fast path ③）。
    * **名单必须落在当前帧上**：缓存条目按内容坐标键存，正常不可能对不上；一旦对不上
      （条目与帧不同源），`df[名单]` 会 KeyError 变成 500 —— 那种条目不可信，整只重算。
      判据 fast path ⑧。
    * **交出去的必须是副本**：缓存列表是跨请求共享对象，下游谁就地一改就传染到后续所有
      请求（判据 fast path ⑥）。

    `rows_filtered` 表示消费方已经把行收窄过（`data_only_bin1`）：缓存名单出自全帧，
    行过滤不新增可测数值列，但会让原本非空的列变全空 ⇒ 在过滤后的帧上再筛一次判空，
    保住「过滤后全空的列不进参数集」的旧语义（判据 fast path ④）。
    """
    profile = metadata.get('column_profile') if isinstance(metadata, dict) else None
    cached = profile.get(HISTOGRAM_PROFILE_KEY) if isinstance(profile, dict) else None
    if cached is None or not set(cached) <= set(df.columns):
        return build_histogram_param_candidates(df)
    candidates = list(cached)
    if rows_filtered:
        candidates = keep_columns_with_values(df, candidates)
    return candidates


def build_column_profile(df, format_type) -> dict:
    """随解析只算一次的列级元信息（响应四键见 `COLUMN_PROFILE_KEYS`，另随存一只
    histogram 内部键 `HISTOGRAM_PROFILE_KEY`——五键存储、四键下发）。

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

    与直方图的参数候选**不是同一个集合**（纯 dtype 口径 + 排除序列/site 列 + 行收窄后
    再判空），所以那边**不许**消费 `numeric_columns`；A4b 给它随解析多算一只内部键
    （`HISTOGRAM_PROFILE_KEY`，口径见 `build_histogram_param_candidates`），
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
        # histogram 专用候选（内部键，不进 browse 响应）：随同一只 profile 写透缓存，
        # 消费侧缺键必须回落现算（挂载外壳算不出时整只 profile 都不挂，键缺失即回落信号）。
        HISTOGRAM_PROFILE_KEY: build_histogram_param_candidates(df),
    }
