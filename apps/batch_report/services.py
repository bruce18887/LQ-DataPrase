"""批次良率汇总的可复用计算（从 views.py 抽出，供 API 与 HTML 报告共用）。"""

import re
from collections import defaultdict

from apps.datafiles.models import DataFile
from apps.datafiles.services import get_cached_parsed_file
from apps.analysis.services.statistics import (
    calculate_fail_bin_statistics, get_site_column,
    get_bin_column_name, compute_site_yield_data, compute_uph,
    compute_pass_yield, compute_yield_trend,
)
from apps.batch_report.aggregation import aggregate_bin_site_table, aggregate_uph
from apps.batch_report.phase_parsing import (
    detect_phase, phase_sort_key, stage_of, stage_sort_key,
)


class BatchNotAvailableError(Exception):
    """批次不存在 / 无文件 / 无法解析时抛出（视图据此返回 404）。"""


def build_phase_summary(phases):
    """Aggregate phases by base phase name (e.g. CP1, FT1, RT1, QA1).
    CP phases: each wafer is independent, so summary shows CP1 aggregate.
    FT/QA/RT: multiple files per phase, aggregate totals.
    """
    groups = defaultdict(lambda: {'total': 0, 'pass': 0, 'fail': 0, 'files': []})
    for p in phases:
        key = p['phase']  # e.g. CP1, FT1, QA1, RT1
        groups[key]['total'] += p['total']
        groups[key]['pass'] += p['pass_count']
        groups[key]['fail'] += p['fail_count']
        groups[key]['files'].append(p['filename'])

    summary = []
    for phase_name, data in groups.items():
        yield_pct = round(data['pass'] / data['total'] * 100, 2) if data['total'] > 0 else 0
        summary.append({
            'phase': phase_name,
            'stage': stage_of(phase_name),
            'file_count': len(data['files']),
            'total': data['total'],
            'pass_count': data['pass'],
            'fail_count': data['fail'],
            'yield_pct': yield_pct,
        })

    # Sort by same phase order
    summary.sort(key=lambda s: phase_sort_key(s['phase']))
    return summary


# 兼容旧名（原 _build_phase_summary）
_build_phase_summary = build_phase_summary


