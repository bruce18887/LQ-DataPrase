#!/usr/bin/env python
"""20 人并发压测（只打 HTTP，不 mock）。

它回答的是方案 §3 那几条验收线：「一次长任务进行时，其他人的请求排多久」。
分两层：

    mixed   —— 20 个用户各发若干轮 {browse 首页, browse IRM 块, dashboard summary,
               files 列表, 写一次账号设置}，按端点报 P50/P95/max 与错误数。
    --heavy —— 在 mixed 正在跑的同时，另起一条重活（上传大文件 / 导出），
               看 P95 被抬到几倍。这就是 P2「拆开长写事务」和 P3「重活作业化」的验收形状。

跑法（两步，服务与压测用**同一个**隔离档，绝不碰真实库与真实 media）：

    # 1) 起一个隔离后端（端口先问过本机动态端口区间，见 docs/reference/testing-gates.md）
    LQDP_E2E_SLOT_DIR=test/perf-data DJANGO_SETTINGS_MODULE=config.settings.e2e_slot \
        .venv/Scripts/python.exe manage.py runserver 127.0.0.1:21099 --noreload

    # 2) 压测（另开一个 shell，同样带上这两个环境变量）
    LQDP_E2E_SLOT_DIR=test/perf-data DJANGO_SETTINGS_MODULE=config.settings.e2e_slot \
        .venv/Scripts/python.exe scripts/perf_load20.py --base http://127.0.0.1:21099

⚠ 进程模型口径：正式档**已拍板 = 方案 A**（systemd 跑 `standalone.py`，本质仍是单进程
`runserver --noreload` 多线程，见 `docs/reference/server-deployment.md` §3）。所以这份脚本量的
形态与生产一致；压不出的是「一个请求把单 worker 占满」那种停摆 —— 那要等换成方案 B
（gunicorn 同步 worker）再跑同一份脚本才会出现。脚本本身与服务器形态无关。

⚠ 压测会写库（建 20 个用户 + DataFile 行）与写 media（--heavy upload 会把大文件落盘）。
落盘面全在 `LQDP_E2E_SLOT_DIR` 下，跑完删那个目录即可；缺该环境变量时脚本直接拒绝启动。
"""

import argparse
import json
import os
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PASSWORD = 'x-perf-12345678'
BIG_REL = os.path.join(
    'Data', 'SampleData', 'Batch', 'FT', 'BP01-2605220057', 'R2605230015',
    'C01Q_BP01-2605220057_BPD93204__H0GG80#AAA12605220057_FT1-FT1-1_'
    'R2605230015_ETS083302_05272026.csv')
# mixed 场景每用户各一只 20MB 文件（常驻约 35MB）：20 人 ≈ 700MB，落在 1536MB 解析缓存
# 预算内，才量得出「已缓存的大文件打开 P95 < 400ms」那条验收线。
# 若这里换成 276MB 那只，20 人 = 9.2GB 工作集 ⇒ 缓存必然互相洗掉，量到的就是全冷解析
# —— 那是方案 §1 的另一个论点，用 --heavy upload 单独量，不要混进 mixed。
MID_REL = os.path.join(
    'Data', 'SampleData', 'Batch', 'FT', 'BP01-2605220057', 'R2605230015',
    'C01Q_BP01-2605220057_BPD93204__H0GG80#AAA12605220057_FT1-FT1-2_'
    'R2605230015_ETS150341_05272026.csv')

_lock = threading.Lock()
_samples = {}   # endpoint -> [ms]
_errors = {}    # endpoint -> {reason: count}


def record(endpoint, ms):
    with _lock:
        _samples.setdefault(endpoint, []).append(ms)


def record_error(endpoint, reason):
    with _lock:
        bucket = _errors.setdefault(endpoint, {})
        bucket[reason] = bucket.get(reason, 0) + 1


def pct(values, q):
    """P50/P95 —— 用排序取值，不用 numpy。n 小时 P95≈max，报数时把 n 一起打出来。"""
    if not values:
        return float('nan')
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return ordered[idx]


