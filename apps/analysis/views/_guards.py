"""统计端点共用的参数守卫（架构评审 P1-2 / lessons R3①）。

同一类失败必须报同一个码，否则客户端只能靠解析中文 detail 分支。改造前的实测分叉：
「请求的参数**一个都不在该文件里**」这一条同一条件，``histogram`` 报
``no_valid_params``（与「参数存在但全无有效数值」**共用同一个码**，客户端分不出
「参数不存在」和「参数没数据」），``cpk`` 报 ``param_not_found``，``param_trend`` 报
``no_valid_params`` 却写着「均不在该文件中」的文案 —— 三个端点三套说法。

本模块把这一条统一到 ``param_not_found``。刻意保留的两档，不是漏改：

* 列表级「存在但都无有效数值」→ ``no_valid_params``；
* 单参数「存在但无有效数值」→ ``param_no_valid_data``。

**已知未覆盖**：``boxplot`` 与 ``correlation_matrix`` 走
``_sanitize_numeric_params``，那个函数把「列不存在」与「非数值/全 NaN/bool」一次滤掉，
调用方拿不到区分，所以这两处仍只能报 ``no_valid_params``。要让它们也分档，得在
sanitize 之前先 `split_params` —— 那会改变 `need_at_least_2_params` 的触发面，属独立改动。
"""
from apps.common.errors import error_response

ALL_MISSING_MESSAGE = '请求的参数均不在该文件中，请重新选择文件或参数'


def split_params(df, params):
    """按「是否在该文件的列里」把参数列表切成 (存在, 不存在)，保持原顺序。"""
    columns = df.columns
    valid = [p for p in params if p in columns]
    missing = [p for p in params if p not in columns]
    return valid, missing


def all_missing_params(params, missing):
    """列表级「一个都不在文件里」→ 400 ``param_not_found``。

    ``requested`` / ``missing`` 是前端按名读取的字段（切文件后的 stale 参数要靠它们
    提示「重新选择文件」），键名不得改。
    """
    return error_response('param_not_found', ALL_MISSING_MESSAGE,
                          requested=params, missing=missing)


def guard_all_missing(df, params):
    """有参数、但全部不在文件里 → 返回 400 响应；否则返回 ``(params, None)``。

    空列表**不在这里判**：调用方对「没传参数」的语义各不相同（有的回退到全列、
    有的报 ``params_required``），统一反而会把某条路径改坏。
    """
    valid, missing = split_params(df, params)
    if params and not valid:
        return None, all_missing_params(params, missing)
    return valid, None
