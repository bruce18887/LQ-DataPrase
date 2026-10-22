# 渲染进程内存与重复请求整改 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用实测复现取代拍脑袋，消除桌面端「查看数据」页因 20 块 × 千列行对象驻留导致的秒级冻结与渲染进程 OOM，并去掉每次导航的重复请求风暴。

**Architecture:** 先在既有 Playwright 栈里加一个 env 门控的渲染进程探针（CDP `Performance.getMetrics` + `Runtime.getHeapUsage` + `longtask` 观察器 + Resource Timing），用它测出「每单元格堆字节」，反推出以**单元格数**表达的块缓存预算；再把该预算做成可单测的纯函数接进 AG Grid IRM，并补 `onActivated/onDeactivated` 生命周期与设置单一 store。

**Tech Stack:** Vue 3 Composition API、Pinia、ag-grid-community 35.3.0（IRM）、Playwright（channel msedge）、vitest（node 环境，无 jsdom）、Django `e2e_slot` 档。

**Spec:** `docs/superpowers/specs/2026-10-22-desktop-lag-renderer-memory-design.md`（含生产日志实测表、AG Grid 包体语义核对、D1–D6 决策）

## Global Constraints

- 门禁节奏唯一事实来源 `docs/reference/testing-gates.md`：每批 commit 前 `cd frontend && npm run test:e2e:affected`；收口 `node scripts/e2e_pool.mjs --slots=4` + 后端全套；**判绿取日志末尾 `RESULT:` 行，不取 `$?`**；`NO AFFECTED TESTS` 不是绿灯。
- 单文件不超过 600 行（`.claude/CLAUDE.md`）。`DataBrowserAgGrid.vue` 已接近上限，新增逻辑一律放独立模块，不往里塞。
- 前端改动必须 dark/light 双主题都过一眼（`AGENTS.md`）。
- 并行度只有 `--slots` / `E2E_SLOTS` 一个旋钮，**不许改 playwright 的 `workers`**。
- 临时产物落 `tasks/`（gitignored），测试文件落 `frontend/test/` 或 `frontend/e2e/`，正式文档落 `docs/`。
- 探针 fixture 用既有种子：`e2e/fixtures/test-data.ts` 的 `SEEDED_FILES.ETS88_FT`（`test/e2e-data` 下 12.8 MB、表头 **1,728 列**，与生产 file 178 同形态）。
- 本轮不改后端 `/browse/`、`/summary/` 载荷形状，不加 GZip，不动 `2026-10-21` 内存治理三批，不改 Electron 日志分级。

---

## 文件结构（先定边界再动手）

| 文件 | 责任 | 动作 |
|---|---|---|
| `frontend/e2e/helpers/viewTab.ts` | 「搜索定位文件 → 点查看 → 等 ag-root」唯一实现 | 新建（从 `view-data.spec.ts:11-23` 抽出） |
| `frontend/e2e/helpers/rendererMetrics.ts` | 渲染进程取样：堆、long task、Resource Timing | 新建 |
| `frontend/e2e/data/renderer-memory.spec.ts` | 三形状复现与数字落盘（env 门控） | 新建 |
| `docs/reference/renderer-memory-baseline-2026-10-22.md` | 实测数字表 + 常数反推过程 | 新建 |
| `frontend/src/pages/data/components/browser/blockCap.ts` | 纯函数：给定设置页大小与列数，算出实际每块行数与缓存块数 | 新建 |
| `frontend/test/unit/blockCap.spec.ts` | 上述纯函数的承重单测 | 新建 |
| `frontend/src/pages/data/DataBrowserAgGrid.vue` | 接预算、补生命周期、可见提示 | 改 |
| `frontend/src/stores/userSettings.ts` | `/auth/settings/` 唯一持有者 | 新建 |
| `frontend/src/utils/{echarts-theme,exportTimeout,filenameWrap,sftpTimeout}.ts` | 各自私有 fetch 缓存 → 读 store | 改 |
| `frontend/src/composables/useChartMemory.ts` | 换掉它自取的 GET；自身 debounce/keepalive 逻辑留在原地 | 改 |
| `frontend/src/pages/settings/SettingsPage.vue` | 整对象 PUT → 脏字段 PUT | 改 |
| `frontend/src/stores/auth.ts` | 五次 reset → store 一次失效 | 改 |

---

## 批 E：先测，再定阈值

### Task 1: 渲染进程取样探针骨架

**Files:**
- Create: `frontend/e2e/helpers/viewTab.ts`
- Create: `frontend/e2e/helpers/rendererMetrics.ts`
- Create: `frontend/e2e/data/renderer-memory.spec.ts`
- Modify: `frontend/e2e/data/view-data.spec.ts:11-23`（删掉本地 `openViewTab`，改 import）

**Interfaces:**
- Consumes: `gotoApp()`（`e2e/helpers/nav.ts:7`）、`SEEDED_FILES`（`e2e/fixtures/test-data.ts`）、Playwright `page.context().newCDPSession(page)`
- Produces:
  - `openViewTab(page: Page, filename: string): Promise<void>`
  - `startRendererMetrics(page: Page): Promise<RendererMetrics>`，其中
    `RendererMetrics = { snapshot(label: string): Promise<MetricRow>; stop(): Promise<void> }`
    `MetricRow = { label: string; jsHeapUsedMiB: number; longTasksMsTotal: number; longestTaskMs: number; requests: Array<{ url: string; responseEndMs: number; durationMs: number; transferMiB: number }> }`

- [ ] **Step 1: 抽出两个 tab helper（不是只抽一个）**

`view-data.spec.ts` 里有两个函数都要搬：`openViewTab`（`:11-23`，内含 `gotoApp` ⇒ 整页重载，
**会把标签列表重置回一个空白页**）与 `openFileInViewTab`（`:34+`，注释明确「不能用 gotoApp」）。
探针的第 3 个形状是「4 个标签同时在内存」，只有后者能表达 —— 用它自己的 helper，否则那组数字
量的是「一个标签反复重载」，形状根本不对。

```typescript
// frontend/e2e/helpers/viewTab.ts
import type { Page } from '@playwright/test'
import { expect } from '@playwright/test'
import { gotoApp } from './nav'

/**
 * 进入查看数据 tab：文件列表服务端搜索定位目标文件 → 点「查看」。
 * 服务端 search 不受分页/下拉时序影响，比 banner 下拉更稳。
 */
export async function openViewTab(page: Page, filename: string) {
  await gotoApp(page, '/data')
  const searchInput = page.locator('input[placeholder="按文件名/程序名/标签搜索"]')
  await searchInput.fill(filename.slice(0, 15))
  const row = page
    .locator('.el-table .el-table__row')
    .filter({ hasText: filename.slice(0, 12) })
    .first()
  await expect(row).toBeVisible({ timeout: 30_000 })
  await row.locator('button').filter({ hasText: '查看' }).click()
  await expect(page.locator('.tab-btn.active')).toContainText('查看数据')
  await expect(page.locator('.ag-root').first()).toBeVisible({ timeout: 30_000 })
}
```

