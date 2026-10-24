# 20 人档双形态基线（2026-10-24）· 方案 A 档 vs 浏览器档

这份文档回答一个问题：**20 人并发下的 P95 到底被什么拖住**。答案是「同进程争抢」，
不是进程形态，也不是提交路径。它同时结清 P3 那两条从未取证的验收，并给出
2026-10-21 崩池的归因。

与 `perf-baseline-2026-10-17.md` 的关系：那份是**浏览器档的历史快照**（数字仍有效，
但口径不含本文件的冷启动协议）；本文件是两档对照 + 提交跳分型。**两份的数字不可互相代入**，
差在协议不在代码，见下节。

## 1. 口径（不满足就不许引用这里的数字）

| 条件 | 取值 | 为什么是承重的 |
|---|---|---|
| 每轮进程 | **冷启动独立进程 + 独立数据根** | 同进程连跑两轮时，第二轮吃第一轮的解析缓存：实测 browse 首页 P95 从 7116ms 掉到 3429ms，那是缓存不是优化 |
| 预热 | `--warmup 1` 后**清零统计账** | 解析/汇总缓存按 `(file, owner)` 分键，冷轮的首次未命中会把 summary P95 抬到几十秒（脚本自述实测 26.0s vs 1.9s） |
| 夹具 | 与 10-17 同一只 `$BIG`（275MB / 35,246 行 × 1,702 列）与 20 只 `$MID`（各 20MB） | 换素材就等于换瓶颈；`$MID` 的 20MB 是刻意的，用 `$BIG` 会让 20 人工作集 9.2GB 互相洗缓存 |
| 样本量 | 每端点 n=120（20 用户 × 6 轮） | n 小的时候 P95≈max，报表连 n 一起出 |
| 提交判据 | 分「**首跳（含池懒建）**」与「**稳态**」，且必配**无并发对照** | `_get_pool()` 是懒建的，Windows 又钉 spawn ⇒ 首跳要付子进程启动的钱；只提一次就当「提交 P95」会让判据假红 |
| 两档定义 | 浏览器档 = `config.settings.e2e_slot` + 手起 `runserver --noreload`（DEBUG=True）；方案 A 档 = `config.settings.server` + **systemd 临时 unit** 跑 `standalone.py`（DEBUG=False） | 与生产进程模型同构的只有后者（`docs/reference/server-deployment.md` §3） |

跑法（两档各三轮 + 一轮无并发对照）：

```bash
# 浏览器档（Windows）
env LQDP_E2E_SLOT_DIR=test/perf-<轮名> DJANGO_SETTINGS_MODULE=config.settings.e2e_slot \
    .venv/Scripts/python.exe manage.py migrate --run-syncdb
env LQDP_E2E_SLOT_DIR=test/perf-<轮名> DJANGO_SETTINGS_MODULE=config.settings.e2e_slot \
    .venv/Scripts/python.exe manage.py runserver 127.0.0.1:<port> --noreload
env LQDP_E2E_SLOT_DIR=test/perf-<轮名> DJANGO_SETTINGS_MODULE=config.settings.e2e_slot \
    .venv/Scripts/python.exe scripts/perf_load20.py --base http://127.0.0.1:<port> \
    --heavy job --job-submits 6 --out tasks/perf-r1-<轮名>.json

# 方案 A 档（Linux/WSL）：每轮一个 systemd 临时 unit + 独立 BASE_DIR，跑完即停
systemd-run --unit=lqdp-perf-<轮名> --property=User=lqdp --property=Group=lqdp \
    --property=WorkingDirectory=/srv/lqdp-src --property=EnvironmentFile=/etc/lqdp/server-perf.env \
    --property=Environment=LQDP_SERVER_BASE_DIR=/srv/lqdp-perf-<轮名> \
    /srv/lqdp-src/.venv/bin/python standalone.py --host 127.0.0.1 --port <port>
```

⚠ 在 WSL 里跑必须把夹具放 **ext4**（`/srv/lqdp-src/Data/...`）。从 `/mnt/c` 直读 275MB 走的是
9p，量到的是协议不是 CPU。

## 2. 表 A：两档 P95 对照（ms，每轮冷启动）

| 端点 | 浏览器档 plain | 方案 A 档 plain | 浏览器档 +275MB 上传 | 方案 A 档 +275MB 上传 |
|---|---|---|---|---|
| GET browse 首页 | 3179 | 3766 | 3429 | 4244 |
| GET browse IRM 块 | 2128 | 2505 | 2117 | 1897 |
| GET files 列表 | 759 | 327 | 676 | 901 |
| GET summary | 1718 | 1925 | 1727 | 1996 |
| PUT 账号设置 | 1413 | 1080 | 1871 | 1701 |
| POST upload（275MB，n=1） | — | — | 37938 | 32698 |

**读法**：两档互有胜负，幅度 ≤1.3×，且两档都卡在 browse 首页 3.2–4.2 秒。
⇒ **进程形态不是当前矛盾**；`server-deployment.md` §7 用方案 A 档复跑验收时不必担心「换了形态数字就变」。

## 3. 表 B：作业提交跳（P3 的两条判据）

