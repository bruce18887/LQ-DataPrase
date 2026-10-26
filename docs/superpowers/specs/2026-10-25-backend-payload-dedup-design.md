# B 后端载荷（解析缓存坐标化）设计稿

**Goal:** 把 20 人并发下的同进程载荷降下来——解析缓存从「按 (file, owner) 分键」改成「按物理文件内容坐标分键」，
并把两处「每次请求重算一遍已经算过的东西」挪到写入侧，使 20 个人打开同一个物理文件只付一次解析、
翻页不再每请求跑一遍 O(列) 元信息循环。

**Architecture:** 改动集中在 `apps/datafiles/services.py` 的缓存键组装与「什么值允许进缓存」这条判据上，
外加两个出口侧的一次性化（`build_col_meta` 随解析产出、dashboard 的 `clean_data` 挪到写入侧）。
缓存键不再含 `file_id`/`owner_id`，但**鉴权完全不留在缓存里**：调用方照旧用
`DataFile.objects.filter(pk=file_id, owner_id=request.user.pk)` 判可见性。响应形状一字不改。

**Tech Stack:** Django/DRF + pandas、进程内按字节预算的 LRU（`_BytesLRUCache`，带每-key 单飞）、
Django unittest（T1）、Playwright（仅作既有契约回归，不新增选择器）。

---

## 0. 路径与已定口径

本刀按 brainstorming 判为 **architectural**（改的是多条热路径共同依赖的缓存键与一处语义）。
四条口径已由用户 2026-10-25 逐条点定：

| # | 口径 | 取定 |
|---|---|---|
| 1 | 边界 | **只做去重**，不改前后端契约（`headers`/`col_meta` 照旧每页发） |
| 2 | 共享防护 | **只加承重判据**，不上只读视图/不改结构约束 |
| 3 | 验收 | **判据先行，阈值事后定**（先拿复测读数再定提交跳那条线） |
| 4 | 方案 | **① 载荷坐标化 + 语义对齐**（含「失败不入缓存」这条语义变更） |

> ⚠ 第 4 条里「失败结果不再入缓存」是**数据/错误口径的变更**，不是纯重构。它已被单独提出并批准，
> 实施时不许和坐标化混在同一条提交信息里含糊过去（见 §5 的 J2 与 §8）。

## 1. 靶点与证据（全部现读代码所得，行号截至本笔）

20 人档测量的定靶结论在 `docs/reference/perf-baseline-2026-10-24-dual-profile.md` §6，三个落点。逐条核实如下：

1. **解析缓存键过细** —— `apps/datafiles/services.py:197` 的键是 `(file_id, owner_id, path_key, file_path)`，
   写透侧 `:261` 同构。但 `_parse_file_uncached`（`:202-216`）只消费 `file_path` + `format_type`，
   `file_id`/`owner_id` **只出现在那行 warning 日志**里 ⇒ 键里的这两个维度对解析结果是零影响项。
   后果实测在压测夹具里：`scripts/perf_load20.py:192-195` 明写「每个用户各登记一行 DataFile 指向
   **同一个物理文件**」（因为 browse/summary 按 `owner=request.user` 取对象，共用一行会让另外 19 人 404）
   ⇒ 20 个 owner = 20 个不同 key = 同一只文件解析 20 次。
2. **单飞救不了它** —— `_BytesLRUCache` 有每-key 单飞（`:59-65`，注释自述历史上首屏三路并发会各解析一遍、
   单次约 4s），但不同 owner 是不同 key，单飞在跨用户场景完全不起作用。这是表 A 里
   browse 首页 P95 **6288ms** 的尾部主导项，也是解析峰值内存「20 × ~460MB」的来源。
3. **每请求 O(列) 元信息循环** —— `apps/analysis/services/statistics/limits.py:296-303` 的 `build_col_meta`
   对 `df.columns` 逐列构造 `{unit,min,max}`；实测夹具那档 1,702 列。台账读数在
   `docs/tasks/todo.md:4594-4595`：`page_size=50` 的响应体 700,451 字节而 `to_json` 只要 18ms，
   大头就是载荷与「每请求 260ms 元信息循环」。
   它的输出只依赖 `df.columns` + `metadata` ⇒ 同一文件每一页都相同。