同一个 `viewTab.ts` 里再放 `openFileInViewTab`（把 `view-data.spec.ts:34+` 的函数体原样搬来并 `export`，
它依赖「同一页面内不重载」的语义，一行都不许改）。`view-data.spec.ts` 删掉这两个本地定义，改为
`import { openViewTab, openFileInViewTab } from '../helpers/viewTab'`。

- [ ] **Step 2: 写取样 helper**

关键约束：`longtask` 观察器必须在**首次导航之前**装进页面，所以 `addInitScript` 不能放在 `gotoApp` 之后；
堆与计时指标走 CDP，不依赖产品代码里任何埋点。

```typescript
// frontend/e2e/helpers/rendererMetrics.ts
import type { Page } from '@playwright/test'

export interface MetricRequest {
  url: string
  responseEndMs: number
  durationMs: number
  transferMiB: number
}
export interface MetricRow {
  label: string
  jsHeapUsedMiB: number
  longTasksMsTotal: number
  longestTaskMs: number
  requests: MetricRequest[]
}
export interface RendererMetrics {
  snapshot(label: string): Promise<MetricRow>
  stop(): Promise<void>
}

const HEAVY = /\/(browse|summary)\//

/** 必须在任何导航前调用（longtask 观察器要注入到文档创建前）。 */
export async function startRendererMetrics(page: Page): Promise<RendererMetrics> {
  await page.addInitScript(() => {
    const w = window as unknown as { __lt?: Array<{ start: number; dur: number }> }
    w.__lt = []
    try {
      new PerformanceObserver((l) => {
        for (const e of l.getEntries()) w.__lt!.push({ start: e.startTime, dur: e.duration })
      }).observe({ entryTypes: ['longtask'] })
    } catch {
      /* 通道不支持 longtask 时探针仍要能跑，不能把自己测死 */
    }
  })

  const cdp = await page.context().newCDPSession(page)
  await cdp.send('Performance.enable')
  await cdp.send('Runtime.enable')

  const heapMiB = async (): Promise<number> => {
    const { usedSize } = await cdp.send('Runtime.getHeapUsage')
    return usedSize / 1048576
  }

  return {
    async snapshot(label: string): Promise<MetricRow> {
      const heap = await heapMiB()
      const lt = await page.evaluate(() => (window as any).__lt ?? [])
      const reqs = await page.evaluate(
        (re: string) =>
          performance
            .getEntriesByType('resource')
            .filter((e) => new RegExp(re).test(e.name))
            .map((e) => ({
              url: e.name.replace(/^.*\/api\/v1/, ''),
              responseEndMs: Math.round(e.responseEnd),
              durationMs: Math.round(e.duration),
              transferMiB: +(e.transferSize / 1048576).toFixed(2),
            })),
        HEAVY.source,
      )
      return {
        label,
        jsHeapUsedMiB: +heap.toFixed(1),
        longTasksMsTotal: Math.round(lt.reduce((a: number, x: any) => a + x.dur, 0)),
        longestTaskMs: Math.round(lt.reduce((a: number, x: any) => Math.max(a, x.dur), 0)),
        requests: reqs,
      }
    },
    async stop() {
      await cdp.detach().catch(() => undefined)
    },
  }
}
```

- [ ] **Step 3: 写探针 spec（env 门控，默认跳过）**

```typescript
// frontend/e2e/data/renderer-memory.spec.ts
import { test, expect } from '@playwright/test'
import { writeFileSync, mkdirSync } from 'node:fs'
import path from 'node:path'
import { SEEDED_FILES, PROJECT_ROOT } from '../fixtures/test-data'
import { openViewTab, openFileInViewTab } from '../helpers/viewTab'
import { startRendererMetrics } from '../helpers/rendererMetrics'

/** 探针产物目录：必须落在**本树**的 tasks/。相对路径 `../../tasks` 会按 process.cwd()
 * （= frontend/）解析到**父检出**的 tasks/ —— lessons 2026-10-16 那条「探针相对路径静默解到父检出」。
 * `PROJECT_ROOT` 由 `fixtures/test-data.ts` 从自身文件位置算出，天然指向本树，不要再另拼相对路径。 */
const OUT_DIR = path.join(PROJECT_ROOT, 'tasks')

/**
 * 渲染进程内存探针（spec §5 Q1–Q3）。默认不跑：翻 20 块千列表要几十秒，
 * 挂在每批门禁里只会逼人把它注释掉。
 *   LQDP_PERF_PROBE=1 npx playwright test --project=P2 e2e/data/renderer-memory.spec.ts
 */
const ENABLED = !!process.env.LQDP_PERF_PROBE
test.describe.configure({ mode: 'serial' })
test.skip(!ENABLED, 'LQDP_PERF_PROBE 未设置')

/** 把中心视口滚到底 n 次，逼 IRM 逐块向服务端取数。 */
async function scrollBlocks(page: import('@playwright/test').Page, n: number) {
  const vp = page.locator('.ag-center-cols-viewport').first()
  for (let i = 0; i < n; i++) {
    const done = page.waitForResponse((r) => /\/browse\//.test(r.url()), { timeout: 60_000 })
    await vp.evaluate((el) => {
      el.scrollTop = el.scrollHeight
    })
    await done
  }
}

/** 被测文件由环境变量选，Task 2 要跑「千列」与「窄」两种形状，不改代码只换 env。 */
const PROBE_KEY = process.env.LQDP_PROBE_FILE ?? 'ETS88_FT'
const PROBE = SEEDED_FILES[PROBE_KEY]
if (!PROBE?.filename) throw new Error(`SEEDED_FILES 里没有 ${PROBE_KEY}`)

test(`@p2 [${PROBE_KEY}] 1 块 / 满缓存 / 4 标签的堆与 long task`, async ({ page }) => {
  const m = await startRendererMetrics(page)
  const rows = []

  await openViewTab(page, PROBE.filename)
  await page.waitForResponse((r) => /\/browse\//.test(r.url()))
  rows.push(await m.snapshot('1 块（首屏）'))

  await scrollBlocks(page, 19)
  rows.push(await m.snapshot('20 块满缓存（1 个标签）'))

  for (let i = 0; i < 3; i++) {
    await page.locator('.tab-btn').filter({ hasText: /^\+/ }).first().click()
    await openFileInViewTab(page, PROBE.filename)
    await page.waitForResponse((r) => /\/browse\//.test(r.url()))
  }
  rows.push(await m.snapshot('4 个标签（各 1 块）'))

  await m.stop()
  mkdirSync(OUT_DIR, { recursive: true })
  writeFileSync(path.join(OUT_DIR, `renderer-probe-${PROBE.filename}.json`), JSON.stringify(rows, null, 2))
  // 承重前置：真的取到了 20 块，否则后面所有数字都是「没翻页」的假绿
  expect(rows[1].requests.length).toBeGreaterThanOrEqual(20)
  expect(rows[1].jsHeapUsedMiB).toBeGreaterThan(rows[0].jsHeapUsedMiB)
  for (const r of rows) console.log(`${r.label}: heap=${r.jsHeapUsedMiB}MiB longTask=${r.longTasksMsTotal}ms max=${r.longestTaskMs}ms reqs=${r.requests.length}`)
})
```

