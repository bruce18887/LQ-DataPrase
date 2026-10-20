# apps/weight/views.py
"""权重画图的端点：解析（Task 3）与 xlsx 导出（Task 5）。

不落库、不落盘、不用 multipart（spec §4）。同步 FileResponse —— 作业化那条路要求 DataFile 行。
（导出口径下「不落库」= 不碰 DataFile/ParseHistory、**不写 MEDIA_ROOT**；但「零写入」这话别说满：
`render_export_filename` 内部是 `UserSetting.objects.get_or_create(user=…)`
（`apps/common/export_naming.py:97`），它会**发 SQL**，并给「从没存过设置的账号」**INSERT 一行
UserSetting**。那是本仓**全部既有导出通路共同**的形态、写的是账号设置而不是权重数据（spec §4），
任何人后续要写「零 SQL / 零写入」的断言必须以「除这一行设置外」为前提。）

错误形态（spec §3.3）：一律走 `apps/common/errors.py:14` 的 `error_response()`，HTTP 400，
后端只给**稳定机器码 + 结构化 detail**，中文文案留在前端 `ERROR_CODE_MAP`（Task 7 进那四个新码）。
入站守卫（缺 `text`/`filename`、类型不对、body 不是对象）= 两个视图共用的 `_guard_core()`，
复用既有码 `param_required`，**不新增机器码** —— 每个新码都必须同时进那张表，那是改 spec。
守卫必须 `detail=None`：`error_response()` 会把非空字符串 detail 复制进 `message`
（`apps/common/errors.py:29`），而 `pickMessage` 优先读 `message`、再读 `detail`，最后才查码表
（`frontend/src/utils/error.ts:60-64`）⇒ 任何非空 detail（英文串也算）都会盖掉前端中文。
机器可读信息（哪个字段缺了）走 `extra`，键名 `field`。
"""
from __future__ import annotations

import io

from django.http import FileResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.errors import error_response
from apps.common.export_naming import base_export_context, render_export_filename

from .parser import WeightError, doc_to_payload, parse_weight_text
from .xlsx import build_weight_workbook

FILENAME_MAX = 120
PALETTE_LEN = 8        # spec §6：色板恒 8 项；长度不对必须拒（见 `_str_list`）


def _bad_input(**extra):
    return error_response('param_required', None, **extra)


def _str_list(value, expected: int) -> list[str] | None:
    """必须是**恰好** expected 项的列表，否则 None（= 守卫拒绝）。

    长度守卫不是洁癖：`xlsx._series_color` 取 `palette[组序 % len(palette)]`，而 builder 里
    `tuple(...) or DEFAULT_PALETTE` 会让空表**静默**换成后端那份默认板（`test_weight_xlsx.py:563`
    把这个行为钉成了契约）⇒ 少一项就是整份色板错位或替换，用户看到的图色和主题不一致，
    却没有任何错误报出来。值本身畸形（非字符串/非 16 进制）才交给 builder 逐项回退。
    """
    if not isinstance(value, list) or len(value) != expected:
        return None
    return [v if isinstance(v, str) else '' for v in value]


def _guard_core(data):
    """parse 与 export **共享**的入站守卫，返回 `(错误或 None, text, filename)`。

    这两段定义的是同一个 400 形状（`param_required` + `field=`、detail 恒 None —— 见模块头），
    各自写一遍迟早漂移，所以两个视图都调这里。第一项非 None 时调用方必须**原样 return**。
    R3②：不能假设前端已经过滤过 —— body 本身可能是 JSON 数组/裸标量，那种形状下
    `data.get(...)` 会 AttributeError 成 500，而承诺是 400 + `param_required`。
    """
    if not isinstance(data, dict):
        return _bad_input(field='body'), None, None
    text = data.get('text')
    filename = data.get('filename')
    if not isinstance(text, str) or not text:
        return _bad_input(field='text'), None, None
    if not isinstance(filename, str) or not filename:
        return _bad_input(field='filename'), None, None
    return None, text, filename