4. **dashboard 命中缓存后仍重算清洗** —— `apps/dashboard/views.py:65` 每次请求把（可能命中缓存的）
   summary 整份过一遍 `clean_data`。`clean_data`（`apps/analysis/views/_helpers.py:84-94`）是**纯函数**，
   返回新建的 list/dict、绝不原地改 ⇒ 挪到写入侧无等价性风险。
   覆盖面实测：`clean_data` 全仓 19 个调用点（`statistics_views` 7、`analysis_views` 6、`param_actions` 4、
   `file_correlation_views` 1、`dashboard/views` 1），但**只有 dashboard 这一处属于"命中缓存后仍重算"**——
   进程内缓存只存在于 `apps/dashboard/services.py` 的 `_summary_cache`。视图注释里那句
   「与 analysis 侧 23 个端点同写法」描述的是防御性清洗这个**写法**，不是浪费；其余 18 处作用在
   未缓存的结果上，属必要工作，本刀不动。

**一条由本刀暴露的既有事实**：`_parse_value_bytes`（`apps/datafiles/services.py:49-56`）对失败三元组
`(None, None, fmt)` 算出 **0 字节**，而 `get_or_compute` 无条件下 `_store`（`:124`）
⇒ **失败结果当前就被缓存**，且 0 字节条目不受字节预算淘汰。
`_disk_mtime_ns`（`:157-171`）的 docstring 自己就写着「没有 mtime 这个键，`_cached_parse` 会一直吐
上次缓存的 `(None, None, fmt)`」。今天这条的爆炸半径是一个人（键含 owner）；坐标化后是同一路径的所有人
⇒ 所以「失败不入缓存」是坐标化的**前置**，不是可选优化。

## 2. 设计：四处改动

### 2.1 键坐标化（`apps/datafiles/services.py`）

- `_cached_parse` 与 `put_cached_parsed_file` 的键统一改为 **`(abs_path, path_key, format_type)`**，
  其中 `path_key = _disk_mtime_ns(abs_path)`。两处键算法必须逐字同源（沿用现有「否则写进去也命不中」那条约束）。
- `get_cached_parsed_file(file_id, owner_id, datafile=None)` 与 `_cached_parse(...)` 的**签名保留 `owner_id`**：
  它仍用于 ① 调用方未传 `datafile` 时的那次鉴权查询 `DataFile.objects.filter(pk=file_id, owner_id=owner_id)`，
  ② 失败日志。`apps/datafiles/tests_parse_cache.py:297` 按参数名钉着这份签名，保留 ⇒ 它不该红。
- `format_type` 进键：两行 DataFile 指向同一 `abs_path` 但标注不同格式时是**两条键**（parser 不同，必须不同）。

### 2.2 失败结果不入缓存（语义变更）

判据放在 **services 层**（LRU 不知道什么叫"解析失败"），但**写入动作发生在通用件里面**——
`get_or_compute` 自己调 `_store`（`:124`），调用侧拿不到"存不存"的决定权。所以落地方式是
给 `_BytesLRUCache.get_or_compute` 增一个**默认关闭**的可选谓词参数（形如 `store_if=None`，
`None` 时行为与今天逐字一致），由 services 传入"成功才存"。

⚠ 明确否决一条看起来更省事的写法：让 `_parse_value_bytes` 对失败值返回 `budget + 1`，
借「单值超预算不缓存」那条既有出口达到同样效果。它能让判据变绿，但把"太大"和"不该存"两件事压在同一个机制上，
读代码的人只看到一条体积异常 —— 那是 hack 不是设计。

失败形状有三种（路径不存在 / `df is None` / 抛异常，见 `_parse_file_uncached:202-216`），
三种都不许入缓存，与写透路径 `put_cached_parsed_file`（`df/metadata` 为 None 时不写）对齐成同一条规则。

代价与选择理由（写明，别事后惊讶）：坏路径的每次请求都会重试（多付一次 `os.path.exists` 与可能的失败解析），
换来「瞬时失败不会永久化」。0 字节条目连 LRU 都淘汰不动它，而给用户一个永久的 `parse_failed` 比一次重试更贵。