- [ ] **Step 4: 跑通探针（无阈值，只看能否出数）**

Run: `cd frontend && node ../scripts/e2e_pool.mjs --slots=1 -- data/renderer-memory.spec.ts`
（先 `LQDP_PERF_PROBE=1`；判据取日志末尾 `RESULT:` 行）
Expected: PASS 且打印三行 `heap=… longTask=… reqs=…`，`tasks/renderer-probe.json` 存在。
若 `reqs < 20`：说明滚动没触发取数（多半是 `.ag-center-cols-viewport` 选择器在这个主题下不对），
先修探针再进 Task 2，**不要**把阈值改成迁就它。

- [ ] **Step 5: 确认没把既有 spec 改坏，提交**

Run: `cd frontend && npx playwright test --project=P1 e2e/data/view-data.spec.ts 2>&1 | tail -30`
Expected: 全绿（证明抽 helper 没动行为）

```bash
git add frontend/e2e/helpers/viewTab.ts frontend/e2e/helpers/rendererMetrics.ts frontend/e2e/data/renderer-memory.spec.ts frontend/e2e/data/view-data.spec.ts
git commit -m "test(e2e): 加渲染进程内存探针，openViewTab 抽成 helper 复用"
```

---

### Task 2: 三形状实测 + 常数反推（写进 baseline 文档）

**Files:**
- Create: `docs/reference/renderer-memory-baseline-2026-10-22.md`
- Test: `frontend/e2e/data/renderer-memory.spec.ts`（Task 1 产物，本任务只跑不改）

**Interfaces:**
- Consumes: `tasks/renderer-probe.json`
- Produces: 三个常数的**实测值**，Task 3 直接抄进 `blockCap.ts`：
  `CELL_PER_BLOCK_MAX`、`CELL_RETAIN_BUDGET`、`RETAIN_MIB_TARGET`

- [ ] **Step 1: 采集两组列宽差异大的形状**

ETS88（1,728 列）之外再跑一只窄文件做对照，用来验算「窄文件行为必须不变」。**不改代码，只换 env**：
先 `grep -n 'export const SEEDED_FILES' -A 24 e2e/fixtures/test-data.ts` 取一个列数最少（≤200 列）的键名，
再
Run: `LQDP_PERF_PROBE=1 LQDP_PROBE_FILE=<那个键> node ../scripts/e2e_pool.mjs --slots=1 -- data/renderer-memory.spec.ts`
产物落在 `tasks/renderer-probe-<键名>.json`（Task 1 用 PROJECT_ROOT 拼路径，不会写到父检出）。

- [ ] **Step 2: 把数字算成「每单元格堆字节」**

单元格数 = `行数 × 列数`。每块 100 行 × 1,728 列 = **172,800 格**。

```
mib_per_cell   = (heap_20块 − heap_1块) / (19 × 172800)      ← Q1，两轮差须 <20%
CELL_PER_BLOCK_MAX = floor(RETAIN_MIB_TARGET / mib_per_cell) ← 单块也别超目标预算
CELL_RETAIN_BUDGET = floor(RETAIN_MIB_TARGET / mib_per_cell) ← 驻留总格数
```

`RETAIN_MIB_TARGET` 起点 48 MiB，按 Q2 校准：**4 个标签同时驻留**必须让堆峰值低于生产机可用提交内存的
十分之一（今天该机 commit 只剩 7.4 GB；4 × 48 = 192 MiB 远低于该量级，若实测远超预期就下调目标）。

- [ ] **Step 3: 验算阈值能不能过（判据不许事后补）**

把算出的 `CELL_RETAIN_BUDGET` 代进 Task 3 的公式，手算两行写进文档：

| 文件 | 设置页大小 | 列数 | 期望 cap | 期望实际每块行数 |
|---|---|---|---|---|
| 窄（142 列） | 100 | 142 | **必须仍是 20** | 100（不变） |
| ETS88（1,728 列） | 100 | 1,728 | 2–4（**实测落 8，见裁定 R10：区间来自未实测占位，采纳 8**） | 100 |
| ETS88 | 500 | 1,728 | ≥1 | `floor(CELL_PER_BLOCK_MAX/1728)`，且不低于 50 |

窄文件算出来不是 20 ⇒ 阈值定错，回 Step 2 重算，**不许**放宽断言迁就它。

- [ ] **Step 4: 写 baseline 文档**

结构照 `docs/reference/perf-baseline-2026-10-17.md`：**只写有命令产出过的数字**，附复跑命令、
原始 `tasks/renderer-probe.json` 摘录、上面三行的代入过程与最终常数。

- [ ] **Step 5: 把两个常数写进 baseline 文档的「交付值」小节（本任务不改代码）**

`blockCap.ts` 是 Task 3 才创建的文件 ⇒ Task 2 **没有文件可回填**（原计划这一步写反了顺序）。
本任务只交付数值与推导，Task 3 直接照抄：
- `CELL_RETAIN_BUDGET = floor(RETAIN_MIB_TARGET / mib_per_cell)`
- `CELL_PER_BLOCK_MAX = floor(CELL_RETAIN_BUDGET / 4)`（**保证至少还能驻留 4 块**，否则每页行数被钳到
  「一块就吃满预算」，翻页会退化成请求风暴——与 `browse_views.py` 里那条「50 下限是为滚动别变成请求风暴」同源）
- 代入验算表（窄文件 142 列必须仍算出 20 块、`effectiveBlockSize(500,142)=500`）连同**实测分母**一起写。
  实测分母已由 Task 1 交付：ETS88 是 `rowsPerBlock=50 × colCount=1728 = 86,400 格/块`，
  不是计划初稿假设的 172,800（生产 page_size=100 才是那个数）；`mib_per_cell ≈ 3.38e-5`。

Run: `cd frontend && npx vitest run`（此步应无变化，仅确认文档没混进代码改动）

- [ ] **Step 6: 提交**

```bash
git add docs/reference/renderer-memory-baseline-2026-10-22.md
git commit -m "docs(reference): 渲染进程内存基线实测与块预算常数反推"
```

---

## 批 A：整改

### Task 3: 块预算纯函数（T2 承重单测）

**Files:**
- Create: `frontend/src/pages/data/components/browser/blockCap.ts`
- Create: `frontend/test/unit/blockCap.spec.ts`

**Interfaces:**
- Consumes: Task 2 的三个常数
- Produces（Task 4 依赖的确切签名）:
  - `effectiveBlockSize(settingsPageSize: number, colCount: number | null | undefined): number`
  - `maxBlocksInCache(blockSize: number, colCount: number | null | undefined): number`
  - `BLOCK_SIZE_MIN`、`BLOCK_SIZE_MAX`、`DEFAULT_COL_COUNT`

- [ ] **Step 1: 先写断言关系的单测（不钉死常数）**

