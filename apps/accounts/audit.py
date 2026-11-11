"""账号安全事件写入器。

spec §5.4 给了五条规则，本模块落地成下面四条（第四条不在 spec 里，是本仓自己加的
序列化边界，理由见该条）：

1. 业务动作永远优先 —— 审计写失败只留一条 warning（带 traceback），绝不外抛。
   判据在 `test/backend/test_audit_writer.py`，两个注入点各管一件事，不重复：
   `AuditEvent.save` 那条量「守卫罩不罩得住真实的 INSERT」，`audit._insert` 那条量
   「咽下来之后外层业务事务还在不在」。留痕写法与 `apps/sftp/views.py:288-293`
   （SFTP 上次访问记录）同一个口径：`try/except Exception` + `logger.warning(exc_info=True)`。
2. 外层有事务 → 开 savepoint；外层是 autocommit → **不**包 atomic。两边都不是偏好：
   * savepoint 这支：真·DB 错误时少这一层，Django 自己的 `Model._save` 对无父表模型包的
     那层 `transaction.mark_for_rollback_on_error()` 会把 `connection.needs_rollback` 置 True，
     而没有 savepoint 可退时 `Atomic.__exit__` 就把**整笔**外层事务标死 —— 改密/重置的业务行
     跟着没。引用的都是 Django 6.0.9 的符号名（`.venv` 不入库，按行号引会静默腐烂），
     本机实测形状与判据见 `test_audit_writer.py` 模块头那张 2×2 四格表和
     `test_real_insert_failure_keeps_outer_business_transaction`。
   * autocommit 这支：包一层 `atomic()` 的净代价是 BEGIN/COMMIT 两条（本机实测裸写
     1 条 INSERT vs 包一层的 BEGIN/INSERT/COMMIT 3 条，判据 `WriterAutocommitShapeTests`），
     而 `AUDIT_EVENTS` 十个码里挂在登录上的有 3 个（`login_success` / `login_failure` /
     `account_locked`，spec §5.2 触发点表逐行可数）—— Task 6 已接线，每次会话至少发一条，
     剩下 7 个才是低频管理动作。`test_login_path_statements.py` 的形状判据已按实跑重钉
     （登录在 `TestCase` 里走 savepoint 支 ⇒ 那边钉的是 DML 序列 + 一记含簿记的完整序列，
     autocommit 支仍由本文件的 `WriterAutocommitShapeTests` 量）。
3. username 快照一律截到列宽（`USERNAME_MAX_LENGTH`，从模型字段读），非字符串取值落空串
   而不是 `repr()`；未知账号的探测输入不许把登录请求带崩。判据
   `test_overlong_username_is_truncated_not_raised` 与
   `test_non_string_username_snapshot_is_empty`（端点侧那一半自 Task 6 起也有判据：
   `test_audit_login_events.py::test_overlong_username_is_truncated_not_500`）。
4. `detail` 必须 JSON 可序列化。这条不是 spec §5.4 的规则，是量出来的边界：传 datetime/
   Decimal 时整行写不进去（`TypeError` 被咽掉 ⇒ 事件静默丢失），而 spec §5.3 约定 detail 里
   本来就该写 ISO 字符串。调用方必须自己转（Task 6 的 `locked_until` 交的是 `.isoformat()`），
   别指望写入器兜住 —— 端点侧那一半的判据只有 `test_audit_login_events.py`
   `::test_fifth_failure_records_failure_then_lock` 一条：全仓只有它把 datetime 交给过
   `detail`，其余分支交上去的都是字符串与整数，行照样落得了。
   机制侧判据 `test_unserializable_detail_drops_the_row_and_is_logged`。
"""

import ipaddress
import logging

from django.db import transaction

from .models import AuditEvent

logger = logging.getLogger(__name__)

# 事件码的唯一清单 = spec §5.2 那十个（触发点表逐行对得上）。
# 前端那份标签表（frontend/src/utils/audit.ts）与本元组双向钉死：绊线是
# frontend/test/unit/audit.spec.ts，它刮这份清单跟前端比集合，两侧各自多出来的码都会被点名
# —— 加/删事件码必须两边一起改。码名写错这里只留 warning、不拒写，所以未登记的码会漏到前端，
# 前端对它的行为是回退显示原码；那条回退、以及「本清单只能长成下面这种形状（顶格块首、
# 每项独占一行带逗号，否则绊线当场抛而不是安静少刮一个码）」，都由同一条绊线钉着。
# 本元组自身的判据仍是 test_audit_writer.py::WriterTests::test_event_list_is_the_single_source。
AUDIT_EVENTS = (
    'login_success',
    'login_failure',
    'account_locked',
    'account_unlocked',
    'password_changed',
    'password_reset',
    'user_created',
    'user_updated',
    'user_deleted',
    'system_paths_changed',
)

