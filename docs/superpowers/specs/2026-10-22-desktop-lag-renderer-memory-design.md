# 桌面端卡顿：渲染进程内存整改设计（2026-10-22）

**证据来源**：用户从生产机（`C:\Users\bpsemi`）搬来的 `test/logs/{main.log,backend.log}`，覆盖 2026-09-08 ~ 2026-10-22。
探针脚本在同目录（被 `.gitignore:135 /test/*` 挡住，不入库）：`_api_latency.mjs`、`_payload.mjs`、`_split_latency.mjs`。

**用户拍板范围**：E（先实测复现）→ A（前端内存/请求整改）。B 后端载荷瘦身、C 落地
`2026-10-21-backend-memory-governance`、D 日志卫生**本轮不做**。

---

## 1. 根因判定（实测，非推断）

### 1.1 一次崩溃

```
[2026-10-22T06:47:30.084Z] [ERROR] [electron] Renderer process gone: oom (exitCode=-536870904)
```

`-536870904 = 0xE0000008`，Chromium 自报 `reason='oom'`。全量日志里另一条 `Renderer process gone`
是 09-09 的 `killed (exitCode=-1073741510=0xC000013A)`（Ctrl+C 语义），与本次无关。

### 1.2 卡顿在渲染侧，不在后端

把渲染进程的 `[api] Request/Response` 与后端访问行按 method+path 配对（只取**无歧义**的单命中样本），
拆成「发出→后端写完访问行」与「后端写完→渲染进程看到」两段。两条时间戳都由 Electron 主进程写入，
同一时钟，可直接相减：

| 时刻(UTC) | 请求 | 字节 | 总耗时 | 后端 | 渲染侧 |
|---|---|---|---|---|---|
| 06:47:49 | `GET /summary/?file_id=179` | 1,124,780 | **51 ms** | 42 | 9 |
| 06:47:56 | `GET /summary/?file_id=179`（同一文件、同一体积） | 1,124,780 | **10,064 ms** | 550 | **9,514** |
| 06:46:22 | `GET /browse/?datafile_id=178&page=1` | 3,039,301 | 870 ms | 848 | 22 |
| 06:45:39 | 同上 | 3,039,301 | 5,732 ms | 3,743 | 1,989 |
| 06:48:24 | `GET /auth/settings/` | 1,134 | 3,920 ms | 180 | **3,740** |
| 常态 | `GET /auth/settings/` | 1,134 | 16–180 ms | — | — |

同一 URL、同一 `file_id`、同一 1,124,780 字节：渲染进程刚崩溃重启空闲时 **51 ms**，7 秒后挂上「查看数据」
标签变成 **10,064 ms**，其中后端只花 550 ms。⇒ 用户感到的"卡"发生在渲染进程内部，后端只是次要贡献。

`tail` 段包含 Chromium 收到响应→axios 拦截器执行→console 跨进程转发的整段，现有日志**无法**再拆出
GC / AG Grid 布局 / IPC 三者各占多少 —— 这正是 E 阶段要测的东西。

### 1.3 载荷量级（今日 25.6 MB 响应）

| 端点 | 次数 | 合计 | 单次最大 |
|---|---|---|---|
| `GET /browse/` | 7 | 14.59 MB | **2,968 KB**（100 行/页，file 178） |
| `GET /summary/` | 9 | 7.19 MB | **1,149 KB** |
| 其余 24 个端点合计 | 250 | 3.8 MB | — |

### 1.4 机器侧同时处于提交内存压力

后端内存在 15:02:34 打的护栏 WARNING（GBK 写入 → 日志里是乱码，见 §4 D 项）：

```
INFO  apps.common.memory: 内存预警: total_ram=31.5GB budget=8.0GB jobs=2.0GB web=6.0GB
                           cache=1.5GB system_available=16.0GB commit=32.7GB/40.0GB
WARN  apps.common.memory: 系统可用提交内存 7.4GB 低于预算 8.0GB
```

