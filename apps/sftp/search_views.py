"""SFTP 搜索端点：``POST /sftp/search/`` → SSE。（spec §3.11）

端点单独成模块，仿 :mod:`apps.sftp.config_views` 的抽离方式：``views.py`` 已 562 行、
600 行是硬上限，这里再加搜索与预设两组 action 一定会顶穿。

**错误契约（spec §3.11 在这里表态）**：项目里错误体有两套并存（视图手写的
``{'error': msg}`` 与 ``custom_exception_handler`` 的 ``{code, message, detail}``），
本模块一律走前者：

* 流开始**前**的失败 → ``400 {'error': msg}``，与 ``views.py`` 现有十余处同形，
  ``utils/ssePost.ts`` 只读 ``err.error``；未连接复用既有哨兵 ``'not_connected'``。
* 流开始**后**的错误**只能**是带内 ``error`` 事件。生成器内绝不抛 DRF 异常 ——
  异常处理器拿不到已经开掉的流，只会留下一截没有收尾的 SSE，前端连「失败了」都
  判断不出来。
"""

import json
import logging
from typing import Any, Dict, Iterator, Optional

from django.http import StreamingHttpResponse
from rest_framework.decorators import action
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.response import Response

from .downloads import download_events_to_sse
from .models import SftpSearchPreset
from .search.connect import SearchSession, SearchSessionError
from .search.contracts import (PRESET_MAX_PER_USER, SearchSpec, SearchSpecError,
                               parse_spec)
from .search.runner import SearchRunner

logger = logging.getLogger(__name__)


class SSERenderer(BaseRenderer):
    """把 ``text/event-stream`` 声明成「本端点能接受的响应类型」——只参与内容协商。

    真流是 :class:`~django.http.StreamingHttpResponse`，压根不经过渲染器；没有这个类时
    视图只有 JSONRenderer 在谈，客户端发 ``Accept: text/event-stream``（SSE 客户端的
    自然写法）会被 DRF 在**进 action 之前**判 406 —— 连「400 + 一句原因」都到不了用户
    手里。浏览器 ``fetch`` 默认发 ``*/*``，所以 test client 那一路全绿，只有真机 HTTP
    才现形（Task 11 Step 5 抓出来的）。

    ``render()`` 因此只会在**非流**的失败响应上被调用，必须回 JSON：
    ``utils/ssePost.ts`` 读的就是 ``err.error``。
    """

    media_type = 'text/event-stream'
    format = 'sse'

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if data is None:
            return b''
        return json.dumps(data).encode('utf-8')


# 「用户没连接」在 ``connect.py`` 里的形状：``SearchSession._credentials()`` 两条消息
# （缓存为空 / 缓存后端读失败）都带 ``no cached session (not connected)``。
_NOT_CONNECTED_MARKERS = ('no cached session', 'not connected')

#: ``overwrite=false`` 的宽容写法，与 ``contracts._TRUE_STRINGS`` 同一族（表单编码会把
#: 布尔发成字符串，``'false'`` 是真值 → 不宽容就等于静默覆盖用户的预设）。
_FALSE_STRINGS = frozenset({'false', '0', 'no', 'off', 'n'})

#: 预设名上限只有一个事实来源：模型字段本身。视图再抄一份 80 就是第三处漂移
#: （lessons R：同一区间三份字面量必然不一致）。
_PRESET_NAME_MAX = SftpSearchPreset._meta.get_field('name').max_length


def _json_object(request) -> Optional[Dict[str, Any]]:
    """把请求体当 JSON 对象取；不是对象（数组 / 标量 / 空）返回 ``None`` 由调用方判 400。

    ``request.data.get(...)`` 在 data 是 list 时直接 ``AttributeError`` → 500 HTML 页，
    与 ``views.py`` 那个 ``path=None`` 家族是同一类缺陷（lessons R3②）。
    """
    data = request.data
    return data if isinstance(data, dict) else None


def _is_false(value: Any) -> bool:
    """只有显式假值才算 False（缺字段由调用方按默认 True 处理）。"""
    if isinstance(value, str):
        return value.strip().lower() in _FALSE_STRINGS
    return value is not None and not value