# 登录失败的四种可区分原因（spec §5.3），detail.reason 的取值域。
LOGIN_FAILURE_REASONS = (
    'unknown_user', 'bad_password', 'account_disabled', 'account_locked',
)

# 列宽从模型字段读，不在这里抄第二份：收窄列定义时本常量的判据会红，
# 而不是让 _snapshot 安静地截出比列宽更长的值（实测抄死 150 时收窄列 10 例全绿）。
USERNAME_MAX_LENGTH = AuditEvent._meta.get_field('actor_username').max_length


def _snapshot(value):
    """快照列只收字符串，并截到列宽：未知账号的探测输入不许把登录带崩。"""
    if not isinstance(value, str):
        return ''
    return value[:USERNAME_MAX_LENGTH]


def _client_ip(request):
    raw = (request.META.get('REMOTE_ADDR') or '') if request else ''
    if raw in ('127.0.0.1', '::1'):
        # 本机反代转发时 REMOTE_ADDR 恒为回环；XFF 最右一条是 nginx 追加的
        # 真实客户端地址，左侧条目可被客户端伪造，不能取。
        xff = request.META.get('HTTP_X_FORWARDED_FOR') or ''
        if xff:
            raw = xff.split(',')[-1].strip()
    try:
        ipaddress.ip_address(raw)
    except ValueError:
        return None
    return raw


def _insert(*, event, actor, actor_username, target, target_username, ip, detail):
    AuditEvent.objects.create(
        event=event,
        actor=actor,
        actor_username=actor_username,
        target=target,
        target_username=target_username,
        ip_address=ip,
        detail=detail or {},
    )


def _live(obj):
    """只把「有主键的实例」当 FK 交出去。

    `instance.delete()` 会把 pk 置 None（`apps/accounts/views.py` 的 destroy 就走这条），
    而无主键实例当关联值时 `Model.save()` 直接抛 `ValueError: save() prohibited to
    prevent data loss due to unsaved related object` —— 那异常被 best-effort 咽掉的
    结果是**整行没了**，快照也一起丢。所以 FK 交 None，快照列照常写：事件读得出
    「当时是谁对谁做了什么」，这正是 spec §5.1 把快照与 FK 分开存的目的。
    管不到的那一层要写清楚：pk 还在但行已不在库里（陈旧实例）时，本仓 SQLite
    `PRAGMA foreign_keys=1` 会让这笔 INSERT 抛 IntegrityError，而且是**外层提交时**
    抛在调用方身上，`record()` 罩不住。删除类事件因此必须走
    `record(request, 'user_deleted', target_username=name)`（Task 7 接线时照此办）。
    """
    return obj if obj is not None and obj.pk is not None else None


def record(request, event, *, actor=None, target=None, target_username=None,
           detail=None):
    """写一条审计事件。异常一律就地咽掉，绝不影响调用方。

    取用户、算快照、写库全在 `try` 里：`request.user` 这个属性本身就可能抛
    （DRF 的懒解析），那种异常落在 `try` 外面就违反「业务动作永远优先」。
    """
    try:
        user = actor if actor is not None else getattr(request, 'user', None)
        if user is not None and not getattr(user, 'is_authenticated', False):
            user = None
        if event not in AUDIT_EVENTS:
            # 只留痕不拒写：拒写会把「码名写错」升级成「事件丢失」，比留一条
            # 前端贴不出标签的行更糟。
            logger.warning('未登记的审计事件码：%r', event)
        fields = dict(
            event=event,
            actor=_live(user),
            actor_username=_snapshot(getattr(user, 'username', '')),
            target=_live(target),
            target_username=_snapshot(
                target_username or getattr(target, 'username', '')
            ),
            ip=_client_ip(request),
            detail=detail,
        )
        if transaction.get_connection().in_atomic_block:
            with transaction.atomic():
                _insert(**fields)
        else:
            _insert(**fields)
    except Exception:
        logger.warning('审计写入失败：event=%s target=%s', event,
                       target_username or getattr(target, 'username', ''),
                       exc_info=True)