class Client:
    """一个用户 = 一个 token。只用标准库，避免给仓库加依赖。"""

    def __init__(self, base, token):
        self.base = base
        self.token = token

    def _call(self, method, path, *, body=None, raw_body=None, content_type=None,
              endpoint=None, expect_json=True):
        endpoint = endpoint or f'{method} {path}'
        req = urllib.request.Request(self.base + path, method=method)
        if self.token:
            req.add_header('Authorization', f'Bearer {self.token}')
        data = None
        if raw_body is not None:
            data = raw_body
            req.add_header('Content-Type', content_type)
        elif body is not None:
            data = json.dumps(body).encode('utf-8')
            req.add_header('Content-Type', 'application/json')
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, data=data, timeout=600) as resp:
                payload = resp.read()
            ms = (time.perf_counter() - t0) * 1000
            record(endpoint, ms)
            if not expect_json:
                return payload, ms
            return json.loads(payload.decode('utf-8')), ms
        except urllib.error.HTTPError as exc:
            ms = (time.perf_counter() - t0) * 1000
            detail = ''
            try:
                detail = exc.read().decode('utf-8', 'replace')[:300]
            except Exception:
                pass
            record_error(endpoint, f'HTTP {exc.code}')
            if 'database is locked' in detail:
                record_error(endpoint, 'database is locked')
            return None, ms
        except Exception as exc:  # 超时/连接断也是结果，不是脚本崩溃的理由
            ms = (time.perf_counter() - t0) * 1000
            record_error(endpoint, type(exc).__name__)
            return None, ms

    def get(self, path, **kw):
        return self._call('GET', path, **kw)

    def post(self, path, body=None, **kw):
        return self._call('POST', path, body=body, **kw)

    def put(self, path, body, **kw):
        """``/auth/settings/`` 只挂了 PUT（内部 partial=True），没有 PATCH。"""
        return self._call('PUT', path, body=body, **kw)


def multipart_body(field, filename, blob):
    """手搓 multipart/form-data —— 仓库里没装 requests，不为压测加依赖。"""
    boundary = f'lqdp{uuid.uuid4().hex}'
    head = (f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            f'Content-Type: application/octet-stream\r\n\r\n').encode('utf-8')
    tail = f'\r\n--{boundary}--\r\n'.encode('utf-8')
    return head + blob + tail, f'multipart/form-data; boundary={boundary}'


def seed(base, users, big_file_id_needed):
    """在隔离档里建用户、发 token，并把基线大文件登记成一只 DataFile（不发 HTTP）。

    直接走 ORM：登录接口有 throttle（base 档 20/min），20 个用户会被限流假红，
    而限流不是本脚本要量的东西。
    """
    import django
    django.setup()

    from django.conf import settings as dj_settings

    slot = os.environ.get('LQDP_E2E_SLOT_DIR', '').strip()
    if not slot:
        sys.exit('需要 LQDP_E2E_SLOT_DIR：本脚本会建用户/写 media，缺它就等于往真实库写。')
    print(f'隔离数据根 = {slot} · 库 = {dj_settings.DATABASES["default"]["NAME"]}', flush=True)

    from apps.accounts.models import User
    from apps.datafiles.models import DataFile

    created = 0
    for i in range(users):
        username = f'perf_u{i:02d}'
        user, made = User.objects.get_or_create(username=username)
        created += made
    print(f'用户 {users} 个（本轮新建 {created}）', flush=True)

    from rest_framework_simplejwt.tokens import RefreshToken

    path = os.path.join(ROOT, MID_REL)
    has_mid = os.path.exists(path)
    if big_file_id_needed and not has_mid:
        print(f'SKIP: 缺 {MID_REL}，browse/summary 场景无素材（样例数据不入库）', flush=True)

    pairs = []
    for i in range(users):
        username = f'perf_u{i:02d}'
        user = User.objects.get(username=username)
        token = str(RefreshToken.for_user(user).access_token)
        file_id = None
        if big_file_id_needed and has_mid:
            # 每个用户各登记一行 DataFile 指向同一个物理文件：browse/summary 都是
            # `owner=request.user` 取对象的，共用一行会让另外 19 个用户 404。
            row, _ = DataFile.objects.get_or_create(
                owner=user, filename=os.path.basename(path),
                defaults={'file_path': path, 'file_size': os.path.getsize(path),
                          'format_type': 'ETS88', 'status': 'ready',
                          'program_name': 'PERFBASE'})
            file_id = row.id
        pairs.append((token, file_id))
    print(f'素材：{users} 个用户各一只 datafile（指向同一物理文件）'
          f'{"，id 例 " + str(pairs[0][1]) if pairs and pairs[0][1] else ""}', flush=True)
    return pairs


