"""视图层错误的唯一出口 —— 与全局异常处理器同形。

``apps/common/exceptions.py`` 把所有异常归一化成 ``{code, message, detail}``，但视图里的
守卫分支曾各写各的：155 处 ``Response({'error': <机器码>})``、登录侧的
``{code, detail}``、SFTP 连接侧的 ``{status: 'error', message}`` —— 前端因此必须在
``utils/error.ts`` 里留一条 ``data.error`` 兜底分支，而这个键名又和「成功响应体里的
per-item error 字段」撞名（架构评审 P1-5）。

本模块只负责**视图主动 return 的错误**；未捕获异常仍走全局处理器。
"""
from rest_framework.response import Response


def error_response(code, detail=None, status=400, **extra):
    """构造与全局处理器同形的错误响应 ``{code, message, detail, **extra}``。

    * ``code``   —— 稳定机器码，是前端 ``ERROR_CODE_MAP`` 的键，也是用例断言的对象；
      改名等于改契约，只能增不能顺手改。
    * ``detail`` —— 可读补充（中文句子或结构化字段）。是字符串时同时充当 ``message``，
      让不带前端映射的调用方（curl / 脚本 / Playwright）也能读出话。
    * ``extra``  —— 端点特有的上下文（``requested`` / ``missing`` / ``skipped`` /
      ``remaining_attempts`` 等）。**保留原键名**：前端与 e2e 已在按名读取。

    文案的单一来源仍在前端 ``ERROR_CODE_MAP``；只有 ``detail`` 缺失时才回落到该表，
    所以后端不要在这里再造一份中文表 —— 两份必漂（见 lessons 2026-09-19）。
    """
    body = {
        'code': code,
        'message': detail if isinstance(detail, str) and detail else None,
        'detail': detail,
    }
    body.update(extra)
    return Response(body, status=status)