断言只写「单调性、钳位、窄文件不变」，常数由 Task 2 决定 —— 这样 Task 2 改数不会让这里红。
每条都带对照组（照 lessons「断言必须承重而不是全绿」）：

```typescript
// frontend/test/unit/blockCap.spec.ts
import { describe, it, expect } from 'vitest'
import {
  effectiveBlockSize,
  maxBlocksInCache,
  BLOCK_SIZE_MIN,
  BLOCK_SIZE_MAX,
  DEFAULT_COL_COUNT,
} from '../../src/pages/data/components/browser/blockCap'

describe('effectiveBlockSize', () => {
  it('列数未知/为 0 时完全不动用户设置（对照组）', () => {
    for (const n of [50, 100, 500]) {
      expect(effectiveBlockSize(n, null)).toBe(n)
      expect(effectiveBlockSize(n, 0)).toBe(n)
    }
  })
  it('窄文件不降（对照组：必须等于设置值）', () => {
    expect(effectiveBlockSize(500, DEFAULT_COL_COUNT)).toBe(500)
    expect(effectiveBlockSize(100, 60)).toBe(100)
  })
  it('千列文件必须被压到单块预算内，且不低于下限', () => {
    const n = effectiveBlockSize(500, 1728)
    expect(n).toBeLessThan(500)
    expect(n).toBeGreaterThanOrEqual(BLOCK_SIZE_MIN)
  })
  it('单调：列数越多，每块行数不增', () => {
    let prev = Infinity
    for (const cols of [50, 200, 800, 1728, 4000]) {
      const n = effectiveBlockSize(500, cols)
      expect(n).toBeLessThanOrEqual(prev)
      prev = n
    }
  })
})

describe('maxBlocksInCache', () => {
  it('窄文件仍是 20 块（对照组，与今天一致）', () => {
    expect(maxBlocksInCache(100, DEFAULT_COL_COUNT)).toBe(20)
    expect(maxBlocksInCache(100, null)).toBe(20)
  })
  it('千列文件必须显著小于 20', () => {
    expect(maxBlocksInCache(100, 1728)).toBeLessThan(20)
    expect(maxBlocksInCache(100, 1728)).toBeGreaterThanOrEqual(1)
  })
  it('钳位下界恒为 1（当前块永不驱逐）', () => {
    expect(maxBlocksInCache(500, 4000)).toBe(1)
  })
})
```

- [ ] **Step 2: 跑到失败**

Run: `cd frontend && npx vitest run test/unit/blockCap.spec.ts`
Expected: FAIL — `Failed to resolve import ".../blockCap"`

- [ ] **Step 3: 写实现（常数取 Task 2 交付值；下面按实测 `mib_per_cell = 3.38e-5` 与 48 MiB 目标算好）**

`CELL_RETAIN_BUDGET = floor(48 / 3.38e-5) = 1,420,118`；`CELL_PER_BLOCK_MAX = floor(预算 / 4) = 355,029`
（**除以 4 是刻意的**：定成等于预算会让「一块吃满预算」，翻页退化成请求风暴）。
Task 2 若给出第二版数字，以 baseline 文档为准重算。常量放本文件顶部，不拆第二个文件：

```typescript
export const BLOCK_SIZE_MIN = 50
export const BLOCK_SIZE_MAX = 500
/** 列数未知时按历史基线宽度处理（142 列，见 docs/reference/perf-baseline-2026-10-17.md） */
export const DEFAULT_COL_COUNT = 142
/** 驻留块数上限：今天 DataBrowserAgGrid 写死的值，窄文件必须保持不变 */
export const MAX_BLOCKS = 20
/** 单块格数上限 = 驻留预算 / 4 ⇒ 最坏情况仍驻留 4 块；推导见 baseline 文档 */
export const CELL_PER_BLOCK_MAX = 355_029
/** 驻留格数预算 = 48 MiB ÷ 3.38e-5 MiB/格（Task 1 探针实测，分母 86,400 格/块） */
export const CELL_RETAIN_BUDGET = 1_420_118

function cols(colCount: number | null | undefined): number {
  return colCount && colCount > 0 ? colCount : 0
}

/**
 * 实际每块行数：用户设置的每页行数，被「单块格数预算」按列数压低。
 * 列数未知 ⇒ 不压（保持设置值），因为压低会静默改变分页语义。
 */
export function effectiveBlockSize(
  settingsPageSize: number,
  colCount: number | null | undefined,
): number {
  const size = Math.max(BLOCK_SIZE_MIN, Math.min(BLOCK_SIZE_MAX, settingsPageSize || BLOCK_SIZE_MIN))
  const c = cols(colCount)
  if (!c) return size
  const byCells = Math.floor(CELL_PER_BLOCK_MAX / c)
  return Math.max(BLOCK_SIZE_MIN, Math.min(size, byCells))
}

/**
 * 缓存块数上限。注意 ag-grid 实际保留 `cap - 1` 块（`purgeBlocksIfNeeded` 的 `blocksToKeep`），
 * 且当前显示块永不驱逐，所以这里给的是上限而非精确驻留数。
 */
export function maxBlocksInCache(
  blockSize: number,
  colCount: number | null | undefined,
): number {
  const c = cols(colCount)
  if (!c) return MAX_BLOCKS
  const cellsPerBlock = Math.max(1, blockSize * c)
  return Math.max(1, Math.min(MAX_BLOCKS, Math.floor(CELL_RETAIN_BUDGET / cellsPerBlock)))
}
```

- [ ] **Step 4: 跑到通过**

Run: `cd frontend && npx vitest run test/unit/blockCap.spec.ts`
Expected: PASS 7 条。若「窄文件仍是 20 块」红 ⇒ Task 2 的常数偏小，回 Task 2 重算，别改断言。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/data/components/browser/blockCap.ts frontend/test/unit/blockCap.spec.ts
git commit -m "feat(view-data): 块缓存预算纯函数（按单元格数封顶）"
```

---

### Task 4: 接预算 + 非激活标签释放 + 修 warning #26 + 可见提示

**Files:**
- Create: `frontend/src/pages/data/composables/useIrmSizing.ts`（**600 行上限逼出来的**：该 .vue 现状
  **598 行**（Task 4 开工前 `wc -l` 复取），新增的 12–20 行放不进去）
- Modify: `frontend/src/pages/data/DataBrowserAgGrid.vue:67-69`（prop 绑定）、`:225-226`（blockSize 初值）、`:260-290`（onMounted 取 page_size、`applyBlockSize`）、`:486-517`（`getRows` 的 `page_size`）、模板分页/表头区加提示
- Modify: `frontend/e2e/helpers/nav.ts:24`（加 `collectConsoleWarnings`）
- Test: `frontend/e2e/data/renderer-memory.spec.ts`（追加一条断言：切走再切回不报错、无 #26）
- Test: `frontend/test/unit/useIrmSizing.spec.ts`（composable 的钳位/驱逐判据）

**硬性收尾判据：** `wc -l frontend/src/pages/data/DataBrowserAgGrid.vue` 必须 ≤ 600。
新逻辑（`gridAlive`、`purgeCacheIfAlive`、`colCount`/`maxBlocks`/`settingsPageSize`）一律进 composable，
.vue 只留 prop 绑定与一次解构。

**Interfaces:**
- Consumes: `effectiveBlockSize`、`maxBlocksInCache`（Task 3）、`props.files`（已存在，`DataManagement.vue:59` 传入，元素带 `col_count`，`src/api/datafiles.ts:47`）
- Produces: 组件内 `blockSize`、`maxBlocks` 两个 computed/ref；无对外新导出

- [ ] **Step 1: 先写会红的 e2e 断言**

`DataBrowserAgGrid.vue` 目前**没有** `onActivated/onDeactivated`（只在 `:201` 有 `onUnmounted`、`:260` `onMounted`），
且生产日志实测 `AG Grid: warning #26 ... grid has been destroyed` 两条。加断言：