物理可用 16.0 GB，但可用**提交**内存只剩 7.4 GB ⇒ 撞的是提交上限，不是 RAM。判据与
`docs/tasks/lessons.md` 2026-10-18「崩池轮第二种成因」完全同一条：**只看可用物理内存会得出相反结论**。

## 2. 内存是怎么被驻留的（代码可核对）

1. `frontend/src/pages/data/DataBrowserAgGrid.vue:68-69` `cacheBlockSize` = 设置的每页行数
   （`apps/common/constants.py:14-15` 钳 50–500），`maxBlocksInCache=20` **写死** ⇒ 单表驻留 20 块。
   file 178 实测 3 MB/100 行 ⇒ 约 60 MB 传输体量；把每页行数调到 500 就是 10 倍。
2. `frontend/src/pages/data/components/browser/browserRows.ts:17-33` 把「值数组」页 zip 成
   **每行一个含全部列键的对象**。生产 file 178 与本地夹具 ETS88 都是千列级（ETS88 表头 **1,728 列**），
   20 块 × 100 行 = 2,000 个字典模式对象、约 345 万个属性。该文件自己的注释就记着上一次事故：
   「68k×142 依赖追踪实测 +1.3GB 堆 + 5s 阻塞」（`browserRows.ts:14-15`）。
3. `DataManagement.vue:117` 查看标签上限 4 个，`:55-63` 用 `v-show` 而非 `v-if` ⇒ 4 份表格连同缓存
   **同时挂载**；`MainLayout.vue:12` `keep-alive :max="10"` 再把整页留在内存。切走的标签没有任何
   `onDeactivated` 钩子（该文件只有 `onMounted:260` 与 `onUnmounted:201`）⇒ 驻留量按标签数线性叠加。
4. 每个标签各持一份 1.1 MB 的 `/summary/`。
5. 重复请求放大同一份抖动：`DataManagement.vue:236` `onMounted(loadFiles)` 与 `:242` `onActivated(loadFiles)`
   在 keep-alive 下首次进入**都触发** ⇒ `files/?page_size=9999`(47KB) 每进页面拉 2 次；
   `/auth/settings/` 被 6 个互不相干的单飞缓存各拉一遍（`utils/echarts-theme.ts:53`、
   `utils/exportTimeout.ts:43`、`utils/filenameWrap.ts:33`、`utils/sftpTimeout.ts:42`、
   `composables/useChartMemory.ts:60`、`DataBrowserAgGrid.vue:260-262`）。同一形态还存在于
   `AnalysisPage.vue:52-53`、`DashboardPage.vue:247+258`、`SftpBrowser.vue:285+289`、
   `SftpSearchPage.vue:274+282`。

## 3. AG Grid 语义约束（已从安装的 35.3.0 包体核对，勿凭记忆设计）

- `dist/ag-grid-community.js:68515-68528`：`maxBlocksInCache` / `cacheBlockSize` 在**创建 InfiniteCache 时快照**
  进 `cacheParams`，注释明确「改了要等下次新建 cache 才生效（通常是 filter/sort 变化或换 datasource）」。
  ⇒ 运行时改 prop 不保证立即生效，**所以封顶值必须在首块加载前算好**，不要指望热更新 prop。
- `:68244-68249`：`blocksToKeep = maxBlocksInCache - 1`，且 `isBlockCurrentlyDisplayed` 的块**永不**被清。
  ⇒ 写预算时按「cap 减 1」理解驻留块数。
- 包里**没有** `setMaxBlocksInCache()`（全文检索零命中）⇒ 唯一可行入口是 prop + 首块前定值。
- `col_count` 已在 API 契约里（`apps/datafiles/serializers.py:73`、`frontend/src/api/datafiles.ts:47`），
  且 `DataBrowserAgGrid` 已通过 `:files="files"`（`DataManagement.vue:59`）拿到整个文件列表
  ⇒ **零新增请求、零新增 prop** 就能在首块前拿到列数。

## 4. 决策