### 2.3 `col_meta` 随解析产出

`build_col_meta(df, metadata)` 的结果在解析成功时**算一次**，写进 **metadata 的一个新键 `col_meta`**，
随解析值一起进缓存、一起被预算淘汰；翻页时直接取用。响应里 `col_meta` 字段**照旧每页都发**，
内容由「每请求重算」变成「每文件一次」。

选这条而非另两条的理由：改缓存值的元数（三元组→四元组）会牵动 **12 个解包点**，是纯噪音的大 diff；
另开一套键则出现第二份生命周期，同一批字节被两个预算各管一次。
两条前提刚核过：① 全仓没有任何地方把 `metadata` 整体序列化进 HTTP 响应
（`git grep "'metadata':"` 除测试夹具外唯一命中是 `apps/analysis/views/_helpers.py:193-199`
那个内部 `file_data_list`，它连 `df` 一起装，本来就不是响应）；② 现有 65 处 `metadata` 消费都按键取值
（`units`/`mins`/`maxs`/`format` 等），多一个键对它们无害。

⚠ 连带必改的一处口径：`_parse_value_bytes`（`:49-56`）现在按 `64 * len(metadata)` 估 metadata 体积，
多塞 `col_meta`（1,702 列那档是几十 KB 量级）会被估成 64 字节 ⇒ **预算会失真**。
体积估算要按 `col_meta` 的真实量级计入，否则 1536MB 那条预算就成了自欺的数字。

### 2.4 dashboard 的 `clean_data` 挪到写入侧

`get_dashboard_summary`（`apps/dashboard/services.py:366`）在**未命中、算完 payload 之后**先清洗再入缓存；
命中直接返回已清洗对象。`_summary_cache_key(datafile, fmt, thresholds)` **不改**——`thresholds` 来自
`get_cpk_thresholds(request.user)`，这一层本来就该按用户阈值分键，跨用户共享是错的。

生产侧调用点**一个都不动**（签名不变），共 12 处：
`apps/analysis/views/_helpers.py:157,189`、`analysis_views.py:293`、`file_correlation_views.py:162,209`、
`batch_report/services.py:77` + `batch_report/views.py:110`、`buyoff/views.py:33,72`、
`common/file_loading.py:48`、`dashboard/views.py:55`、`datafiles/views/browse_views.py:142`、`gage/views.py:64`。

## 3. 不变式

- **失效杠杆只有 `mtime_ns` 一个**，本刀不新增 TTL、不加内容哈希（那是 P4-3 待拍板项）。
- **缓存不参与鉴权**：能被同一 `abs_path` 命中的前提，是这个人自己已有一行 DataFile 指向它 ⇒
  共享不新增任何"看得见的内容"。
- **单飞语义不变**，只是现在它真的能跨用户生效（同 key 并发 miss 只算一次）。
- **响应字节不变**：J4/J5 用逐字节对照证明，不靠"看起来一样"。

## 4. 复测与阈值

验收读数的口径全部复用 `docs/reference/perf-baseline-2026-10-24-dual-profile.md` §1 的协议与夹具
（每轮冷启动独立进程 + 独立数据根、`--warmup 1` 后清零统计账、同一只 `$BIG`（275MB / 35,246 行 × 1,702 列）
与 20 只 `$MID`、每端点 n=120、提交分首跳/稳态并配无并发对照、两档定义同构），**不新建口径**。
结构读数用现成的 `get_parse_cache_stats()`（已挂 `/api/v1/metrics/`：`entries/hits/misses/evictions/clears`）。

提交跳的硬阈值**等复测读数出来再定**（已定口径 3）。注意基线 §7 的两条限制不许外推：
单机（方案 A 档在 WSL2/NAT）⇒ 容量与并发上限不可外推；稳态 n=6 ⇒ P95≈max，要当门禁基线得加到 ≥20 单。

## 5. 判据（T1 为主，每条自带对照组）

按 `docs/reference/testing-gates.md` §2 选层：本刀零 UI 改动 ⇒ 全部落 T1（后端服务/纯函数），
T2/T3 只承担"既有契约没被动"的回归证明，不新增选择器。