```typescript
// frontend/e2e/data/view-data.spec.ts 内新增（P1 档，不依赖 LQDP_PERF_PROBE）
test('@p1 切换文件标签不触发已销毁 grid 的 AG Grid #26 警告', async ({ page }) => {
  const warns: string[] = []
  page.on('console', (m) => {
    if (m.type() === 'warning') warns.push(m.text())
  })
  await openViewTab(page, SEEDED_FILES.ETS88_FT.filename)
  await page.locator('.tab-btn').filter({ hasText: /文件列表/ }).first().click()
  await page.locator('button').filter({ hasText: '查看' }).nth(1).click()
  await expect(page.locator('.ag-root').first()).toBeVisible({ timeout: 30_000 })
  expect(warns.filter((w) => /#26|has been destroyed/.test(w))).toEqual([])
})
```

同时给 `nav.ts` 加与 `collectConsoleErrors` 同形的 `collectConsoleWarnings`（若上面的内联监听已够，就不加，
避免无人使用的导出）。

- [ ] **Step 2: 跑到失败**

Run: `cd frontend && npx playwright test --project=P1 e2e/data/view-data.spec.ts -g '#26' 2>&1 | tail -20`
Expected: FAIL，数组里含 `purgeInfiniteCache() cannot be called as the grid has been destroyed`

**这一步绿了就不许往下走**：断言必须先在未改动的代码上真红，才证明它承重（照 lessons
「基线绿≠断言承重」）。红不出来就换触发动作（切 fileId → 关标签 → 立刻再开），直到它红。

- [ ] **Step 3: 接线**

`DataBrowserAgGrid.vue` 五处改动，逐处给旧→新。

⚠ 本文件 `:273-274` 已有本地 `const BLOCK_SIZE_MIN = 50` / `BLOCK_SIZE_MAX = 500`，与 `blockCap.ts`
导出的同名 ⇒ **只 import `effectiveBlockSize` 与 `maxBlocksInCache` 两个函数**，保留本地那对常量
（它们是「设置页可取范围」的校验，语义不同，别合并）。

1. prop 绑定（`:67-69`）：
```html
          :infiniteInitialRowCount="blockSize"
          :cacheBlockSize="blockSize"
          :maxBlocksInCache="maxBlocks"
```

2. 列数与预算（紧跟 `:226` 的 `const blockSize = ref(PAGE_SIZE_DEFAULT)` 之后新增；
   `col_count` 已在 `props.files` 里，`DataManagement.vue:59` 就传进来了 ⇒ 零新增请求、零新增 prop）：
```typescript
/** 当前文件列数：来自已传入的文件列表；未知（null）时预算完全不介入 */
const colCount = computed<number | null>(
  () => props.files.find((f) => f.id === props.fileId)?.col_count ?? null,
)
/** 账号设置里用户选的「默认每页行数」原值，仅用于提示实际是否被压低 */
const settingsPageSize = ref(PAGE_SIZE_DEFAULT)
const maxBlocks = computed(() => maxBlocksInCache(blockSize.value, colCount.value))
```

3. `applyBlockSize`（`:282-288`，旧实现见文件）改为「先校验设置值 → 再按列数钳单块格数 → 只在 grid 存活时 purge」：
```typescript
function applyBlockSize(raw: unknown) {
  const n = Number(raw)
  if (!Number.isInteger(n) || n < BLOCK_SIZE_MIN || n > BLOCK_SIZE_MAX) return
  settingsPageSize.value = n
  const sized = effectiveBlockSize(n, colCount.value)
  if (sized === blockSize.value) return
  blockSize.value = sized
  purgeCacheIfAlive()
}

let gridAlive = false

/**
 * `gridApi` 由 onGridReady 赋值且此前从不置空（composables/useBinCellMenu.ts:39-41），
 * 而 `watch(() => props.fileId)`（:405）是 pre-flush ⇒ 旧写法 `gridApi.value?.purgeInfiniteCache()`
 * 会打到已销毁实例，生产日志实测 AG Grid #26 两条（2026-10-22 06:45:39）。
 */
function purgeCacheIfAlive() {
  if (!gridAlive || !gridApi.value) return
  gridApi.value.purgeInfiniteCache()
}
```
`onMounted` 里 `await authApi.getSettings()`（:260-270）的续体回来后必须再判一次
`if (!gridAlive) return` —— 异步续体在卸载后落地是这条警告的第二个入口。`onGridReady` 里置
`gridAlive = true`，`onUnmounted`（:201-206）置 `false`。

4. 生命周期补齐（`:138` 的 import 加 `onActivated, onDeactivated`）：
```typescript
onDeactivated(() => {
  // v-show 的隐藏标签仍保持挂载（DataManagement.vue:55-63），20 块 × 千列的行对象
  // 一直留着就是生产那次 oom 的体积；切回来由 IRM 按视口自行重新取块。
  purgeCacheIfAlive()
})
```

5. 可见提示（spec D3：这是口径变更，不许静默改用户设的每页行数）——加在现有每页行数显示处，
   文案与 class 随该区块现状，**dark/light 各看一眼**：
```html
<span
  v-if="colCount && blockSize !== settingsPageSize"
  class="dim-text"
  :title="`该文件 ${colCount} 列：每页行数已从 ${settingsPageSize} 降为 ${blockSize} 以控制内存`"
>降页</span>
```

- [ ] **Step 4: 跑到通过 + 全量目检**