def one_user_round(client, file_id, rounds):
    """一个用户的一轮：浏览首页 → 滚一块 IRM → 切看板 summary → 列表 → 写一次设置。"""
    for _ in range(rounds):
        if file_id:
            client.get(f'/api/v1/browse/?datafile_id={file_id}&page=1&page_size=50',
                       endpoint='GET browse 首页')
            client.get('/api/v1/browse/?datafile_id='
                       f'{file_id}&page=2&page_size=50&sort_model=%5B%5D',
                       endpoint='GET browse IRM 块')
            client.get(f'/api/v1/summary/?file_id={file_id}',
                       endpoint='GET summary（看板汇总）')
        client.get('/api/v1/files/?page=1&page_size=50', endpoint='GET files 列表')
        client.put('/api/v1/auth/settings/', {'page_size': 100},
                   endpoint='PUT 账号设置')


def heavy_upload(base, token, path):
    with open(path, 'rb') as f:
        blob = f.read()
    body, ctype = multipart_body('file', os.path.basename(path), blob)
    client = Client(base, token)
    payload, ms = client._call(  # noqa: SLF001 - 脚本内部，不必再包一层
        'POST', '/api/v1/upload/', raw_body=body, content_type=ctype,
        endpoint=f'POST upload（{len(blob) // 1024 // 1024} MB）', expect_json=False)
    print(f'  heavy upload 完成：{ms:.0f} ms · 响应 {str(payload)[:120]}', flush=True)


def heavy_export(base, token, file_id):
    client = Client(base, token)
    _payload, ms = client.post('/api/v1/export/to_excel/',
                               {'file_id': file_id, 'passfail': 'all'},
                               endpoint='POST export to_excel（重活占位）',
                               expect_json=False)
    print(f'  heavy export 完成：{ms:.0f} ms', flush=True)


def report(base_label, compare_path):
    print(f'\n=== {base_label}')
    print(f'{"endpoint":<40} {"n":>5} {"P50":>9} {"P95":>9} {"max":>9}  errors')
    out = {}
    prev = {}
    if compare_path and os.path.exists(compare_path):
        with open(compare_path, encoding='utf-8') as f:
            prev = json.load(f)
    for endpoint in sorted(set(_samples) | set(_errors)):
        values = _samples.get(endpoint, [])
        if not values:
            # 「只有错误、一个样本都没有」的端点也必须上表 —— 否则报表会把整段失败
            # 吞成「没这个端点」，上一轮就是这么漏掉 404 的（脚本自己写错路径）。
            row = {'n': 0, 'p50': None, 'p95': None, 'max': None,
                   'errors': dict(_errors[endpoint])}
            err = ', '.join(f'{k}×{v}' for k, v in row['errors'].items())
            print(f'{endpoint:<40} {0:>5} {"-":>9} {"-":>9} {"-":>9}  {err}')
            out[endpoint] = row
            continue
        row = {'n': len(values), 'p50': round(pct(values, 0.5)),
               'p95': round(pct(values, 0.95)), 'max': round(max(values)),
               'errors': dict(_errors.get(endpoint, {}))}
        out[endpoint] = row
        note = ''
        if endpoint in prev and prev[endpoint]['p95']:
            ratio = row['p95'] / prev[endpoint]['p95']
            note = f'   ← 对比 {compare_path}：P95 ×{ratio:.2f}'
        err = ', '.join(f'{k}×{v}' for k, v in row['errors'].items()) or '-'
        print(f'{endpoint:<40} {row["n"]:>5} {row["p50"]:>9} {row["p95"]:>9} '
              f'{row["max"]:>9}  {err}{note}')
    total_err = sum(sum(v.values()) for v in _errors.values())
    locked = sum(v.get('database is locked', 0) for v in _errors.values())
    print(f'\n合计错误 {total_err} · 其中 database is locked {locked}'
          f'（{statistics.mean(len(v) for v in _samples.values()) if _samples else 0:.0f} '
          f'平均样本/端点）')
    return out


def _delayed(seconds, fn, args):
    """让重活比 mixed 晚起步 —— 否则「第一次冷解析」会被算进重活造成的排队里，归因就错了。"""
    time.sleep(seconds)
    fn(*args)