| # | 断言 | 对照组（必须红的那一档） |
|---|---|---|
| J1 | 两行 DataFile 同 `abs_path`、不同 owner ⇒ 两次取回 **`assertIs` 同一只 df**，且 `entries == 1` | 键里加回 `owner_id` ⇒ 红 |
| J2 | 让 `parse` 抛一次 ⇒ `entries` 不增，且第二次请求**确实又试了**（调用计数桩 > 1） | 恢复「失败入缓存」⇒ 红 |
| J3 | 两个 owner、同一路径、并发 miss ⇒ `parser.parse` 调用 **1 次** | 改回 per-owner 键 ⇒ 红（现存 `:123` 那条从"同 key"扩到"跨 owner"） |
| J4 | N 次翻页 ⇒ `build_col_meta` 调用次数 == 解析次数（非请求次数），且响应串逐字节相等 | 每请求仍算 ⇒ 计数红 |
| J5 | 同 user 同 thresholds 的第二次请求 ⇒ `clean_data` 调用 0 次；payload 与旧写法逐字节相等 | 清洗留在出口 ⇒ 计数红 |
| J6 | 文件缺失（`_disk_mtime_ns` 返回 0 那档）⇒ 该结果**不缓存**，恢复后可正常命中 | 失败入缓存 ⇒ 红 |
| J7 | `col_meta` 进 metadata 后，`bytes_cached()` 的增量 ≥ `col_meta` 的真实量级（预算不失真） | 沿用 `64 × len(metadata)` ⇒ 红 |

现存用例的处置：`apps/datafiles/tests_parse_cache.py:90`「换 `file_id` → 新 key，必须挤掉旧的」**正面断言旧语义**，
本刀改成内容坐标断言（同 path 不同 `file_id` ⇒ 同 key、同一只对象）；改写前先用 J1 的对照确认它真承重，
改写后它才是"语义变了"的哨兵而不是残留。`apps/datafiles/tests.py:762-797`、`:1766-1783` 那几处解析缓存用例
若断的是 owner 维度，同样要按新语义重写并逐条说明。

## 6. 门禁档位

- 批内 affected：`cd frontend && npm run test:e2e:affected`（改到 `apps/datafiles`/`dashboard`/`analysis`
  ⇒ 会带后端子集与相应模块档）。
- 收口：`node scripts/e2e_pool.mjs --slots=4` + 后端全套（判据取日志末尾 `RESULT:` 行，不取 `$?`）。
- 复测另跑 §4 的 20 人档协议，读数进台账，**不进门禁**（单机不外推）。

## 7. 残余风险（明写，不藏）

1. 一只 df 被多个请求并发读，本刀只有 J1/J3 + 调用方静态扫描兜着，**没有结构性只读约束**（口径 2 已拍）。
   静态扫描要按"载体并集"写，别重犯 `:5325-5329` 那次的搬家漏扫（单文件扫描零命中 ⇒ 空集假绿）。
2. 坏路径每次重试的 CPU 代价（§2.2）。
3. 解析峰值内存下降会**改变崩池的发生条件**，但崩池本身归内存治理批 2/3，本刀不承诺修复，只记读数。

## 8. 刻意不做

响应体瘦身（`headers`/`col_meta` 每页照发）、任何前端代码与 e2e 契约、媒体内容哈希（P4-3 待拍板，
与现有 move 语义正面冲突）、内存批 2（准入）与批 3（每-worker 硬上限）、`_BytesLRUCache` 的淘汰与预算算法
（只加 §2.2 那条**默认关闭**的可选谓词参数，其余行为逐字不变）、
其余 18 处 `clean_data`、`evict_to`/水位的既有关系。

## 9. 落点文件

`apps/datafiles/services.py`（347 行）、`apps/dashboard/services.py`（406）、`apps/dashboard/views.py`（75）、
`apps/analysis/services/statistics/limits.py`（334）或其调用侧、`apps/datafiles/tests_parse_cache.py`（340）、
`apps/datafiles/tests.py`（1968，受 600 行约束的那件——本刀只改其中解析缓存相关的几段，
拆文件归 P2-7，不在本刀夹带）。全部低于 600 行上限，本刀不产生新的越界文件。