Run: `cd frontend && npx vitest run && npx playwright test --project=P1 e2e/data/view-data.spec.ts 2>&1 | tail -25`
Expected: vitest 全绿；view-data 档全绿（含新的 #26 断言）。
再手工起 `npm run electron:dev`，在 dark 与 light 主题各开一次千列表，确认提示文案可读、
滚动仍能连续取数（cap 生效后翻到第 5 页不该卡住）。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/data/DataBrowserAgGrid.vue frontend/e2e/data/view-data.spec.ts
git commit -m "fix(view-data): 块缓存按列数封顶、非激活标签释放、修 AG Grid #26 生命周期"
```

---

### Task 5: 导航期重复请求去重（5 个页面）

**Files:**
- Modify: `frontend/src/pages/data/DataManagement.vue:236,242`
- Modify: `frontend/src/pages/analysis/AnalysisPage.vue:52-53`
- Modify: `frontend/src/pages/dashboard/DashboardPage.vue:247,258`
- Modify: `frontend/src/pages/sftp/SftpBrowser.vue:285,289`
- Modify: `frontend/src/pages/sftp/SftpSearchPage.vue:274,282`
- Test: `frontend/e2e/data/file-list-completeness.spec.ts`（追加计数断言）
  ⚠ 执行期更正：该路径在本仓库**不存在**，真实文件是 `frontend/e2e/analysis/file-list-completeness.spec.ts`；
  而按裁定 R15/R19，计数守卫最终按「哪个档保护哪个页面」分放到 `e2e/data/data.spec.ts`（`pages/data/` → data+exports 档）
  与 `e2e/analysis/file-list-completeness.spec.ts`（`pages/analysis/` → analysis 档），并另在
  `e2e/dashboard/dashboard.spec.ts` 钉住仪表板的 `list_batches`/`files/options`（R16/R17）。

**Interfaces:**
- Consumes: 无新依赖
- Produces: 约定「keep-alive 路由页只用 `onActivated` 做首拉」，Task 6 沿用

- [ ] **Step 1: 写计数断言（红）**

`MainLayout.vue:12` 是 `keep-alive :max="10"`，首次进入 `mounted` 与 `activated` **都**触发 ⇒ 生产实测
`files/?page_size=9999` 一次导航 2 条。新增断言钉死为 1 条：

```typescript
// frontend/e2e/data/file-list-completeness.spec.ts 追加
test('@p1 进数据管理页只发一次全量文件列表', async ({ page }) => {
  const hits: string[] = []
  page.on('request', (r) => {
    if (/\/files\/\?page_size=9999/.test(r.url())) hits.push(r.url())
  })
  await gotoApp(page, '/data')
  await expect(page.locator('.el-table__row').first()).toBeVisible({ timeout: 30_000 })
  expect(hits).toHaveLength(1)
})
```

- [ ] **Step 2: 跑到失败**

Run: `cd frontend && npx playwright test --project=P1 e2e/data/file-list-completeness.spec.ts -g '只发一次' 2>&1 | tail -15`
Expected: FAIL — `Received length: 2`

- [ ] **Step 3: 只留 `onActivated`（5 个页面同法）**

```typescript
// DataManagement.vue：删掉 :236 的 onMounted(loadFiles)
// keep-alive 下首次进入必然触发 activated；这里刻意不再 onMounted，
// 否则一次导航拉两遍 page_size=9999（生产实测 2026-10-22 每条导航都翻倍）。
onActivated(loadFiles)
```
其余四处同样删 `onMounted`、保留 `onActivated`，并把各自原 `onMounted` 里的**非取数**副作用留在 `onMounted`
（例如 `SftpBrowser.vue:285` 的 `checkLastVisit()` 与 `loadTimeout()` 要一起进 `onActivated`，
因为两者都是「进页面才知道」的状态初始化；逐个读一遍再删，别机械删半边）。

- [ ] **Step 4: 跑到通过**

Run: `cd frontend && npx playwright test --project=P1 e2e/data/file-list-completeness.spec.ts e2e/data/view-data.spec.ts 2>&1 | tail -25`
Expected: 全绿。若某页首次进入空白 ⇒ 说明那页在 keep-alive 之外渲染，回退该页为
`onMounted` 单用并把断言改成该页专属计数（**逐个页面判断，不许一把梭**）。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/data/DataManagement.vue frontend/src/pages/analysis/AnalysisPage.vue frontend/src/pages/dashboard/DashboardPage.vue frontend/src/pages/sftp/SftpBrowser.vue frontend/src/pages/sftp/SftpSearchPage.vue frontend/e2e/data/file-list-completeness.spec.ts
git commit -m "perf(pages): keep-alive 页去重首屏请求，导航期不再翻倍拉全量文件列表"
```

---

### Task 6: `/auth/settings/` 收敛成单一 store

**Files:**
- Create: `frontend/src/stores/userSettings.ts`
- Modify: `frontend/src/utils/echarts-theme.ts`、`utils/exportTimeout.ts`、`utils/filenameWrap.ts`、`utils/sftpTimeout.ts`、`composables/useChartMemory.ts`、`pages/data/DataBrowserAgGrid.vue:259-270`、`stores/auth.ts:4-9,23-27,77-81`、`pages/settings/SettingsPage.vue:90,120-138`
- Test: `frontend/test/unit/userSettings.spec.ts`（新建）、`frontend/e2e/settings/*.spec.ts`（按实际红点修）

**Interfaces:**
- Consumes: `authApi.getSettings()`（`src/api/auth.ts:163-165`）、`authApi.updateSettings()`（`:166-168`）、`authApi.updateSettingsKeepalive()`（`:174-191`）
- Produces:
  - `useUserSettingsStore(): { raw: Ref<UserSettings|null>; ensure(): Promise<void>; patch(p: Partial<UserSettings>): void; save(p: Partial<UserSettings>): Promise<void>; saveKeepalive(p: Partial<UserSettings>): void; reset(): void }`
- **必须保持不变的对外契约**（改签名会打断路由守卫与同步 getter）：
  - `ensureChartRenderer(): Promise<void>` 仍返回 void，`router/index.ts:178` 在守卫里 await 它；
  - ⚠ 执行期更正（裁定 R23）：**只有 `getChartRenderer()` 是同步 getter**（图表初始化链路 `utils/echarts-init.ts` 里没法 await）；
    `getExportTimeoutMs()`（`utils/exportTimeout.ts:35`）、`getFilenameWrap()`（`utils/filenameWrap.ts:26`）、
    `getSftpTimeoutSec()/Ms()`（`utils/sftpTimeout.ts:35/43`）**本来就是 `Promise<…>`**，调用点也本来就是 `await`
    （`BatchFilesTable.vue:107`、`FileListTable.vue:228`、`SftpBrowser.vue:93`）。
    本任务要求「签名一字不改」，不是「改成同步」；改成同步才是行为变更。
  - 取不到设置时的回退值与今天逐个模块的初值一致（renderer 回 `'svg'` 等），且**失败后不再重试**——
    今天 `echarts-theme.ts:44-51` 的注释写死了这个口径，丢了它就会退化成每次导航都重试的请求风暴。

- [ ] **Step 1: store 的单测（T2，mock 掉 api 模块）**

承重设计：断言「N 个并发 `ensure()` 只发 1 次 GET」「reset 后确实重发」「GET 失败后**不**再重试」
「save 只 PUT 脏字段」——四条都是今天日志的反面或今天的既有语义，缺任何一条都算不承重。

