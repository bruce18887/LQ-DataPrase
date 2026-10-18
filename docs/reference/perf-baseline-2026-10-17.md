# 性能基线（2026-10-17 立项，2026-10-18 复跑固化）

> 本文只写**有命令产出过**的数字。方案与验收线在 `docs/plans/2026-10-17-performance-remediation.md`。
> 前身是 `tasks/perf_probe_*_2026-10-17.py` 六个临时探针，已合并成 `scripts/perf_baseline.py`
> （进程内单点成本）与 `scripts/perf_load20.py`（20 人 HTTP 负载）。

## 1. 复跑方式

```bash
# A. 进程内单点成本（只读，不碰库不碰 media）
.venv/Scripts/python.exe scripts/perf_baseline.py                    # 默认 7 组
.venv/Scripts/python.exe scripts/perf_baseline.py big irm --json     # 指定组 + 落 JSON
.venv/Scripts/python.exe scripts/perf_baseline.py peak               # 解析期峰值内存（默认不跑，见下）

# B. 20 人 HTTP 负载（两步；服务与压测必须用同一个隔离档）
LQDP_E2E_SLOT_DIR=test/perf-data DJANGO_SETTINGS_MODULE=config.settings.e2e_slot \
    .venv/Scripts/python.exe manage.py migrate --noinput
LQDP_E2E_SLOT_DIR=test/perf-data DJANGO_SETTINGS_MODULE=config.settings.e2e_slot \
    .venv/Scripts/python.exe manage.py runserver 127.0.0.1:21099 --noreload
LQDP_E2E_SLOT_DIR=test/perf-data DJANGO_SETTINGS_MODULE=config.settings.e2e_slot \
    .venv/Scripts/python.exe scripts/perf_load20.py --base http://127.0.0.1:21099 \
        --users 20 --rounds 3 --heavy none --out tasks/mixed.json
# 对照轮（同参数加 --heavy upload --compare tasks/mixed.json）
```

`peak` 组默认不跑：`tracemalloc` 会把 `parse()` 从 3.6s 抬到 **7.8s**（实测），同表比较就是自欺。
`perf_baseline.py` 里也**不再有 browse `search` 探针** —— 该参数已于 P1-5 删除（直连返回 400）。

## 2. 进程内单点成本（`scripts/perf_baseline.py`，2026-10-18 两轮）

机器：本机 Windows，基线文件 275MB / 35,246 行 × 1,702 列（文本列 2 个）。A=11:35 那轮，B=紧随的第二轮。

| 组 | 探针 | A ms | B ms | 读法 |
|---|---|---|---|---|
| big | `parse()` | 3642 | 3831 | 一次性成本的主体；常驻 460MB |
| big | `detect_fail_data()` | 379 | 372 | 已按 (file, mtime) 缓存 |
| big | `df.copy()` | 581 | 461 | 10-17 那次量到 328ms；本轮抖动到 461–581 |
| big | `sort_values 单列` | 273 | 267 | |
| big | `page(100 行) to_json` | 19 | 18 | 序列化本身很便宜，载荷大小才是要害（见 §3） |
| screen | browse page==1 元信息循环 | 260 | 247 | 每个首页请求都要付 |
| screen | `build_col_meta()` | 1 | 1 | |
| screen | `compute_dashboard_summary()`（不缓存） | 978 | 1232 | P1-2 之前的通路 |
| screen | `get_dashboard_summary()` 首次 | 900 | 1163 | 未命中 ⇒ 与上一行同价 |
| screen | `get_dashboard_summary()` **二次** | **0** | **0** | **P1-2 承重项：同 key 命中，两轮都是 0** |
| screen | 换 thresholds（必须失效重算） | 836 | 1013 | 判据的另一半：只测「二次=0」会漏掉失效不生效 |
| analysis | histogram 10 参数 | 276 | 277 | |
| analysis | 全列低 CPK 扫描 | 2507 | 2038 | 进程内有缓存 |
| batch | `calculate_fail_bin_statistics` | 1 | 1 | 批次汇总的成本全在 parse |
| batch | `compute_site_yield_data` | 9 | 7 | |
| batch | `compute_uph` | 7 | 7 | |
| irm | `filter_model` 文本列 contains | 56 | 64 | 真实滚动路径 |
| irm | `filter_model` 数值列 >0 | 2 | 1 | |
| irm | `sort_model` 单列 | 176 | 171 | |
| irm | filter+sort 合成一块 | 142 | 145 | 与 10-17 的 152ms 一致 |
| startup | 子进程 import pandas+matplotlib | 485 | 444 | 含解释器启动 |
| startup | `ProcessPoolExecutor(8)` 冷启 + 每 worker import | 692 | 635 | **见 §4 第一条** |
| startup | 池冷启 + 每 worker import `chart_workers` | 1151 | 1032 | 真实导出通路要多 import 渲染模块 |
| auth | `make_password`（pbkdf2_sha256） | 367 | 353 | 10-17 记的 346ms 复现 |
| auth | `check_password` 命中 | 353 | 329 | 每次登录都要付 |
| auth | `check_password` 不匹配 | 367 | 324 | 不匹配也付满迭代 ⇒ 登录可被用作 CPU 拒绝服务 |