def _is_not_connected(exc: SearchSessionError) -> bool:
    """这次 :class:`SearchSessionError` 是不是「压根没连接」。

    只有这一支换成哨兵 ``not_connected``（前端据此提示重新连接）。其余故障——服务器
    拒绝建连、会话已关、借连接超时——**原因原样吐给用户**：把「服务器拒绝了连接」报成
    「你没连接」会让人去点一个解决不了问题的按钮。

    判据取自消息文本而不是新增异常子类，是因为 ``connect.py`` 已经写完并有自己的测试；
    ``test_the_sentinel_marker_matches_the_real_message`` 钉住两边不会各自漂移。
    """
    text = str(exc).lower()
    return any(marker in text for marker in _NOT_CONNECTED_MARKERS)


def _safe_stream(runner: SearchRunner) -> Iterator[Dict[str, Any]]:
    """把 runner 的事件流包一层：流内的异常只能变成一个 ``error`` 事件。

    ``GeneratorExit`` 是 ``BaseException``，不在拦截范围内 —— 客户端断开时必须原样传进
    ``runner.events()``，由它的 ``finally`` 去关连接与线程池（spec §3.9 第 4 条）。
    异常能冒到这儿，说明 runner 自己的 ``except`` 没接住（连接炸了、上限触发那些都接住了），
    那是真意外：留 WARNING，再告诉前端「这次没了」。
    """
    try:
        yield from runner.events()
    except Exception as exc:                          # noqa: BLE001 - 收尾事件必须发出去
        logger.warning('SFTP search stream broke: %s', exc, exc_info=True)
        yield {'kind': 'error', 'scope': 'fatal', 'path': None,
               'message': str(exc) or type(exc).__name__}