def probe_health(base):
    """先确认服务在跑：不在就一句话退出，而不是让 20 个线程各抛一次 URLError。"""
    try:
        with urllib.request.urlopen(base + '/api/v1/health/', timeout=10) as resp:
            body = resp.read().decode('utf-8', 'replace')[:120]
        print(f'health {resp.status} {body}', flush=True)
    except Exception as exc:
        sys.exit(f'打不开 {base}/api/v1/health/ —— 先按文件头那条命令起隔离后端再跑。({exc})')


def main(argv=None):
    ap = argparse.ArgumentParser(description='20 人并发压测（HTTP 层）')
    ap.add_argument('--base', required=True, help='如 http://127.0.0.1:21099')
    ap.add_argument('--users', type=int, default=20)
    ap.add_argument('--rounds', type=int, default=6, help='每用户跑几轮 mixed 请求')
    ap.add_argument('--heavy', choices=['none', 'upload', 'export'], default='none',
                    help='upload=大文件上传（P2 形状），export=导出（P3 形状）')
    ap.add_argument('--compare', default='', help='上一轮的 JSON 输出，用于报 P95 倍数')
    ap.add_argument('--warmup', type=int, default=1,
                    help='每用户先跑几轮不计账（缓存冷会污染 P95 比值）；0=关掉')
    ap.add_argument('--out', default='', help='本轮结果写 JSON（给 --compare 用）')
    args = ap.parse_args(argv)

    probe_health(args.base)
    pairs = seed(args.base, args.users, True)
    if args.heavy == 'upload' and not os.path.exists(os.path.join(ROOT, BIG_REL)):
        sys.exit('--heavy upload 需要基线大文件，但它不在仓库里（样例数据不入库）')

    clients = [Client(args.base, tk) for tk, _fid in pairs]

    if args.warmup:
        # 先走一轮不计账的请求：解析缓存/汇总缓存都是 per-(file,owner) 的，冷轮子里
        # 「首次未命中」会把 summary 的 P95 抬到几十秒。不预热就没有可比的 P95 ——
        # 实测同一场景 summary P95 = 26.0s（冷）vs 1.9s（热），拿这两者算比值毫无意义。
        print(f'预热：每用户 {args.warmup} 轮（不计入统计）…', flush=True)
        t_w = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.users) as ex:
            list(ex.map(lambda a: one_user_round(*a),
                        [(c, fid, args.warmup) for c, (_tk, fid) in zip(clients, pairs)]))
        with _lock:
            _samples.clear()
            _errors.clear()
        print(f'预热完成 {(time.perf_counter() - t_w):.1f}s · 统计账已清零', flush=True)

    t0 = time.perf_counter()

    def _run_mixed():
        with ThreadPoolExecutor(max_workers=args.users) as ex:
            futures = [ex.submit(one_user_round, client, fid, args.rounds)
                       for client, (_tk, fid) in zip(clients, pairs)]
        # 不 result() 的话线程里的异常会被 future 静静吞掉 —— 上一轮就是这么少跑了 2/3 的轮数
        for i, fut in enumerate(futures):
            try:
                fut.result()
            except Exception as exc:
                print(f'  ⚠ perf_u{i:02d} 线程异常退出：{type(exc).__name__}: {exc}', flush=True)
                record_error('（线程内异常）', type(exc).__name__)

    heavy_thread = None
    if args.heavy == 'upload':
        heavy_thread = threading.Thread(
            target=_delayed, args=(1.0, heavy_upload,
                                   (args.base, pairs[0][0], os.path.join(ROOT, BIG_REL))),
            daemon=True)
    elif args.heavy == 'export':
        if not pairs[0][1]:
            sys.exit('--heavy export 需要基线文件')
        heavy_thread = threading.Thread(
            target=_delayed, args=(1.0, heavy_export, (args.base, pairs[0][0], pairs[0][1])),
            daemon=True)
    if heavy_thread:
        heavy_thread.start()

    _run_mixed()
    wall = time.perf_counter() - t0
    if heavy_thread:
        heavy_thread.join()

    label = f'{args.base} · {args.users} 用户 × {args.rounds} 轮 · heavy={args.heavy} · 墙钟 {wall:.1f}s'
    out = report(label, args.compare)
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f'JSON → {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