def _weight_error_response(exc: WeightError):
    """解析错误原样透传（同样两端点共享）：detail = 结构化字段字典（非字符串 ⇒ 不会被
    复制成 message），同一组字段也平铺到响应顶层，让不带前端映射的调用方
    （curl / 脚本 / Playwright）按名读得到 line、declared、actual……
    """
    return error_response(exc.code, exc.fields or None, **exc.fields)


class WeightParseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        err, text, filename = _guard_core(request.data)
        if err is not None:
            return err
        shown = filename[:FILENAME_MAX]
        try:
            doc = parse_weight_text(text, filename_hint=shown)
        except WeightError as exc:
            return _weight_error_response(exc)
        return Response({**doc_to_payload(doc), 'filename': shown})


class WeightExportView(APIView):
    """同一份文本 + 页面上的可见性/均值开关 → 原生图表 xlsx 字节流（零落库、零落盘）。

    参数口径（spec §4 的请求体契约；错误形态见 §3.3/§3.4）：`visible_group_indexes` 缺席 = 全可见，
    元素级容错交给 builder（脏索引按不可见处理，绝不因为一个越界下标把导出打成 500）；
    `palette` 是表现层，只卡长度、不卡值。
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data
        err, text, filename = _guard_core(data)
        if err is not None:
            return err
        indexes = data.get('visible_group_indexes')
        if indexes is not None and not isinstance(indexes, list):
            return _bad_input(field='visible_group_indexes')
        palette = _str_list(data.get('palette'), PALETTE_LEN)
        if palette is None:
            return _bad_input(field='palette')
        mean_color = data.get('mean_color', '')
        if not isinstance(mean_color, str):
            return _bad_input(field='mean_color')
        show_mean = data.get('show_mean', False)
        if not isinstance(show_mean, bool):
            # 与 palette/mean_color 同口径**拒**，不在这里 truthy 一下：`'false'`/`'0'`/`[x]`
            # 都是 truthy，`bool()` 会把「用户没要均值」静默渲染成一份画满均值的错工作簿，
            # 而且没有任何错误报出来。整个键缺席 = False（前端「没开均值」那条路径）。
            return _bad_input(field='show_mean')
        try:
            doc = parse_weight_text(text, filename_hint=filename[:FILENAME_MAX])
        except WeightError as exc:
            return _weight_error_response(exc)
        # sheet 名已改为测试项名（总览 + 每项一张）；文件名 stem 只用于下载名。
        stem = (filename.rsplit('.', 1)[0] if '.' in filename else filename)[:FILENAME_MAX]
        base = stem or filename[:FILENAME_MAX]   # 文件名整串就是扩展名时 stem 为空（`'.'`、`'.csv'`）
        # 下载名与源文件 stem 同源（R3）
        content = build_weight_workbook(
            doc, visible_group_indexes=indexes, show_mean=show_mean,
            palette=palette, mean_color=mean_color)
        fname = render_export_filename(
            request.user, 'weight_plot', 'xlsx',
            {**base_export_context(request.user), 'filename': base})
        # FileResponse 而不是 Response + 手写头：WSGI 头只认 latin-1，中文源文件名会
        # UnicodeEncodeError；FileResponse 自己出 RFC 5987，但**实测 Django 6.0.5 发的是小写**
        # `filename*=utf-8''…`（不是 RFC 里那个大写 `UTF-8`），且非 ASCII 名时 `filename="…"`
        # 回退段整个缺席 —— 真值由 `test_chinese_source_name_goes_through_rfc5987` 钉住。
        # 前端 `utils/download.ts:28` 的正则带 /i 且 charset 段可选 ⇒ 两种形态都吃。
        return FileResponse(io.BytesIO(content), as_attachment=True, filename=fname,
                            content_type=(
                                'application/vnd.openxmlformats-officedocument'
                                '.spreadsheetml.sheet'))