| 条件 | 浏览器档 | 方案 A 档 |
|---|---|---|
| 无并发 · 首跳（含池懒建） | 65ms | 34ms |
| 无并发 · 稳态 6 单 | 12 / 14 / 16 / 23 / 30 / 30ms（中位 19.5） | 17 / 25 / 35 / 37 / 44 / 48ms（中位 36） |
| **20 人并发 · 首跳** | 3486ms | 3750ms |
| **20 人并发 · 稳态 6 单** | 514 / 607 / 1499 / 1898 / 2739 / 2952ms（中位 1698） | 305 / 707 / 1413 / 1901 / 2778 / 3558ms（中位 1657） |
| 同期轻请求劣化（heavy/plain） | 0.9–1.5× | 0.9–1.5× |

**判据结论**（设计稿 `docs/specs/2026-10-17-heavy-job-offload-design.md` §目标）：

- ✅ **「轻请求 P95 劣化 ≤2×」达标** —— 重活确实不再拖垮别人的请求，P3 的隔离目的实现了。
- ✅ **「提交 P95 <200ms」在无并发达标**（12–48ms）⇒ 提交路径本身不贵。
- ❌ **同一判据在 20 人档不达标**（中位 ~1.7s，超 8 倍），且两档中位数几乎相同（1698 vs 1657）
  ⇒ 慢的不是提交代码，是**提交跳在和同进程里 20 人的解析/序列化争抢同一个 GIL 与同一把写锁**。

这条区分决定了下一刀的落点：见 §6。

## 4. 崩池归因（2026-10-21 那轮 VOID）

既有现场（**本机** e2e 池产物，`C:/lqdp-e2e/slots/022212-54444/blob/report.jsonl`，
该目录不入库）里因果链完整，无需重跑：

```
OpenBLAS error: Memory allocation still failed after 10 retries, giving up.   ×8
  → 子进程死亡
  → concurrent.futures.process.BrokenProcessPool                              ×6
  → POST /api/v1/jobs/export_excel/ 500                                        ×3
  → POST /api/v1/jobs/export_html_report/ 500                                  ×2
当时 commit：33.2GB / 36.7GB（只剩 3.5GB）· 4 个 slot 里 slot1 与 slot3 中招（slot0/slot2 干净）
```

配套事实：**2-slot 复跑也掉了 slot1**（本机 `tasks/e2e-pool-batch1-slots2.log:9`，
该目录 gitignored；现场记「空闲提交 6.3GB 低于预算 8.0GB」）⇒ 这不是并行度问题，降档不解决。

判读口径：**看 commit，不看 available 内存**。`apps/common/memory.py` 的预算日志已经把
这条打出来了（`WARNING 系统空闲提交内存 X 低于预算 8.0GB`），出现这行就别开全量池。

## 5. 已修与未修

- ✅ **已修（`87fbc9c`）**：崩池之后**永久 500**。原缺陷是 `executor_available()` 只判
  「池建不建得起来」，看不见「池里的子进程刚死」，而 `_dispatch` 不接标准库异常 ⇒
  一次内存尖峰后该进程所有导出永久 500，且进程活着，`Restart=always` 救不回来。
  现在崩池会丢弃坏池并让**紧接着的那一条**请求走同步回落。三条 T1 判据在
  `apps/jobs/tests_jobs.py`（修复前分别红在 `AttributeError` / `500 internal_error` / 孤儿 `pending`）。
- ❌ **未修**：**为什么会崩**（OpenBLAS 在 commit 逼近上限时分配失败）。那是内存治理
  批 2（准入控制）与批 3（每-worker 硬上限）的靶子，本文件只负责给出定靶读数。
- ⚠ 附带缺口：e2e 池的掉线现场文件只有进程表与 netstat，**没有后端 stderr**；
  本节的归因靠的是 `slot*.run.log` 与 `blob/report.jsonl`，下次崩池建议把后端日志尾部也收进现场。

## 6. 下一刀（定靶结论）

争抢是主因 ⇒ 要降的是**同进程里的载荷**，即桌面卡顿线里那条「B 后端载荷」（`docs/tasks/todo.md:5318`）：

1. `browse` 每页重发 headers/col_meta（`apps/datafiles/views/browse_views.py:237,246`）；
2. 缓存命中后仍跑 `clean_data`（`apps/dashboard/views.py:65`，出口兜底那一条）；
3. 解析缓存按 `(file, owner)` 分键 ⇒ 20 人各解析一遍同一物理文件
   （`get_cached_parsed_file(datafile.id, request.user.pk, ...)`，见
   `apps/datafiles/views/browse_views.py:142` 与 `apps/dashboard/views.py:55`）。

**B 目前没有设计稿**，开工前要先出 spec。三条判据的验收就用本文件的协议与夹具，
不新建口径。

## 7. 局限（不许外推的部分）

- 全部数字来自**单机**：方案 A 档跑在 WSL2（内核 6.6.114.1-microsoft-standard，NAT 网络）。
  局域网多用户访问模拟不了，真机的网卡/磁盘/CPU 也不同 ⇒ **容量与并发上限不能从这里外推**。
- 压测客户端与服务端同机，争抢读数偏保守（真实多机场景客户端不占服务端 CPU）。
- 稳态提交 n=6，P95≈max；要当门禁基线得加到 ≥20 单。
- 本轮 commit 空闲约 10GB（30.7/40.8GB），高于 §4 的崩池阈值 ⇒ 本轮**没有**复现崩池，
  归因来自既有现场而非新证。