def compute_batch_yield_data(user, batch_name, *, for_html_report=False):
    """组装批次良率 payload（`/batch-report/batch_yield_data/` 响应体同形）。

    批次无文件 / 全部无法解析时抛 BatchNotAvailableError。

    ``for_html_report`` 决定那四段**只有 HTML 报告读**的分区
    （``trend_data`` / ``bin_distribution`` / ``bin_table_data`` /
    ``bin_site_columns``，读点见 ``apps/export/html_report/batch.py`` 的
    ``payload.get(...)``）是**算出来**还是**留空**：
    ``True`` ⇒ 四把都在函数末尾那唯一一处 ``if for_html_report:`` 里计算并写入，
    「绑定制」与「消费制」同块、不可能分叉（先前分在两块、另配两行兜底默认值的那个
    形状已随 2026-10-30 审查 Minor 3 合并掉）；``False`` ⇒ 同一处 ``else`` 只写
    **空占位**（``{}`` / ``[]``），一条计算都不跑。

    为什么 JSON 分支还带着这五把 key（2026-10-31 修正批）：D3（``d203ca1``）把 JSON
    响应从 14 把删成 9 把，而计划 Task D3 Step 2 的硬口径是「响应 JSON 键集合不变」、
    Global Constraints 又写着「改响应字段属契约变更、必须与前端同批改」—— 那批没动前端
    ⇒ 键集合先恢复。**恢复的是键，不是数据**：``trend_data={}``、
    ``site_pass_data`` / ``bin_distribution`` / ``bin_table_data`` / ``bin_site_columns``
    四把 ``[]``，任何按实值用它们的调用方拿到的都是空。判据（键集合 14 把、空值与类型、
    两条 ``not_called`` spy、占位每次新建）在
    ``test/backend/test_batch_report_payload.py``；HTML 产物字节另有
    ``test/backend/test_batch_report_html_artifact.py``。

    HTML 那侧另有一道入口守卫：``build_batch_html_report`` 认 ``site_pass_data`` 这把
    **只有 JSON 形状才带**的键来拦「忘了开开关」的载荷（键在不在已分不出两形状，因为
    JSON 那侧现在也带那四把空占位），外加「连 ``bin_site_columns`` 都没有 ⇒ 不是本函数
    产物」那一半；不放它渲染出一份只是少三块的报告。

    **这两段的账现在两分支都不付**（计划 Step 3 的完整口径，2026-10-30 补齐）：
    趋势输入 ``file_data_list`` 带的是循环里**已经算好的** ``bin_stats``/``total``，
    不带 ``df`` ⇒「每文件第二遍全量 bin 统计」（``apps/analysis/services/statistics/``
    ``trends.py`` 的 ``_bin_stats_and_total`` 先前那句按 ``df`` 现算的 fallback）与
    「批次内每个文件的 DataFrame 同时驻留」一起消失，JSON 分支与 HTML 分支同界。
    于是 ``for_html_report=False`` 省的**只是那四把分区本身的构造与体积**
    （``aggregate_bin_site_table`` + ``bin_agg`` 累计 + SPC 那趟 O(文件数) 的均值/标准差），
    别再写成「省一趟全量统计」或「省一批帧」。

    ``site_pass_data`` 是**纯形状兼容**：它**两分支都没有读者**（前端那两处命中是
    ``batchAggregation.ts`` 里描述「同构」的注释文字），所以 JSON 那侧只给空占位，
    HTML 那侧连键都不带 —— 报告不读它，就不为它加一笔无消费者的字段。
    """
    files = DataFile.objects.filter(
        owner=user, file_type='batch', batch_name=batch_name
    ).order_by('id')

    if not files.exists():
        raise BatchNotAvailableError('批次无文件')

    phases = []
    file_data_list = []
    bin_agg = defaultdict(int)
    all_sites = set()

    for idx, df_obj in enumerate(files):
        df, metadata, fmt = get_cached_parsed_file(df_obj.id, user.pk, df_obj)
        if df is None:
            continue

        total = df.shape[0]
        bin_stats = calculate_fail_bin_statistics(df, metadata)
        yield_result = compute_pass_yield(bin_stats, total)
        pass_count = yield_result['pass_count']
        fail_count = yield_result['fail_count']
        yield_pct = yield_result['yield_pct']

        bin_info = []
        for bin_name, binfo in bin_stats.items():
            count = binfo.get('count', 0)
            pct = binfo.get('percentage', 0)
            bn = str(bin_name)
            if for_html_report:
                # bin_agg 只喂 bin_distribution（HTML 的 Pareto 图）。
                bin_agg[bn] += count
            bin_info.append({
                'name': bn,
                'value': count,
                'pct': f"{pct:.2f}%",
                'sites': {},
            })

        # Site yield
        site_col = get_site_column(df)
        site_yields = {}
        site_total_map = {}
        site_pass_map = {}
        if site_col:
            bin_col = get_bin_column_name(df_obj.format_type)
            if bin_col in df.columns:
                yd = compute_site_yield_data(df, bin_col, site_col)
                for d in yd.get('yield_data', []):
                    site = d['Site']
                    site_yields[site] = d['Yield']
                    site_total_map[site] = d.get('Total', 0)
                    site_pass_map[site] = d.get('PassCount', 0)
                    all_sites.add(site)

                # Populate per-bin site data
                site_breakdown = yd.get('site_breakdown', {})
                for bi in bin_info:
                    for site in all_sites:
                        bi['sites'][site] = site_breakdown.get(site, {}).get(bi['name'], 0)

        # Detect phase type from filename (compound > standard > short filename fallback)
        phase_type = detect_phase(df_obj.filename)

        # Extract WAFER_ID from CP filenames: _05_CP1_ → 05
        wafer_id = ''
        if phase_type.startswith('CP'):
            wm = re.search(r'_(\d{2})_CP', df_obj.filename.upper())
            if wm:
                wafer_id = wm.group(1)

        # UPH per phase
        uph_data = compute_uph(df, metadata)

        phases.append({
            'filename': df_obj.filename,
            'phase': phase_type,
            'stage': stage_of(phase_type),
            'wafer_id': wafer_id,
            'lot_id': metadata.get('lot_id', '') or df_obj.program_name or '-',
            'total': total,
            'pass_count': pass_count,
            'fail_count': fail_count,
            'yield_pct': yield_pct,
            'start_time': metadata.get('start_time', '') or (str(df_obj.created_at)[:19] if hasattr(df_obj, 'created_at') else '-'),
            'end_time': metadata.get('end_time', '') or '-',
            'operator': metadata.get('operator', '') or '-',
            'station': metadata.get('station', '') or '-',
            'device_name': metadata.get('device_name', '') or '-',
            'tester_type': metadata.get('tester_type', '') or '-',
            'test_type': metadata.get('test_type', '') or '-',
            'total_test_time': metadata.get('total_test_time', '') or '-',
            'handler': metadata.get('handler', '') or '-',
            'site_yields': site_yields,
            'site_total': site_total_map,
            'site_pass': site_pass_map,
            'bin_info': bin_info,
            'program_name': df_obj.program_name or '',
            'uph': uph_data,
        })

        if for_html_report:
            # 趋势图的输入：把循环里**已经算好的** ``bin_stats``/``total`` 带下去，
            # 不带 ``df``/``metadata``。``compute_yield_trend`` **只**认这份形状
            # （``apps/analysis/services/statistics/trends.py`` 的 ``_bin_stats_and_total``
            # 直接按 ``file_data['bin_stats']``/``['total']`` 取，没有按 ``df`` 现算的
            # fallback 可走）⇒ 这里少带一趟全量 bin 统计，也就没有理由把批次里
            # 每个文件的 DataFrame 攒在一份列表里 ——「同时驻留整批帧」这条账在
            # **两个分支都不存在**（绊线：JSON 分支
            # ``test_json_branch_retains_no_dataframe_as_performance_tripwire``、
            # HTML 分支 ``test_html_branch_retains_no_dataframe_as_performance_tripwire``，
            # 两分支的「每文件只一趟 bin 统计」由
            # ``test_both_branches_run_one_bin_statistics_pass_per_file_as_performance_tripwire``
            # 钉；入参形状本身由 ``test_html_trend_input_carries_precomputed_bin_stats_and_no_frame``
            # 与 ``test/backend/test_bin_trend_yield.py`` 的反垫片用例两头夹）。
            # JSON 分支不往这份列表里 append 任何东西（那四把分区在它那边只是空占位，
            # 见函数末尾的 else）：留在上面的只是一只空 list / 空 defaultdict，没有内容。
            file_data_list.append({
                'bin_stats': bin_stats,
                'total': total,
                'file_id': df_obj.id,
                'filename': df_obj.filename,
                'timestamp': str(getattr(df_obj, 'created_at', '')),
            })

    if not phases:
        raise BatchNotAvailableError('无法解析批次文件')

    # KPI — overall yield (CP+FT input based, 2D3D counts as FT)
    cp_bin1 = sum(p['pass_count'] for p in phases if p['phase'].startswith('CP'))
    ft_bin1 = sum(p['pass_count'] for p in phases if p['phase'].startswith('FT') or p['phase'] == '2D3D')
    rt_bin1 = sum(p['pass_count'] for p in phases if p['phase'].startswith('RT'))
    input_total = sum(p['total'] for p in phases if p['phase'].startswith('CP') or p['phase'].startswith('FT') or p['phase'] == '2D3D')
    if input_total == 0:
        input_total = sum(p['total'] for p in phases)
    overall_yield = round((cp_bin1 + ft_bin1 + rt_bin1) / input_total * 100, 2) if input_total > 0 else 0

    total_all = sum(p['total'] for p in phases)
    pass_all = sum(p['pass_count'] for p in phases)
    fail_all = total_all - pass_all

    # 良率趋势（SPC）/ Bin 分布这几把 key 的**全部**写入都在函数末尾那一对互斥的
    # ``if for_html_report:`` / ``else:`` 里（HTML 算实值、JSON 写空占位）—— 这里曾经有一处
    # 独立的 ``if`` 加两行兜底默认值（``trend = {}`` / ``bin_distribution = []``），因为绑定与
    # 消费分在两块里、两处判据漂开就是 ``UnboundLocalError``。合并成一处之后那个形状
    # 不存在了，默认值与钉它的源码改写用例一起删（2026-10-30 审查 Minor 3）。

    # Site matrix table data
    sorted_sites = sorted(all_sites)
    site_matrix = []
    for p in phases:
        row = {'phase': p['phase'], 'stage': p['stage'], 'wafer_id': p.get('wafer_id', '')}
        for site in sorted_sites:
            st_val = p['site_total'].get(site, 0)
            sp_val = p['site_pass'].get(site, 0)
            sy = p['site_yields'].get(site, 0)
            try:
                sy_val = float(sy)
                row[f'{site}_yield'] = f"{sy_val:.2f}%" if st_val > 0 else 'N/A'
            except (ValueError, TypeError):
                row[f'{site}_yield'] = 'N/A'
            row[f'{site}_ratio'] = f"{sp_val}/{st_val}"
        row['all_yield'] = f"{p['yield_pct']:.2f}%"
        row['all_ratio'] = f"{p['pass_count']}/{p['total']}"
        site_matrix.append(row)

    # Sort phases by semiconductor test flow: CP → UIS → FT/BF → RT → QA → 2D3D
    phases.sort(key=lambda p: phase_sort_key(p['phase']))

    # Stage-level yield stats (CP/UIS/FT 分别统计): aggregate phases by flow stage
    stage_groups = defaultdict(lambda: {'total': 0, 'pass': 0, 'fail': 0, 'files': 0})
    for p in phases:
        stage = stage_of(p['phase'])
        stage_groups[stage]['total'] += p['total']
        stage_groups[stage]['pass'] += p['pass_count']
        stage_groups[stage]['fail'] += p['fail_count']
        stage_groups[stage]['files'] += 1
    stage_yields = []
    for stage, data in stage_groups.items():
        yield_pct = round(data['pass'] / data['total'] * 100, 2) if data['total'] > 0 else 0
        stage_yields.append({
            'stage': stage,
            'file_count': data['files'],
            'total': data['total'],
            'pass_count': data['pass'],
            'fail_count': data['fail'],
            'yield_pct': yield_pct,
        })
    stage_yields.sort(key=lambda s: stage_sort_key(s['stage']))

    # QA validation
    qa_checks = []
    qa1 = next((p for p in phases if re.match(r'^QA1(?:[_-]|$)', p['phase'], re.IGNORECASE)), None)
    qa_phases = [p for p in phases if p['phase'].startswith('QA')]
    if qa1 and len(qa_phases) >= 1:
        all_qa_pass = sum(p['pass_count'] for p in qa_phases)
        diff = all_qa_pass - qa1['total']
        qa_names = [p['phase'] for p in qa_phases]
        qa_checks.append({
            'check': f"QA系列Pass总数 ({', '.join(qa_names)}) ↔ QA1 Total",
            'expected': str(qa1['total']),
            'actual': str(all_qa_pass),
            'status': '✅ 一致' if diff == 0 else f'⚠️ 差异 {diff} 颗',
        })

    # Batch-level Bin×Site cross table + aggregated UPH (reuse single-file
    # analysis components in the batch report). Pure helpers in aggregation.py.
    #
    # ``bin_table_data``/``bin_site_columns`` 这两把只有 HTML 报告读：批次页那张
    # Bin×Site 表是前端自己按当前阶段现算的（``frontend/src/utils/batchAggregation.ts``
    # 的 ``aggregateBinSiteTable``，吃 ``phases[].bin_info[].sites`` —— 所以那些不能被删，
    # 判据在 ``test_phases_still_carry_per_bin_site_data``）。批级交叉表是它的同构物，
    # 不是它的输入。
    batch_uph = aggregate_uph(phases)

    payload = {
        'batch_name': batch_name,
        'kpi': {
            'file_count': len(phases),
            'input_total': input_total,
            'total': total_all,
            'pass': pass_all,
            'fail': fail_all,
            'overall_yield': overall_yield,
            'yield_pct': overall_yield,
        },
        'phases': phases,
        'phase_summary': _build_phase_summary(phases),
        'stage_yields': stage_yields,
        'sorted_sites': sorted_sites,
        'site_matrix': site_matrix,
        'uph': batch_uph,
        'qa_checks': qa_checks,
    }
    if for_html_report:
        # HTML 那四段分区的**唯一**一处计算与写入：绑定与消费同块 ⇒ 不存在「两处判据分叉 ⇒
        # ``UnboundLocalError``」这个形状，也就不需要 ``trend`` / ``bin_distribution``
        # 的兜底默认值。只有 HTML 报告读这四把 key（``apps/export/html_report/batch.py``
        # 的 ``payload.get(...)``，那边还有一条入口守卫拦「忘了开开关」的载荷）；
        # 「每文件第二趟全量 bin 统计」与「整批 DataFrame 驻留」两分支都已经不存在（趋势输入
        # 带的是算好的 bin_stats，见循环里那段注释），HTML 这侧多付的只是那四把 key 的构造与体积。
        payload['trend_data'] = compute_yield_trend(file_data_list)
        # Bin 分布（HTML 的 Pareto 图）；bin_agg 只喂这一把 key。
        payload['bin_distribution'] = [
            {'name': bn, 'value': bin_agg[bn]}
            for bn in sorted(bin_agg.keys(), key=lambda x: (x not in ('1', 'Bin1'), x))
        ]
        payload['bin_table_data'], payload['bin_site_columns'] = \
            aggregate_bin_site_table(phases, sorted_sites)
    else:
        # **形状兼容空键**（2026-10-31 修正批）：这五把在 HEAD（``d203ca1`` 之前）的响应里
        # 一直存在，D3 把它们整个删掉属契约变更（计划的 Task D3 Step 2 写的就是「响应 JSON
        # 键集合不变」），前端那批又没跟着改 ⇒ 键补回来。
        # 诚实口径：**只补键，不补账**。这里一个计算都没接回来 —— ``trend_data`` 恒 ``{}``、
        # 其余四把恒 ``[]``（类型与 HEAD 那五把实值的类型一致），``compute_yield_trend`` 与
        # ``aggregate_bin_site_table`` 在这条分支一次都没被调用，``file_data_list``/``bin_agg``
        # 也停在空容器上没有被填过。所以这不是「恢复了旧的 trend/partition 内容」，任何人把它们
        # 当实值用都会拿到空。要恢复**值**：先给出 JSON 那侧的读者，并单开一条契约/性能任务。
        # 每调用各建一份（都是可变容器，共用一份模块级常量会让一个调用方写脏全站）。
        # HTML 那侧**不带** ``site_pass_data``：报告不读它，不为 JSON 的形状兼容加无消费者的
        # 字段 —— 也正因为它只有 JSON 形状才有，``build_batch_html_report`` 拿它认门。
        # 判据：test/backend/test_batch_report_payload.py 的 JSON_COMPAT_KEYS 那组
        # （键集合 14 把 + 空值与类型 + 两条 not_called spy + 每次新建）。
        payload['trend_data'] = {}
        payload['site_pass_data'] = []
        payload['bin_distribution'] = []
        payload['bin_table_data'] = []
        payload['bin_site_columns'] = []
    return payload
