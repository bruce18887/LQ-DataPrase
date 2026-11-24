import re

_CONTROL_OR_SEPARATOR = re.compile(r'[\/\\\x00-\x1f\x7f]')


def normalize_combination_name(raw) -> str:
    if not isinstance(raw, str):
        raise ValueError('组合名必须是字符串')
    value = raw.strip()
    if not value:
        raise ValueError('组合名不能为空')
    if len(value) > 40:
        raise ValueError('组合名最长 40 字符')
    if _CONTROL_OR_SEPARATOR.search(value):
        raise ValueError('组合名不能包含 /、\\ 或控制字符')
    return value


def normalize_batch_no(raw) -> str:
    if raw is None:
        return ''
    if not isinstance(raw, str):
        raise ValueError('批次号必须是字符串')
    value = raw.strip()
    if len(value) > 40:
        raise ValueError('批次号最长 40 字符')
    if _CONTROL_OR_SEPARATOR.search(value):
        raise ValueError('批次号不能包含 /、\\ 或控制字符')
    return value


def managed_tags_for(combination_name: str | None, batch_no: str) -> list[str]:
    if not combination_name:
        return []
    tags = [combination_name]
    if batch_no:
        tags.append(f'{combination_name} / {batch_no}')
    return tags


def resolve_batch_no(explicit: str, metadata: dict) -> str:
    if explicit:
        return normalize_batch_no(explicit)
    raw = (metadata or {}).get('lot_id')
    if not isinstance(raw, str):
        return ''
    try:
        return normalize_batch_no(raw)
    except ValueError:
        return ''
