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

import logging
from typing import Any, Dict, Iterator

from django.http import StreamingHttpResponse
from rest_framework.decorators import action
from rest_framework.response import Response

from .downloads import download_events_to_sse
from .search.connect import SearchSession, SearchSessionError
from .search.contracts import SearchSpec, SearchSpecError, parse_spec
from .search.runner import SearchRunner

logger = logging.getLogger(__name__)

# 「用户没连接」在 ``connect.py`` 里的形状：``SearchSession._credentials()`` 两条消息
# （缓存为空 / 缓存后端读失败）都带 ``no cached session (not connected)``。
_NOT_CONNECTED_MARKERS = ('no cached session', 'not connected')


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

    @action(detail=False, methods=['post'])
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