```typescript
// frontend/test/unit/userSettings.spec.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const getSettings = vi.fn()
const updateSettings = vi.fn()
vi.mock('../../src/api/auth', () => ({
  authApi: {
    getSettings: (...a: any[]) => getSettings(...a),
    updateSettings: (...a: any[]) => updateSettings(...a),
  },
}))

import { useUserSettingsStore } from '../../src/stores/userSettings'

describe('userSettings store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    getSettings.mockReset()
    updateSettings.mockReset()
  })

  it('并发 ensure 只发一次 GET（单飞）', async () => {
    getSettings.mockResolvedValue({ data: { page_size: 100 } })
    const s = useUserSettingsStore()
    await Promise.all([s.ensure(), s.ensure(), s.ensure()])
    expect(getSettings).toHaveBeenCalledTimes(1)
  })

  it('已取过后再次 ensure 不再发请求', async () => {
    getSettings.mockResolvedValue({ data: { page_size: 100 } })
    const s = useUserSettingsStore()
    await s.ensure()
    await s.ensure()
    expect(getSettings).toHaveBeenCalledTimes(1)
  })

  it('GET 失败后 ensure 不再重试（对照组：防请求风暴回归）', async () => {
    getSettings.mockRejectedValue(new Error('boom'))
    const s = useUserSettingsStore()
    await s.ensure()
    await s.ensure()
    expect(getSettings).toHaveBeenCalledTimes(1)
    expect(s.raw).toBeNull()
  })

  it('reset 后 ensure 会重新发一次（登录/登出串账号防线）', async () => {
    getSettings.mockResolvedValue({ data: { page_size: 100 } })
    const s = useUserSettingsStore()
    await s.ensure()
    s.reset()
    await s.ensure()
    expect(getSettings).toHaveBeenCalledTimes(2)
  })

  it('save 只 PUT 脏字段，不发全量', async () => {
    getSettings.mockResolvedValue({ data: { page_size: 100, chart_renderer: 'canvas' } })
    updateSettings.mockResolvedValue({ data: { page_size: 200, chart_renderer: 'canvas' } })
    const s = useUserSettingsStore()
    await s.ensure()
    await s.save({ page_size: 200 })
    expect(updateSettings).toHaveBeenCalledTimes(1)
    expect(updateSettings.mock.calls[0][0]).toEqual({ page_size: 200 })
  })
})
```

- [ ] **Step 2: 跑到失败**

Run: `cd frontend && npx vitest run test/unit/userSettings.spec.ts`
Expected: FAIL — 模块不存在

- [ ] **Step 3: 写 store**

```typescript
// frontend/src/stores/userSettings.ts
import { defineStore } from 'pinia'
import { ref, type Ref } from 'vue'
import { authApi } from '../api/auth'

export interface UserSettings {
  page_size?: number
  chart_renderer?: string
  export_timeout?: number
  sftp_download_timeout?: number
  filename_wrap?: boolean
  analysis_chart_memory?: boolean
  default_hidden_columns?: string[]
  [k: string]: unknown
}

/**
 * /auth/settings/ 的唯一持有者。
 *
 * 今天这份设置被 6 个互不相干的模块各自单飞（echarts-theme / exportTimeout /
 * filenameWrap / sftpTimeout / useChartMemory / DataBrowserAgGrid），一次导航实测 2–6 次 GET
 * （生产日志 2026-10-22 06:47:47 三条 auth/settings）。
 */
export const useUserSettingsStore = defineStore('userSettings', () => {
  const raw = ref<UserSettings | null>(null)
  let settled = false
  let inflight: Promise<void> | null = null

  /** 幂等：取过就不再取；失败也算取过（与 echarts-theme.ts:44-51 的降级口径一致，防请求风暴）。 */
  function ensure(): Promise<void> {
    if (inflight) return inflight
    if (settled) return Promise.resolve()
    inflight = authApi
      .getSettings()
      .then(({ data }) => {
        raw.value = (data ?? null) as UserSettings | null
      })
      .catch(() => {
        raw.value = null
      })
      .finally(() => {
        inflight = null
        settled = true
      })
    return inflight
  }

  /** 本地即时生效，不等 PUT 往返。同时记为已取过（等同今天 setChartRenderer 的 _rendererFetched=true）。 */
  function patch(p: Partial<UserSettings>) {
    raw.value = { ...(raw.value ?? {}), ...p }
    settled = true
  }

  /** 只 PUT 调用方给的键（后端 serializer 是 partial=True，增量合法）。 */
  async function save(p: Partial<UserSettings>): Promise<void> {
    const { data } = await authApi.updateSettings(p as Record<string, unknown>)
    raw.value = (data ?? null) as UserSettings | null
  }

  /** 卸载期冲刷专用（pagehide），沿用 auth.ts:174-191 的 keepalive 通道。 */
  function saveKeepalive(p: Partial<UserSettings>): void {
    patch(p)
    authApi.updateSettingsKeepalive(p as Record<string, unknown>)
  }

  /** 登录/登出调用，防跨账号串值。 */
  function reset(): void {
    raw.value = null
    settled = false
    inflight = null
  }

  return { raw, ensure, patch, save, saveKeepalive, reset } as {
    raw: Ref<UserSettings | null>
    ensure: () => Promise<void>
    patch: (p: Partial<UserSettings>) => void
    save: (p: Partial<UserSettings>) => Promise<void>
    saveKeepalive: (p: Partial<UserSettings>) => void
    reset: () => void
  }
})
```

给 Step 1 的 spec 再补一条（patch 的「已取过」语义是新引入的）：

```typescript
  it('patch 后 ensure 不再发请求（等同旧 setChartRenderer 标记已取过）', async () => {
    const s = useUserSettingsStore()
    s.patch({ page_size: 200 })
    await s.ensure()
    expect(getSettings).toHaveBeenCalledTimes(0)
  })
```

- [ ] **Step 4: 四个 scalar util 改为读 store（对外签名一字不改）**

以 `echarts-theme.ts` 为模板。现状是模块级 `_chartRenderer` + `_rendererFetched` + `_rendererPromise`
三个变量（`:17-19`）与 `ensureChartRenderer`（`:53-67`）；改后：

```typescript
import { useUserSettingsStore } from '../stores/userSettings'

/** 路由守卫 await 这个预热；签名保持 Promise<void> 不变（router/index.ts:178 依赖它）。 */
export function ensureChartRenderer(): Promise<void> {
  return useUserSettingsStore().ensure()
}

/** 同步 getter 必须继续存在：echarts-init.ts 的 tryInit 里没法 await。 */
export function getChartRenderer(): 'svg' | 'canvas' {
  return useUserSettingsStore().raw?.chart_renderer === 'canvas' ? 'canvas' : 'svg'
}

export function setChartRenderer(renderer: 'svg' | 'canvas'): void {
  useUserSettingsStore().patch({ chart_renderer: clampChartRenderer(renderer) })
}
```

`_chartRenderer` / `_rendererFetched` / `_rendererPromise` 与 `resetChartRendererCache` **一并删除**
（不留兼容壳，照 `.claude/CLAUDE.md`「避免向后兼容残渣」）。`clampChartRenderer` 保留——它是
「非 'canvas' 一律回退 'svg'」的唯一口径，`getChartRenderer()` 现在也走它。
其余三个模块同构（`exportTimeout` → `export_timeout`、`sftpTimeout` → `sftp_download_timeout`、
`filenameWrap` → `filename_wrap`），逐个改，不要写循环脚本批量替换。

