"""解析缓存的**体积记账**与「column_profile 挂载外壳」（Django-free 模块）。

2026-10-28 波次 G2 从 ``apps/datafiles/services.py`` 原样搬出（一句断言没改）：
``services.py`` 当时 599/600，而 G2 要往同一文件里加 fail 检测缓存，必须先腾出空间。
搬出来的是纯计算——bytes 估算、挂载重试外壳——它们不碰 Django、不碰缓存实例本身：

* **不要**把 ``_BytesLRUCache`` / ``_parse_cache`` / ``evict_*`` 搬进来：判据按属性名
  换掉 ``services._parse_cache``，搬走就会「测的是假缓存、跑的是真缓存」。
* ``_resolve_cache_budget_bytes`` / ``PARSE_CACHE_BUDGET_BYTES`` 也不行：
  ``apps/datafiles/tests_parse_cache.py`` 按 ``services.get_budget`` 打桩。
* ``clear_parse_cache`` 被 ``apps/common/exceptions.py`` 直接 import，留在原处。

``services`` 在导入期把这两个名字绑进自己的命名空间；``_parse_value_bytes`` 还作为
``_BytesLRUCache.get_or_compute`` / ``put`` 的 ``size_of=`` 默认值在**类体执行时**被求值，
所以导入之后再 patch 本模块的 ``_parse_value_bytes``（或 ``services`` 上的同名绑定）都是
空操作 —— 默认值仍指向导入期那只函数对象。要让体积计算变慢/变贵，必须 patch 本函数
**内部晚查**的名字（例如 ``_frame_bytes``）：``test/backend/test_parse_cache_single_flight.py``
的 ``CachedParseChainTests`` 打的就是 ``parse_cache_sizing._frame_bytes``。
``_column_profile_for_storage`` 则由 ``services`` 的函数体按全局名查，patch
``services._column_profile_for_storage`` 才生效（patch 本模块的同名绑定不会影响
``services`` 里已经绑好的那一份）。
"""
import logging

from apps.datafiles.column_profile import build_column_profile

logger = logging.getLogger(__name__)


def _frame_bytes(df) -> int:
    """估算一只 DataFrame 的常驻字节数。

    ``deep=True`` 才会把 object 列的真实字符串大小算进来——ATE 数据里
    这类列很多，浅估算会让预算形同虚设。
    """
    if df is None:
        return 0
    try:
        return int(df.memory_usage(deep=True).sum())
    except Exception:
        return 0


def _col_meta_bytes(metadata) -> int:
    """`col_meta` 的真实量级：列名 + 每列三个字符串。

    1702 列那档是几十 KB 量级。`_parse_value_bytes` 若继续按 `64 × len(metadata)` 算，
    它会被估成 64 字节，1536MB 那条预算就成了自欺的数字（判据 J7）。
    """
    col_meta = metadata.get('col_meta') if isinstance(metadata, dict) else None
    if not isinstance(col_meta, dict):
        return 0
    total = 0
    for name, entry in col_meta.items():
        total += len(str(name))
        if isinstance(entry, dict):
            total += sum(len(str(v)) for v in entry.values())
    return total


# 首屏列级元信息的四键与口径本体在 `apps/datafiles/column_profile.py`（Django-free 模块）；
# 这里只留「挂载」与「体积记账」——那是解析缓存的职责，不是口径的职责。
_PARSE_MOUNT_PARSE_SIDE = 'parse(_parse_file_uncached)'
_PARSE_MOUNT_WRITE_THROUGH = 'write-through(put_cached_parsed_file)'


def _column_profile_for_storage(df, format_type, *, source, file_path):
    """解析/写透侧的挂载外壳：算不出就**不挂键**，别把整只文件判成解析失败。

    已知的「算不出」形状是重复列名（`df[col]` 会返回 DataFrame 而没有 `.dtype`；
    `_load_df_from_request` 的去重守卫就是防它——真解析器先用 `make_column_names_unique`
    把 `P1` 变成 `P1.1`，所以那是极端入参而非常态）。旧写法在**视图里**现算：抛错只让
    page==1 那一页 500，page>1 照旧可用。若让它从解析期抛出，`_parse_file_uncached`
    的兜底会把整只文件变成 parse_failed（连 page>1 都打不开）——那是行为变更，不是这一刀
    的目的；写透侧抛出更会把上传链路带崩。
    不挂键的后果只是「视图侧每次首屏回落现算」，与今天逐字一致；正常帧两只键都有，
    「col_meta 与 column_profile 同址」这条常规因此仍然成立。

    这条 WARNING 吞掉的是**故意**吞掉的异常，所以必须可归因：`source` 说是哪条挂载路径
    （解析侧 / 写透侧该修的地方不同）、`file_path`+`format_type` 说是哪只文件的哪种格式、
    `exc_info=True` 留完整栈（写法对齐 `apps/datafiles/views/_helpers.py` 的 `_register_file`）。
    少任何一样，这条 WARNING 在生产日志里就查不到头——等于没留痕。
    """
    try:
        return build_column_profile(df, format_type)
    except Exception as exc:
        logger.warning(
            'column_profile 现算失败（mount=%s file_path=%s format_type=%s）：%s，'
            '本次不挂键，交由消费侧回落',
            source, file_path, format_type, exc,
            exc_info=True,
        )
        return None


def _column_profile_bytes(profile) -> int:
    """`column_profile` 的真实量级：与 `col_meta` 同理，按字符串实际长度计。

    1702 列那档 `numeric_columns` 就把上千个列名整份存着（十几 KB 级），
    继续按「metadata 每键 64 字节」估会让预算再次失真（判据 J7 的同族）。
    A4b 起 profile 里还有第五只列表 `histogram_numeric_columns`（同为列名清单）——
    本函数遍历 `profile.items()` 天然覆盖，点名判据在
    `test.backend.test_column_profile_caliber.HistogramCandidatesSizingTests`。
    """
    if not isinstance(profile, dict):
        return 0
    total = 0
    for name, value in profile.items():
        total += len(str(name))
        if isinstance(value, (list, tuple)):
            total += sum(len(str(v)) for v in value)
        elif value is not None:
            total += len(str(value))
    return total


def _parse_value_bytes(value) -> int:
    """``(df, metadata, format_type)`` 三元组的缓存占用（metadata 按真实量级）。"""
    df = value[0] if isinstance(value, tuple) else None
    total = _frame_bytes(df)
    if isinstance(value, tuple) and isinstance(value[1], dict):
        meta = value[1]
        # `col_meta` 与 `column_profile` 各有自己的真实量级函数，先从「每键 64 字节」
        # 的粗估里剔掉，否则两只 dict 各只算 64 字节（判据 J7 同因）。
        real_sized = sum(
            1 for k in ('col_meta', 'column_profile', 'col_meta_json') if k in meta)
        total += 64 * (len(meta) - real_sized)
        total += _col_meta_bytes(meta)
        total += _column_profile_bytes(meta.get('column_profile'))
        # B5 的预序列化串与 col_meta 字典同量级（几十 KB）；按 64 字节估会让预算失真。
        col_meta_json = meta.get('col_meta_json')
        if isinstance(col_meta_json, str):
            total += len(col_meta_json)
    return total
