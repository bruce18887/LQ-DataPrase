"""Shared request parameter extraction helpers.

Replaces the repeated ``request.data.get('x') or request.query_params.get('x')``
pattern and the private ``_getlist`` / ``_to_float`` helpers in analysis/views.py.
"""


def get_param(request, key, default=None):
    """Get a parameter from request.data with request.query_params fallback.

    Works with both JSON body and form-data (QueryDict).
    """
    val = request.data.get(key)
    if val not in (None, ''):
        return val
    return request.query_params.get(key, default)


def get_param_float(request, key, default=None):
    """Get a float parameter from request.data or request.query_params.

    Returns *default* for blank/invalid input.
    """
    val = get_param(request, key)
    if val in (None, ''):
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def get_param_list(request, key):
    """Get a list parameter from request.data or request.query_params.

    Tolerant to both dict/JSON body and QueryDict/form-data.
    Always returns a list (possibly empty).
    """
    if hasattr(request.data, 'getlist'):
        val = request.data.getlist(key)
    else:
        val = request.data.get(key)
    if val:
        return val if isinstance(val, list) else [val]
    return request.query_params.getlist(key)