`stores/auth.ts`：删掉 `:4-9` 里 5 个 `resetXxxCache` 的 import 与 `:23-27`、`:77-81` 的调用，
换成一次 `useUserSettingsStore().reset()`。

- [ ] **Step 5: `useChartMemory.ts`、网格、设置页走 store**

- `useChartMemory.ts`：只把 `:60-94` 里那次 `getSettings()` 换成 `store.ensure()` + 读 `store.raw`；
  它自己的 debounce 定时器（`:96-109`）、`pagehide` keepalive 冲刷（`:155-166`）、
  `analysis_chart_state` 的读写**都留在原处**——那些与「缓存账号设置」无关，混进 store 会把两种生命周期搅一起。
  冲刷改调 `store.saveKeepalive({ analysis_chart_memory: v })`。
- `DataBrowserAgGrid.vue:259-270`：`onMounted` 里那次裸 `authApi.getSettings()` 改成
  `const s = useUserSettingsStore(); await s.ensure(); if (!gridAlive) return` 后读
  `s.raw?.default_hidden_columns` / `s.raw?.page_size`（与 Task 4 的 `gridAlive` 守卫同一处）。
- `SettingsPage.vue:120-138`：现在是无脏追踪地整对象 PUT 全部 11 个键（今天生产实测 32 次 PUT）。
  改为 `onMounted` 载入后存一份 `loaded` 快照，`saveSettings` 只把 `!== loaded` 的键交给 `store.save()`；
  一个键都没变就**不发** PUT，并把保存按钮在该状态下置 disabled（语义变化要可见）。

- [ ] **Step 6: 跑到通过**

Run: `cd frontend && npx vitest run 2>&1 | tail -12`
Expected: 全绿。
再跑一次 e2e：`cd frontend && npm run test:e2e:affected`（`stores/` 命中 GLOBAL ⇒ 会排全量档，
日志末尾应有 `RESULT:`；`NO AFFECTED TESTS` 不算绿）。

⚠ **存量红会拦住这一档**：`e2e/settings/export-timeout.spec.ts` 是已知存量红，只要改动命中 settings
模块，快门禁就会因它报 FAIL（见项目记忆「E2E 存量红清单与回归定性」）。**别读成成本批改坏**——
按 `testing-gates` 的定性流程在父检出 master 上复跑同一 spec 对照，结论写进 todo；本轮不顺手修它。
预计还要一起维护的 spec：`settings/{page-size,chart-memory,export-timeout,sftp-timeout,hidden-columns,
cpk-thresholds,export-templates,settings}.spec.ts`（各自 seed 或断言 settings 读写）。

- [ ] **Step 7: 实测「一次导航只发一次 settings」**

在 Task 5 Step 1 那条 spec 里加同形计数：

```typescript
  const hits: string[] = []
  page.on('request', (r) => {
    if (/\/auth\/settings\//.test(r.url())) hits.push(r.url())
  })
  await gotoApp(page, '/data')
  await expect(page.locator('.el-table__row').first()).toBeVisible({ timeout: 30_000 })
  expect(hits.filter((h) => h.includes('/auth/settings/'))).toHaveLength(1)
```
Expected: 首屏 GET 恰 1 次（今天生产实测 2–6 次）。多出来的一定是某个仍在自取的模块，顺着请求 initiator
找它，别把断言改成 `toBeLessThanOrEqual(6)`。

- [ ] **Step 8: 提交**

```bash
git add frontend/src/stores/userSettings.ts frontend/test/unit/userSettings.spec.ts frontend/src/utils/ frontend/src/composables/useChartMemory.ts frontend/src/pages/data/DataBrowserAgGrid.vue frontend/src/pages/settings/SettingsPage.vue frontend/src/stores/auth.ts
git commit -m "refactor(frontend): /auth/settings/ 收敛为单一 store，导航期不再 2–6 次自取"
```

---

### Task 7: 收口对照与文档回填

**Files:**
- Modify: `docs/reference/renderer-memory-baseline-2026-10-22.md`（追加整改后复跑表）
- Modify: `docs/tasks/todo.md`（本批结论与遗留）
- Modify: `docs/tasks/lessons.md`（追加当日条目）

- [ ] **Step 1: 探针复跑（整改后）**

Run: `LQDP_PERF_PROBE=1 node scripts/e2e_pool.mjs --slots=1 -- data/renderer-memory.spec.ts`
Expected: PASS；把三行数字与 Task 2 的「整改前」并排写进 baseline 文档，**两栏都标 cap 生效后的实际块数**
（cap 变了，`reqs.length` 也会变，不标注就等于换了两个变量还叫「对照」）。

- [ ] **Step 2: 全量池 + 后端全套**

Run: `node scripts/e2e_pool.mjs --slots=4`
Expected: 日志末尾 `RESULT: PASS`（判据取 `RESULT:` 行，不取 `$?`）。存量红按
`docs/reference/testing-gates.md` 的定性流程走父检出 master 对照，别当场归因给本批。

- [ ] **Step 3: 回填与教训**

`docs/tasks/todo.md` 追加一节：实测表、四个常数、哪些 e2e 因 GLOBAL 档重排、遗留（B/C/D 三项仍未做，
以及「切走的标签切回来要重新取数」这一体验代价）。`docs/tasks/lessons.md` 只记**教训形状**，
不抄数字：本轮值得写的是「同一 URL 同一体积在空闲/挂载后差 200 倍 ⇒ 归因前先拆后端段与渲染段」
与「AG Grid 的 maxBlocksInCache 是 cache 创建时的快照，改 prop 不重建 cache 就不生效」。

- [ ] **Step 4: 提交**

```bash
git add docs/reference/renderer-memory-baseline-2026-10-22.md docs/tasks/todo.md docs/tasks/lessons.md
git commit -m "docs(memory): 渲染进程块预算整改实测对照与两条判据教训"
```

---

## 遗留（本轮刻意不做，别顺手改）

- **B 后端载荷**：`/browse/` 每页重发 `headers`+`col_meta`（`apps/datafiles/views/browse_views.py:237,246`）、
  `/summary/` 命中缓存仍 `clean_data` + 重序列化（`apps/dashboard/views.py:65`）。
- **C 内存治理三批**：`docs/superpowers/specs/2026-10-21-backend-memory-governance-design.md` +
  同名计划未实施；今天那条「可用提交内存 7.4GB 低于预算 8.0GB」正是它要接的场景。
- **D 日志卫生**：`electron/backend.ts:70` 把 backend-stderr 一律记 ERROR（今天 3057 条假 ERROR）、
  内存护栏中文 GBK 乱码、日志无轮转。
- 生产机页面文件仍偏小（历史实测只分配 4.97 GB）——这是机器配置，不是代码能修的，需运维处理。