## 3. 20 人 HTTP 负载（`scripts/perf_load20.py`，2026-10-18）

服务档 `config.settings.e2e_slot` + `runserver --noreload`（多线程），20 个用户各一只 20MB 文件
（20 × 约 35MB 常驻 = 700MB，落在 1536MB 解析缓存预算内），每用户 3 轮，每轮 5 个请求。

| 端点 | 预热 mixed P50/P95/max (ms) | +275MB 上传进行中 P50/P95/max | P95 倍数 |
|---|---|---|---|
| GET browse 首页 | 4358 / **6288** / 6827 | 4713 / 7442 / 7826 | ×1.18 |
| GET browse IRM 块 | 941 / 1881 / 2402 | 1667 / 2600 / 3336 | ×1.38 |
| GET summary（看板） | 804 / 2152 / 2368 | 811 / 2332 / 2746 | ×1.08 |
| GET files 列表 | 749 / 1730 / 2125 | 541 / 2005 / 2565 | ×1.16 |
| PUT 账号设置（写） | 733 / 1978 / 2487 | 462 / **1903** / 2142 | ×0.96 |
| POST upload（275MB） | — | 36709（1 次） | — |

- **两轮都是 0 错误、0 次 `database is locked`** ⇒ P2「拆开长写事务」的方向是对的：
  上传 275MB 期间写请求没有被写锁挡住（倍数 ×0.96，即与不上传时同量级）。
- **但目标线全部没达到**：方案 §3 要 browse 首页 P95 < 400ms、导入期间他人写 P95 < 200ms，
  实测是 6288ms 与 1903ms。原因不是锁，是**单进程串行 + 载荷大小**。
- browse 首页贵的不是解析：服务端日志量到 `page_size=50` 的响应体 = **700451 字节**
  （50 行 × 1702 列）。`to_json` 本身只要 18ms，贵在序列化 + 传输 + 每请求重复做 260ms 元信息循环。
- ⚠ **进程模型口径**：`runserver --noreload` 是多线程 dev server，20 人正式档是单进程同步 worker
  （`docs/reference/server-deployment.md:60-72` 里进程模型尚未拍板）。所以这一档量到的是
  「DB + 解析 + GIL 排队」，**量不到**「一个请求占满 worker 全站停」那一种停摆。
  本文所有 P95 都是**乐观值**；换 waitress / gunicorn-sync 跑同一份脚本才会压出真实尾部。

### 缓存冷热会污染 P95 比值（脚本因此自带 `--warmup`）

同一场景（20 用户 × 3 轮、无重活）差别只在预热：

| | summary P50 | summary P95 | summary max |
|---|---|---|---|
| 冷（不预热） | 1022 | **22480** | 26004 |
| 热（预热 1 轮） | 804 | 2152 | 2368 |

首版的「heavy vs mixed」比值因此算出过 `×0.09` 这种荒谬值 —— 分子那轮缓存是热的，
分母那轮里塞着 20 次冷计算。**跨轮比 P95 之前必须先让两轮同样热**。

5 用户小档（校验脚本机制用）：browse 首页 1099/1987、IRM 186/313、files 136/491、
summary 149/438、PUT 120/549，0 错误 —— 并发从 5 抬到 20 后 browse 首页 P50 从 1.1s 涨到 4.4s。

## 4. 被实测推翻/修正的三条说法

1. **「导出每次 spawn 8 进程 ⇒ 约 5.7s 纯启动」（方案 §2 表、§6、spec §9 验收项）不成立。**
   那是 `715ms × 8` 的**串行乘法**，而 spawn 出来的 worker 是**并发**启动的。实测：
   `ProcessPoolExecutor(8)` 冷启 + 每 worker `import pandas/matplotlib` 墙钟 **635–692ms**，
   加上真实 worker 模块（`apps.export.chart_workers`）也只有 **1032–1151ms**。
   ⇒ P3 的收益**不在「省启动」**，只在「把活挪出请求线程」。spec §9 那条
   「单次导出的启动开销从 5.7s 降到 < 0.5s」作废，改判为「导出提交 < 200ms + 轻请求 P95 劣化 ≤ 2×」。
2. **browse `search` 的 16.2s 已经不是通路了。** 10-17 实测 `astype(str)` 10083ms、全链路 16177ms；
   P1-5 已删该参数并改成直连 400（提交 `3beb861`），基线脚本里也不再留这条探针。
3. **`tracemalloc` 会把 `parse()` 拖慢到 2 倍**（3.6s → 7.8s 实测），所以峰值内存独立成 `peak` 组、默认不跑。

## 5. 这批数据支撑的结论

- 一次性成本（parse 3.6s × 每用户每文件）与串行排队是主因；解析缓存按 (file, owner) 分键，
  20 个人打开**同一个物理文件**也要各解析一遍 —— 这是 §3 里 browse/summary 尾部的主导项。
- P1-2（看板汇总缓存）在真实 HTTP 上同样成立：冷 22.5s → 热 2.2s P95，进程内二次命中 0ms。
- P2（拆开长写事务）达成「无 `database is locked`」；未达成「他人写 P95 < 200ms」——
  剩下的排队要靠 P3（重活挪出请求线程）与载荷瘦身（browse 首页 700KB/块）。
