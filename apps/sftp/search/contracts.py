"""``SearchSpec`` 契约：搜索请求体的校验与钳位（spec §3.2）。

纯逻辑模块——不读配置、不建连接、不碰 ORM，因此能在 ``test/backend/`` 当纯单元测试跑。

三条不可让的约束（理由见 spec §3.2）：

1. **未知键一律拒绝**。DRF serializer 默认静默忽略未声明字段，本项目的历史教训就是
   ``sftp.ts`` 至今还在发后端从不读的 ``only_data``——会悄悄失效的字段比报错更糟。
2. **数值越界是钳位不是报错**（``clamped_<field>`` 码 + engine 转 notice）：用户把滑块
   拖到最大不该吃 400。但 ``term`` 超长与 ``roots`` 超数是**报错**——静默截断查询串
   等于让用户查了别的东西。
3. **深度不设实用上限**（``HARD_MAX_DEPTH=64`` 只防路径长度爆掉）：防遍历失控的闸是
   ``max_entries`` 与 ``timeout``，它们和目录形状无关；用深度兜会在目标树恰好深一层时
   静默少结果，而静默少结果比慢十倍恶劣得多。
"""

import dataclasses
import posixpath
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from apps.sftp.downloads import clamp_timeout

# —— 枚举档位 ——
MODES = ('name', 'content', 'column')
MATCHINGS = ('substring', 'whole_word', 'fuzzy')
DEPTHS = ('self', 'children', 'all', 'custom')
DEPTH_TO_MAX = {'self': 0, 'children': 1, 'all': None, 'custom': None}

# —— 全搜索子系统共享常量（计划 Global Constraints：各处只从这里取，勿另写数字）——
READ_TIMEOUT_SEC = 15          # 单次 SFTP channel 读超时，配合 downloads.channel_timeout
HARD_MAX_DEPTH = 64            # depth=custom 的硬顶，仅防路径长度爆掉
MAX_ROOTS = 20                 # 一次搜索最多几个根目录，超出报错
MAX_TERM_LEN = 200             # 查询串长度上限，超出报错（不截断）
PRESET_MAX_PER_USER = 50       # 每用户搜索预设条数上限

# 每项 (low, high)；越界即夹并记 clamped_<field>
_INT_BOUNDS = {
    'workers': (1, 8),
    'max_entries': (1, 500_000),
    'max_candidates': (1, 50_000),
    'max_matches': (1, 20_000),
    'matches_per_file': (1, 20),
    'column_rows': (1, 50),
    'max_scan_bytes': (1, 1 << 30),
}

_DATE_FORMATS = ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M', '%Y-%m-%d')

_TRUE_STRINGS = frozenset({'true', '1', 'yes', 'y', 'on'})

_KNOWN_KEYS = frozenset({
    # 作用域
    'roots', 'depth', 'max_depth', 'prune_dirs',
    # 元数据过滤
    'name_pattern', 'modified_after', 'modified_before', 'min_size', 'max_size',
    'data_files_only',
    # 命中模式
    'mode', 'term', 'column_name', 'column_rows', 'matching', 'case_sensitive',
    'first_hit_per_file', 'matches_per_file', 'one_per_folder',
    # 执行控制
    'workers', 'allow_server_grep', 'stop_after_listing', 'max_entries',
    'max_candidates', 'max_matches', 'max_scan_bytes', 'timeout',
})


class SearchSpecError(ValueError):
    """契约校验失败。视图层转 ``400 {"error": msg}``；``.field`` 供前端定位控件。"""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class SearchSpec:
    """校验并钳位后的搜索请求。engine/walker/scanners 只读它，不再碰用户输入。"""

    roots: Sequence[str]
    mode: str
    depth: str = 'all'
    max_depth: Optional[int] = None
    prune_dirs: Sequence[str] = field(default_factory=list)
    name_pattern: Optional[str] = None
    modified_after: Optional[datetime] = None
    modified_before: Optional[datetime] = None
    min_size: Optional[int] = None
    max_size: Optional[int] = None
    data_files_only: bool = True
    term: str = ''
    column_name: str = ''
    column_rows: int = 10
    matching: str = 'substring'
    case_sensitive: bool = False
    first_hit_per_file: bool = True
    matches_per_file: int = 1
    one_per_folder: bool = False
    workers: int = 4
    allow_server_grep: bool = True
    stop_after_listing: bool = False
    max_entries: int = 200_000
    max_candidates: int = 5_000
    max_matches: int = 2_000
    max_scan_bytes: int = 67_108_864
    timeout: int = 600
    clamped: List[str] = field(default_factory=list)

    def effective_max_depth(self) -> Optional[int]:
        """遍历深度上限；``None`` = 不限（spec §3.2「深度默认不限」）。"""
        if self.depth != 'custom':
            return DEPTH_TO_MAX[self.depth]
        return self.max_depth