**D1 封顶用「单元格数」而非块数或 MiB。** 块数是列宽的函数，MiB 需要现场探针才可定；
用 `blockSize × colCount` 表达的保留量，对窄文件保持今天的行为（仍 20 块），只对宽文件收紧。
预算常数由 E 阶段实测的「每单元格堆字节」反推，公式与验算写进 §5，不许拍脑袋填数。

**D2 两个约束，不是一个。**
- 单块上限 `CELL_PER_BLOCK_MAX`：防止「每页 500 行 × 1,728 列 = 86.4 万格」这种一块就爆的设置。
  实际每页行数 = `min(设置的 page_size, floor(CELL_PER_BLOCK_MAX / colCount))`，下限仍守 `PAGE_SIZE_MIN=50`。
- 驻留上限 `CELL_RETAIN_BUDGET`：`maxBlocksInCache = clamp(floor(CELL_RETAIN_BUDGET / (行×列)), 1, 20)`。

**D3 语义变化必须可见。** 用户把「每页行数」设成 500，实际只取 100 —— 这是口径变更，
必须在页面上提示（tooltip/help 文案），不能静默改。遵守 lessons 里「匹配判据一变，提示与用户指南同步改」。

**D4 非激活标签释放缓存。** `v-show` 保留 DOM（切回不闪），但 `onDeactivated` 调 `purgeInfiniteCache()`，
`onActivated` 让 IRM 自然重新拉当前视口的块。切走的表不再驻留 20 块。

**D5 顺带修 `AG Grid: warning #26`（生产日志 06:45:39 实测两条）**：`gridApi` 只在
`useBinCellMenu.ts:28,39-41` 赋值、从不置空，`watch(props.fileId)` 是 pre-flush ⇒ `reload()` 打到已销毁实例。
这条不是性能项，但它证明生命周期缺 `onGridDestroyed` 接线，D4 正好一起补。

**D6 不做的事**：不加 GZip（`config/settings/base.py:106-108` 为 68 MB JSON 花 3.6 s CPU 而刻意移除）；
不动后端 `/browse/`、`/summary/` 的载荷形状（B 项）；不碰 `2026-10-21` 内存治理三批（C 项）；
不改 Electron 日志分级与编码（D 项）。这些各有价值，但都不在本轮授权范围。

## 5. E 阶段必须回答的四个问题（判据先验算）

| # | 问题 | 判据 |
|---|---|---|
| Q1 | 单块（100 行 × 1,728 列）在渲染进程占多少 MiB 堆？ | `Δheap = heap(载入 1 块后) − heap(载入前)`，两轮差 <20% |
| Q2 | 满缓存（cap 块）与 4 标签叠加的峰值？ | 逐形状列表，与生产 file 178 传输字节同数量级校验 |
| Q3 | 「Chromium 收到响应 → JS 处理完」的间隔与 long task 时长 | `responseEnd` vs 同窗 longtask 区间；给出最长一条 |
| Q4 | 反推预算常数 | `CELL_RETAIN_BUDGET = floor(RETAIN_MIB_TARGET / (Q1 / 每块单元格数))`；**代入窄文件验算**：142 列 × 100 行时算出的 cap 必须仍为 20（否则阈值定错，窄文件也被砍） |

`RETAIN_MIB_TARGET`（单表驻留目标）本轮先取 **48 MiB**，E 结束时按 Q1/Q2 复核；它只是常数初值，
最终值必须来自实测并写进 `docs/reference/renderer-memory-baseline-2026-10-22.md`。

## 6. 验收

- 前端：`blockCap` 纯函数 vitest 承重测试带对照组（窄文件行为不变、宽文件必须降）。
- 复跑探针：整改后 Q2 的 4 标签峰值相对整改前必须显著下降，并把两组数字写进 baseline 文档。
- 门禁节奏按 `docs/reference/testing-gates.md`：每批 commit 前 `cd frontend && npm run test:e2e:affected`，
  收口 `node scripts/e2e_pool.mjs --slots=4` + 后端全套；判绿取日志末尾 `RESULT:` 行，不取 `$?`。
- 双主题：本轮只动 tooltip 文案与表格无关样式，仍需在 dark/light 下各看一眼（`AGENTS.md` 那条硬约束）。
