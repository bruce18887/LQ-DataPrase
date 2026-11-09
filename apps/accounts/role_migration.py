"""viewer → user/administrator 的归并内核。

现由迁移 `0012_normalize_user_roles`（历史库升级）调用；Task 3 会把 `seed_users`
接成第二个调用点（dev/e2e 夹具库的幂等兜底）。收模型类为参数，迁移里传的是
RunPython 的历史模型，测试里传的是真实模型 —— 因此本模块**不得 import models**
（一旦被 models 侧引用就成了真实循环；而迁移若在 RunPython 里直接用当前模型类，
读到的也不是 0011 那一刻的状态，而是未来 schema）。
"""

VIEWER = 'viewer'
ADMINISTRATOR = 'administrator'
USER = 'user'


def normalize_roles(UserModel):
    """把 viewer 归并进两级模型，并补一遍 superuser→administrator。

    返回三类计数，调用方据此打印，别静默改数据。
    顺序有讲究：先升 superuser 的 viewer（否则第一步就把它们并成 user，
    第三步再升上来会把计数算错 —— 实测反序跑同一份夹具，数据逐行相同但
    计数变成 viewer_to_user=2 / superuser_promoted=2）。
    两条 superuser 分支都带上 is_staff=True：spec §4 第 3 步要对齐启动期
    `_promote_superusers`，它同时写 role 与 is_staff，且只挑 `role != administrator`
    的行 —— 0012 若只改 role，被改过的那两行启动期再也看不见，is_staff 就永久
    留在 False，而 Django admin 的准入是 `is_active and is_staff`
    （`AdminSite.has_permission`，django/contrib/admin/sites.py:208）。对齐范围仅
    限「挑哪些行、写哪些值」，不含 save/信号语义：这里走 queryset.update()，与
    spec §4「批量改为」一致。

    调用方需要知道的另外两条：
    * 三支的行集互斥（第 2 支只看还剩的 viewer，第 3 支排除已是 administrator 的
      且非 superuser 的行进不来），所以 `sum(counts.values())` 就等于被改动的行数
      —— 判「有没有改数据」请用 `any(counts.values())`，别挑单个键。
    * 幂等：第二次调用三项全 0（Task 3 把 `seed_users` 接成第二个调用点时靠这条
      保证每次 e2e 预跑不会重复出声）。
    """
    to_admin = UserModel.objects.filter(
        role=VIEWER, is_superuser=True
    ).update(role=ADMINISTRATOR, is_staff=True)
    to_user = UserModel.objects.filter(role=VIEWER).update(role=USER)
    promoted = UserModel.objects.filter(is_superuser=True).exclude(
        role=ADMINISTRATOR
    ).update(role=ADMINISTRATOR, is_staff=True)
    return {
        'viewer_to_administrator': to_admin,
        'viewer_to_user': to_user,
        'superuser_promoted': promoted,
    }