# 契约默认值的唯一来源就是 dataclass 字段声明，避免两处数字漂移。
_SPEC_DEFAULTS: Dict[str, Any] = {
    f.name: f.default
    for f in dataclasses.fields(SearchSpec)
    if f.default is not dataclasses.MISSING
}

_MISSING = object()


def parse_spec(raw: dict) -> SearchSpec:
    """校验并钳位请求体。任何不合法输入抛 :class:`SearchSpecError`。"""
    if not isinstance(raw, dict):
        raise SearchSpecError('body', '请求体必须是 JSON 对象')

    unknown = sorted(str(key) for key in set(raw) - _KNOWN_KEYS)
    if unknown:
        raise SearchSpecError(
            unknown[0],
            f'未知字段：{"、".join(unknown)}。搜索请求只接受：'
            f'{"、".join(sorted(_KNOWN_KEYS))}')

    clamped: List[str] = []
    values: Dict[str, Any] = {}

    # —— 作用域 ——
    values['roots'] = _normalise_roots(_get(raw, 'roots'))
    mode = values['mode'] = _as_enum('mode', _get(raw, 'mode'), MODES)
    depth = values['depth'] = _as_enum('depth', _get(raw, 'depth'), DEPTHS)
    values['max_depth'] = _resolve_max_depth(_get(raw, 'max_depth'), depth, clamped)
    values['prune_dirs'] = _string_list('prune_dirs', _get(raw, 'prune_dirs'))

    # —— 元数据过滤 ——
    values['name_pattern'] = _optional_text(_get(raw, 'name_pattern'))
    for key in ('modified_after', 'modified_before'):
        values[key] = _as_datetime(key, _get(raw, key))
    values['min_size'] = _optional_size('min_size', _get(raw, 'min_size'))
    values['max_size'] = _optional_size('max_size', _get(raw, 'max_size'))
    if (values['min_size'] is not None and values['max_size'] is not None
            and values['min_size'] > values['max_size']):
        raise SearchSpecError(
            'min_size',
            f"min_size({values['min_size']}) 大于 max_size({values['max_size']})")
    values['data_files_only'] = _as_bool(_get(raw, 'data_files_only'))

    # —— 命中模式 ——
    values['term'] = _search_text('term', _get(raw, 'term'),
                                  required=(mode == 'content'), mode_name='内容搜索')
    values['column_name'] = _search_text('column_name', _get(raw, 'column_name'),
                                         required=(mode == 'column'),
                                         mode_name='列匹配')
    values['column_rows'] = _bounded_int('column_rows', _get(raw, 'column_rows'), clamped)
    values['matching'] = _as_enum('matching', _get(raw, 'matching'), MATCHINGS)
    values['case_sensitive'] = _as_bool(_get(raw, 'case_sensitive'))
    values['first_hit_per_file'] = _as_bool(_get(raw, 'first_hit_per_file'))
    values['matches_per_file'] = _bounded_int(
        'matches_per_file', _get(raw, 'matches_per_file'), clamped)
    values['one_per_folder'] = _as_bool(_get(raw, 'one_per_folder'))

    # —— 执行控制 ——
    values['workers'] = _bounded_int('workers', _get(raw, 'workers'), clamped)
    values['allow_server_grep'] = _as_bool(_get(raw, 'allow_server_grep'))
    values['stop_after_listing'] = _as_bool(_get(raw, 'stop_after_listing'))
    for key in ('max_entries', 'max_candidates', 'max_matches', 'max_scan_bytes'):
        values[key] = _bounded_int(key, _get(raw, key), clamped)
    values['timeout'] = _resolve_timeout(_get(raw, 'timeout'), clamped)

    return SearchSpec(clamped=clamped, **values)


# ---------------------------------------------------------------- 取值与类型


def _get(raw: dict, key: str) -> Any:
    """缺失或显式 ``null`` 都按契约默认值处理（前端把「清空」当 null 发）。"""
    value = raw.get(key, _MISSING)
    if value is _MISSING or value is None:
        return _SPEC_DEFAULTS.get(key)
    return value


def _as_int(key: str, value: Any) -> int:
    if isinstance(value, bool):
        raise SearchSpecError(key, f'{key} 必须是整数，收到布尔值')
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            raise SearchSpecError(key, f'{key} 必须是整数，收到 {value!r}')
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            raise SearchSpecError(key, f'{key} 必须是整数，收到 {value!r}') from None
    raise SearchSpecError(key, f'{key} 必须是整数，收到 {value!r}')


def _as_bool(value: Any) -> bool:
    """容忍字符串真值——前端表单偶尔把开关发成 ``'true'`` / ``'1'``。"""
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_STRINGS
    return bool(value)


