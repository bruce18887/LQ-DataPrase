"""DataFile 的**批量取行**口径：按 owner 过滤、按 PK 分块、坏 id 剔在查询之外。

为什么单独一份：这条取数在仓里原本有**两处逐字近似**的实现
（``apps/analysis/views/_helpers.py`` 的 ``_load_files_from_request`` 与
``apps/batch_report/views.py`` 的 ``_owned_files_by_pk``，2026-10-30 D3 审查 Important 3
指出）。两者的差别只在**调用方**拿到缺失 id 之后怎么办（analysis 静默跳过、
batch_report 判 404），取数本身四条口径完全同形 —— 而同形的两份实现会各自漂：
分块容量、``owner`` 预留的参数个数、越界整数拦不拦，任何一处改动都得记得改两处。
本模块收的是**取数**；404 还是跳过留在各自调用点。

四条非显然口径（改动本文件前先读）：

1. **非整数与超出主键合法范围者剔除**。逐条精确 ``pk=`` 查询会把它们拒成
   ``None``/404，而 ``IN`` **不校验范围** —— 越界整数交给适配器可能是整批 500
   （``BigAutoField`` 的合法区间是 ±2^63，``2**63-1`` 过、``2**63`` 不过）。
   剔掉 ⇒ 它们不出现在结果 dict 里 ⇒ 调用方按缺失处理 ⇒ 状态码与逐条查时一致。
2. **先去重再查**（``dict.fromkeys`` 保首次出现序），批量取本身不保重复行。
3. **按连接上报的 ``max_query_params`` 分块**，并给 ``owner`` 过滤预留 1 个参数
   （``in_bulk`` 只给 id 列表预算位，不预留就会在恰好顶到上限时溢出）。
   上限由后端报，不写死数字（换数据库就漂）；后端报 ``None``（无上限）时一次打完。
4. **空输入 ⇒ 一条 SELECT 都不发**（含「全是坏 id」那一格）。
"""

from django.db import connections

from apps.datafiles.models import DataFile


def valid_file_ids(file_ids):
    """归一批量入参：剔除非整数与超出主键合法范围者，返回**保序含重复**的 id 列表。

    宽异常是**刻意的**，不是偷懒：这一格的判据来自 analysis 侧那批 A3 用例
    （``test/backend/test_analysis_load_db_count.py``），它们喂的是
    ``'bad'`` / ``None`` / ``{}`` / ``[]`` / ``'1.5'`` / ``float('inf')`` /
    ``float('nan')`` / ``2**63`` / ``-(2**63)-1`` 的混合物 —— ``ValueError`` /
    ``TypeError`` / ``OverflowError`` / ``ValidationError`` 四族都会从这里过，
    任何一个漏出去就把「一个坏 id」升级成「整批 500」。

    幂等：对已经归一过的 id 列表再调一次是同一份结果，所以调用方可以先取这份
    有序列表、再把它交给 ``owned_files_by_pk``。
    """
    valid = []
    for file_id in file_ids:
        try:
            file_id = int(file_id)
            DataFile._meta.pk.run_validators(file_id)
        except Exception:
            continue
        valid.append(file_id)
    return valid


def owned_files_by_pk(user, file_ids):
    """一次按 owner 批量取，返回 ``{pk: DataFile}``（N 个 id ⇒ ⌈N/块容量⌉ 条 SELECT）。

    坏 id 的处置见模块 docstring 的第 1 条；**拿到缺失者之后做什么不属于这里**：
    ``apps/analysis/views/_helpers.py`` 跳过它，``apps/batch_report/views.py`` 用它判 404。
    返回的 dict 不保证顺序（``in_bulk`` 的产物），需要保序或保重复的调用方自己按
    输入序回放（两侧现在都是这么做的）。
    """
    unique_ids = list(dict.fromkeys(valid_file_ids(file_ids)))
    if not unique_ids:
        return {}
    queryset = DataFile.objects.filter(owner=user)
    max_params = connections[queryset.db].features.max_query_params
    # in_bulk 只给 id 列表预算位，给 owner 过滤留 1 个。
    chunk_size = max_params - 1 if max_params else len(unique_ids)
    found = {}
    for offset in range(0, len(unique_ids), chunk_size):
        chunk = unique_ids[offset:offset + chunk_size]
        found.update(queryset.in_bulk(id_list=chunk))
    return found