class SftpSearchMixin:
    """搜索端点（预设 CRUD 的三个 action 见 Task 11，同在本 mixin 上）。"""

    #: 类属性而不是就地引用 ``SearchRunner``：测试靠替换它注入异常。
    #: 换上去的替身必须是**类**（或 staticmethod）——模块级函数一放进类属性就成了
    #: 方法，``self._runner_class(spec, session)`` 会多绑一个 ``self`` 进去。
    _runner_class = SearchRunner

    def _build_session(self, user_id: int, workers: int) -> SearchSession:
        """开本次搜索的 N 条临时连接（spec §3.7）。

        单独成一个方法只为**测试注入假连接**——它绝不能被内联进 ``search``，
        否则端点层就没法在不碰 paramiko 的情况下验断流清理。
        """
        session = SearchSession(user_id, workers)
        session.open_all()
        return session

    @action(detail=False, methods=['post'],
            renderer_classes=[JSONRenderer, SSERenderer])
    def search(self, request):
        """``POST /sftp/search/`` → SSE 事件流（事件协议见 spec §3.8）。

        请求体是一个 :class:`~apps.sftp.search.contracts.SearchSpec`：校验、钳位与
        「未知键一律拒」全在 ``parse_spec`` 里，本方法不重做一遍（两处判据迟早漂移）。
        """
        try:
            spec: SearchSpec = parse_spec(request.data)
        except SearchSpecError as exc:
            return Response({'error': str(exc)}, status=400)

        try:
            session = self._build_session(request.user.id, spec.workers)
        except SearchSessionError as exc:
            if _is_not_connected(exc):
                return Response({'error': 'not_connected'}, status=400)
            logger.warning('SFTP search: no connection for user %s: %s',
                           request.user.id, exc)
            return Response({'error': str(exc)}, status=400)
        except Exception as exc:                      # noqa: BLE001 - 开流之前一律 400
            # 主机密钥不匹配（spec §3.7 的安全边界，不降级不吞）等建连故障都在这一支：
            # 它们必须是一句可读的 400，而不是异常处理器那页 HTML 500。
            logger.warning('SFTP search: connection setup failed for user %s: %s',
                           request.user.id, exc, exc_info=True)
            return Response({'error': str(exc)}, status=400)

        runner = self._runner_class(spec, session)
        response = StreamingHttpResponse(
            download_events_to_sse(_safe_stream(runner)),
            content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response

    # ------------------------------------------------- 预设 CRUD（spec §3.10）

    @staticmethod
    def _preset_dict(preset: SftpSearchPreset) -> Dict[str, Any]:
        """手写序列化（不引 serializer 类）：字段集就是「载入预设」需要的全部。

        ``spec`` 原样回传，前端据此回填表单，不发第二次请求；``owner`` **绝不**出现在
        响应里（跨用户隔离由 ``filter`` 保证，但也不该把主键撒出去）。
        """
        return {'id': preset.id, 'name': preset.name, 'spec': preset.spec,
                'updated_at': preset.updated_at.isoformat()}

    @action(detail=False, methods=['get'])
    def search_presets(self, request):
        """``GET /sftp/search_presets/`` → ``{'presets': [...]}``，只含本人预设。

        排序交给模型的 ``ordering = ['-updated_at']``：最近改过的排最前。
        """
        qs = SftpSearchPreset.objects.filter(owner=request.user)
        return Response({'presets': [self._preset_dict(p) for p in qs]})

    @action(detail=False, methods=['post'], url_path='search_presets/save',
            url_name='save-search-preset')
    def save_search_preset(self, request):
        """``POST /sftp/search_presets/save/``，体 ``{name, spec, overwrite?}``。

        **``parse_spec`` 是这道门的门禁**：预设里存一个跑不通的 spec，等于给用户一个
        点了才报错的按钮 —— 搜索端点会拒的条件，保存时必须更早拒（校验失败一律
        ``400 {'error': msg}``，与 :meth:`search` 同形）。

        同名即覆盖（``overwrite`` 缺省 True，仿 ``save_config``）；显式 ``false`` 时同名
        存在只报 400，绝不悄悄吃掉旧预设。上限只数**本人**的行：``existing`` 命中说明
        这是更新，不占新名额，否则存满 50 条的用户再也改不了任何一条。
        """
        body = _json_object(request)
        if body is None:
            return Response({'error': '请求体必须是 JSON 对象'}, status=400)

        name = body.get('name')
        if not isinstance(name, str) or not name.strip():
            return Response({'error': '预设名称不能为空'}, status=400)
        name = name.strip()
        if len(name) > _PRESET_NAME_MAX:
            return Response(
                {'error': f'预设名称最长 {_PRESET_NAME_MAX} 字符，'
                          f'收到 {len(name)} 字符'}, status=400)

        raw_spec = body.get('spec')
        try:
            parse_spec(raw_spec)
        except SearchSpecError as exc:
            return Response({'error': f'搜索条件不合法：{exc}'}, status=400)

        mine = SftpSearchPreset.objects.filter(owner=request.user)
        existing = mine.filter(name=name).first()
        if existing is not None and _is_false(body.get('overwrite', True)):
            return Response({'error': f'预设「{name}」已存在'}, status=400)
        if existing is None and mine.count() >= PRESET_MAX_PER_USER:
            return Response(
                {'error': f'预设数量已达上限 {PRESET_MAX_PER_USER} 条，'
                          f'请先删除不再使用的预设'}, status=400)

        # ``owner`` 必须在 kwargs 里显式传：queryset 上的 filter 条件不进 INSERT
        # （``update_or_create`` 只把 kwargs 当创建字段）。少写它就是 owner_id NULL 的
        # IntegrityError → 500 —— 由 tests_search_preset 的落库断言抓到过。
        preset, created = SftpSearchPreset.objects.update_or_create(
            owner=request.user, name=name, defaults={'spec': raw_spec})
        return Response(self._preset_dict(preset), status=201 if created else 200)

    @action(detail=False, methods=['post'], url_path='search_presets/delete',
            url_name='delete-search-preset')
    def delete_search_preset(self, request):
        """``POST /sftp/search_presets/delete/``，体 ``{id}``。

        ``owner`` 与 ``id`` 一起进 ``filter``：别人的预设在这层就查不到，于是「删除他人
        预设」的表现是 404 而不是 200 —— 不给「存在但无权限」留一条可被探测的分支
        （仿 ``SftpConfigOwnerIsolationTests`` 钉住的既有契约）。
        """
        body = _json_object(request)
        if body is None:
            return Response({'error': '请求体必须是 JSON 对象'}, status=400)

        raw_id = body.get('id')
        try:
            preset_id = int(raw_id)
        except (TypeError, ValueError):
            return Response({'error': f'id 必须是整数，收到 {raw_id!r}'}, status=400)

        deleted, _detail = SftpSearchPreset.objects.filter(
            owner=request.user, id=preset_id).delete()
        if not deleted:
            return Response({'error': '未找到预设'}, status=404)
        return Response({'deleted': True})