def _as_enum(key: str, value: Any, allowed: Sequence[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise SearchSpecError(key, f'{key} 只能是 {" / ".join(allowed)} 之一，收到 {value!r}')
    return value


def _as_datetime(key: str, value: Any) -> Optional[datetime]:
    """接受 ``_DATE_FORMATS`` 三种写法（前端 datetime picker 带不带秒都可能）。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise SearchSpecError(key, f'{key} 必须是时间字符串，收到 {value!r}')
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue  # 逐个试，全部失败才在下面报错，不静默
    raise SearchSpecError(
        key, f'{key} 时间格式无法识别：{value!r}（支持 {" / ".join(_DATE_FORMATS)}）')


# ---------------------------------------------------------------- 作用域与列表


def _normalise_roots(value: Any) -> List[str]:
    """绝对路径、拒 ``..`` 段、``posixpath.normpath`` 归一、去重保序。"""
    out: List[str] = []
    for raw_path in _string_list('roots', value):
        if not raw_path.startswith('/'):
            raise SearchSpecError('roots', f'roots 必须是绝对路径：{raw_path!r}')
        if '..' in raw_path.split('/'):
            # normpath 会把 /a/../b 折成 /b，越权就藏在归一这一步之后，所以先拒。
            raise SearchSpecError('roots', f'roots 不允许 .. 段：{raw_path!r}')
        path = posixpath.normpath(raw_path)
        if path not in out:
            out.append(path)
    if not out:
        raise SearchSpecError('roots', 'roots 不能为空')
    if len(out) > MAX_ROOTS:
        # 超数报错而非截断：只搜前 20 个根会静默少结果，用户看不出来。
        raise SearchSpecError('roots', f'roots 最多 {MAX_ROOTS} 条，收到 {len(out)} 条')
    return out


def _string_list(key: str, value: Any) -> List[str]:
    """「字符串数组」字段的共用形状：非数组报错，单项去空白，空项丢弃、保序去重。"""
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise SearchSpecError(key, f'{key} 必须是字符串数组，收到 {value!r}')
    out: List[str] = []
    for item in value:
        if not isinstance(item, str):
            raise SearchSpecError(key, f'{key} 每一项必须是字符串，收到 {item!r}')
        text = item.strip()
        if text and text not in out:
            out.append(text)
    return out


# ---------------------------------------------------------------- 文本与数值


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SearchSpecError('name_pattern', f'必须是字符串，收到 {value!r}')
    return value.strip() or None


def _search_text(key: str, value: Any, required: bool, mode_name: str) -> str:
    """``term`` / ``column_name``：必填性按模式判，超长**报错不截断**。"""
    if value is None:
        text = ''
    elif isinstance(value, str):
        text = value.strip()
    else:
        raise SearchSpecError(key, f'{key} 必须是字符串，收到 {value!r}')
    if required and not text:
        raise SearchSpecError(key, f'{mode_name}（mode 相关）必须提供 {key}')
    if len(text) > MAX_TERM_LEN:
        raise SearchSpecError(key, f'{key} 最长 {MAX_TERM_LEN} 字符，收到 {len(text)} 字符')
    return text


def _bounded_int(key: str, value: Any, clamped: List[str]) -> int:
    """钳到 ``_INT_BOUNDS[key]``，越界记 ``clamped_<field>``，不报错。"""
    if isinstance(value, str) and not value.strip():
        return _SPEC_DEFAULTS[key]
    number = _as_int(key, value)
    low, high = _INT_BOUNDS[key]
    bounded = min(high, max(low, number))
    if bounded != number:
        clamped.append(f'clamped_{key}')
    return bounded


def _optional_size(key: str, value: Any) -> Optional[int]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    number = _as_int(key, value)
    if number < 0:
        raise SearchSpecError(key, f'{key} 不能为负，收到 {number}')
    return number


def _resolve_max_depth(value: Any, depth: str, clamped: List[str]) -> Optional[int]:
    """只有 ``depth='custom'`` 才有深度上限；其余档位存 ``None``，免得下游读到一个被忽略的数。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        if depth == 'custom':
            raise SearchSpecError('max_depth', 'depth=custom 必须提供 max_depth')
        return None
    number = _as_int('max_depth', value)
    if number < 1:
        raise SearchSpecError('max_depth', f'max_depth 必须是正整数，收到 {number}')
    if number > HARD_MAX_DEPTH:
        clamped.append('clamped_max_depth')
        number = HARD_MAX_DEPTH
    return number if depth == 'custom' else None


def _resolve_timeout(value: Any, clamped: List[str]) -> int:
    """边界复用 ``downloads.clamp_timeout``（30–3600），非法值仍按契约报错。

    ``clamp_timeout`` 对无法转换的输入会回退 600——那是下载端点的宽容；搜索这里
    宁可 400，因为「写了个超时却悄悄变成 600 秒」正是本契约要消灭的那类失效。
    """
    if isinstance(value, str) and not value.strip():
        return _SPEC_DEFAULTS['timeout']
    seconds = _as_int('timeout', value)
    bounded = clamp_timeout(seconds)
    if bounded != seconds:
        clamped.append('clamped_timeout')
    return bounded
