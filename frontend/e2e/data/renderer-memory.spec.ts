import { test, expect, type Page } from '@playwright/test'
import { writeFileSync, mkdirSync } from 'node:fs'
import path from 'node:path'
import { SEEDED_FILES, PROJECT_ROOT } from '../fixtures/test-data'
import { gotoApp } from '../helpers/nav'
import { openViewTab, openFileInViewTab } from '../helpers/viewTab'
import { startRendererMetrics, type MetricRow } from '../helpers/rendererMetrics'

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

/**
 * 下面这些 env 只**解析**、不**校验**：校验在测试体第一步（`validateProbeConfig`）。
 * 模块级 throw 会让整池在 collection 阶段炸成 `[pool] 结论 VOID (infra)`
 * —— 而本文件的约束是「门控没开就默认跳过、不花钱」。Task 2 要反复换这几个 env，
 * 拼错应当红在这**一条**用例上并写清哪个 env 不对，不该把 76 个文件的池拖成一条收集错误。
 */

/** 被测文件由环境变量选，Task 2 要跑「千列」与「窄」两种形状，不改代码只换 env。 */
const PROBE_KEY = process.env.LQDP_PROBE_FILE ?? 'ETS88_FT'
/** `SEEDED_FILES` 的值**就是**文件名（`fixtures/test-data.ts:50-68`），不是 `{ filename }` 对象 */
const PROBE_FILE = SEEDED_FILES[PROBE_KEY] as string

/**
 * 标签 2..4 的文件键。同一个 fileId 开不出两个标签（`DataManagement.vue` 的 `viewFile`
 * 按 fileId 去重：命中已有标签就只是切过去），所以「4 个标签同时在内存」这个形状
 * 必须由 4 个**不同**文件表达；第 1 个标签恒为被测文件。
 */
const TAB_KEYS = (process.env.LQDP_PROBE_TABS ?? 'CTA8290D_FT,BUYOFF_FT,CTA8280F_FT')
  .split(',')
  .map((k) => k.trim())
  .filter((k) => k && k !== PROBE_KEY)

/**
 * 每块行数 = 账号设置「默认每页行数」（`DataBrowserAgGrid.vue:223-229` applyBlockSize 读它）。
 * 探针必须自己钉住它，否则「20 块」这个形状根本不存在：ETS88 全文件 1,436 行 ÷ 出厂默认 100
 * = 15 块，连 maxBlocksInCache=20 都填不满，那组数字量的是 15 块。取设置域下限 50
 * （`apps/common/constants.py:14` PAGE_SIZE_MIN）→ 29 块，够翻 20 块满缓存。
 */
const PROBE_PAGE_SIZE = Number(process.env.LQDP_PROBE_PAGE_SIZE ?? 50)
/**
 * 必须翻满的块数。**Task 4 之后 `maxBlocksInCache` 不再是常量 20**，而是
 * `blockCap.maxBlocksInCache(每块行数, 列数)`：ETS88（1,728 列）@50 行 = 16，
 * 窄文件（≤142 列）@100 行仍 = 20（验收锚点，见 baseline 文档 §6 那张表）。
 * 留 env 口：cap 变了要用新的块数重量同一个形状，不该为此改代码，也不该让
 * 「20 块满缓存」这个标签在 cap 之后继续骗人。注意 IRM 是**请求**每一块、只**驱逐**超额的块，
 * 所以翻 20 块仍能拿到 20 个不同页（下面的承重判据不受 cap 影响），但驻留量已经是 cap 那份。
 */
const BLOCKS = Number(process.env.LQDP_PROBE_BLOCKS ?? 20)
/** 行高 30px（同文件 `:rowHeight="30"`），滚动步长按它换算 */
const ROW_HEIGHT = 30
/**
 * 读不到原值时的回落值 = `apps/accounts/models.py:62` `page_size` 的 default，
 * 与 `e2e/settings/page-size.spec.ts:89,106` 的 `original ?? 100` 同源（lessons 2026-09-19）。
 */
const PAGE_SIZE_FALLBACK = 100

/** 门控开着才校验配置；返回「哪一条不成立」的文案列表，空数组 = 配置可用。 */
function validateProbeConfig(): string[] {
  const errors: string[] = []
  if (!PROBE_FILE) errors.push(`LQDP_PROBE_FILE=${PROBE_KEY} 不在 SEEDED_FILES 里`)
  if (!Number.isInteger(PROBE_PAGE_SIZE) || PROBE_PAGE_SIZE < 50 || PROBE_PAGE_SIZE > 500) {
    errors.push(
      `LQDP_PROBE_PAGE_SIZE=${process.env.LQDP_PROBE_PAGE_SIZE ?? ''} 必须是 50..500 的整数（DataBrowserAgGrid.vue:273-274 BLOCK_SIZE_MIN/MAX）`,
    )
  }
  if (!Number.isInteger(BLOCKS) || BLOCKS < 1) {
    errors.push(`LQDP_PROBE_BLOCKS=${process.env.LQDP_PROBE_BLOCKS ?? ''} 必须是 ≥1 的整数`)
  }
  for (const k of TAB_KEYS) {
    if (!SEEDED_FILES[k]) errors.push(`LQDP_PROBE_TABS 里的标签文件 ${k} 不在 SEEDED_FILES 里`)
  }
  if (TAB_KEYS.length !== 3) {
    errors.push(`第 3 个形状必须是 4 个标签（被测文件 + 3 个标签文件），当前 ${1 + TAB_KEYS.length} 个`)
  }
  return errors
}

async function readPageSize(page: Page): Promise<number | null> {
  return page.evaluate(async () => {
    const resp = await fetch('/api/v1/auth/settings/', {
      headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` },
    })
    const data = await resp.json()
    return typeof data?.page_size === 'number' ? data.page_size : null
  })
}

async function putPageSize(page: Page, value: number) {
  const status = await page.evaluate(async (v) => {
    const resp = await fetch('/api/v1/auth/settings/', {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('access_token')}`,
      },
      body: JSON.stringify({ page_size: v }),
    })
    return resp.status
  }, value)
  expect(status, `PUT page_size=${value}`).toBe(200)
}

/**
 * 钉住块大小并返回原值供收尾写回。admin 是共享账号，收尾必须写回**原值**而不是硬编码
 * 默认（同 `e2e/settings/page-size.spec.ts`，教训见 lessons 2026-09-19）。
 * 先 gotoApp 到别处再 PUT：设置必须在「查看数据」整页导航**之前**落库，
 * 网格是 onMounted 才读它的。
 */
async function pinPageSize(page: Page, value: number): Promise<number | null> {
  await gotoApp(page, '/dashboard')
  const original = await readPageSize(page)
  await putPageSize(page, value)
  return original
}

/**
 * 收尾写回（给 `finally` 用）：不带 expect、**不抛**。
 *
 * 它跑在 finally 里，抛出会把 try 里真正的失败原因盖掉（超时场景尤其糟：Playwright 拆页面
 * 时 evaluate 必然抛，那一刻的「原始失败」才是线索）。但失败也绝不能再被
 * `.catch(() => undefined)` 咽掉 —— 所以把 PUT 状态码与写回后的读回值一路带回测试体，
 * 由末尾那条 `page_size 必须写回` 的断言判红。值以读回为准：PUT 返回 200 也不等于落库。
 */
async function restorePageSize(
  page: Page,
  value: number,
): Promise<{ putStatus: number | null; restored: number | null }> {
  let putStatus: number | null = null
  try {
    putStatus = await page.evaluate(async (v) => {
      const resp = await fetch('/api/v1/auth/settings/', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('access_token')}`,
        },
        body: JSON.stringify({ page_size: v }),
      })
      return resp.status
    }, value)
  } catch {
    putStatus = null // 页面已被拆掉 / 网络断：交给末尾断言判红，这里不抛
  }
  let restored: number | null = null
  try {
    restored = await readPageSize(page)
  } catch {
    restored = null
  }
  return { putStatus, restored }
}

/** `requests[].url` 是砍掉 `/api/v1` 前缀后的相对路径，靠 base 补成可解析的绝对 URL。 */
function urlParam(url: string, name: string): number | null {
  try {
    const raw = new URL(url, 'http://probe.invalid').searchParams.get(name)
    if (raw === null) return null
    const n = Number(raw)
    return Number.isInteger(n) ? n : null
  } catch {
    return null
  }
}

/**
 * 分母（§5 Q4 的「每块单元格数」）从后端权威取，不靠 DOM 数格子：
 * 默认隐藏列（`default_hidden_columns` → `colDef.hide`）不渲染表头，而行数据是
 * `zipBrowserRows` 按 `/browse/` 的 `headers` **全量**拼的 —— 内存里每块的格数
 * = `headers.length × 块行数`，与看得见的表头数无关。
 */
async function probeDenominator(
  page: Page,
  datafileId: number,
  pageSize: number,
): Promise<{ colCount: number | null; totalRows: number | null }> {
  return page.evaluate(async ({ id, ps }) => {
    const qs = new URLSearchParams({
      datafile_id: String(id),
      page: '1',
      page_size: String(ps),
      sort_model: '[]',
      filter_model: '{}',
    })
    const resp = await fetch(`/api/v1/browse/?${qs}`, {
      headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` },
    })
    if (!resp.ok) return { colCount: null, totalRows: null }
    const d = await resp.json()
    return {
      colCount: Array.isArray(d?.headers) ? d.headers.length : null,
      totalRows: typeof d?.total === 'number' ? d.total : null,
    }
  }, { id: datafileId, ps: pageSize })
}

/**
 * 逐块向下翻 n 次，逼 IRM 一块一块向服务端取数。
 *
 * 两处都是实测事实、不是风格选择：
 * ① 垂直滚动必须驱动 `.ag-body-vertical-scroll-viewport`：赋 scrollTop 能触发 IRM 续块请求，
 *   赋给 `.ag-center-cols-viewport` 触发不了（`e2e/settings/page-size.spec.ts:79-82` 记过这条，
 *   view-data 的 ensureRowRendered 用的也是前者）。
 * ② 必须**按块位递进**，不能「滚到底」。IRM 从首块响应的 rowCount 就知道整表高度，
 *   滚到底等于一步跳到末块，之后的「滚到底」不再产生任何请求 → 每步撞超时，
 *   看起来像「滚动没触发取数」，实际是驱动方式把 20 块压成了 1 块。
 *
 * 单步等不到新响应不在此处判红（预取会让某一步落进已缓存的块），
 * 承重判据是末尾那条按 page 参数去重的 `distinctPages >= BLOCKS`：形状没堆出来就必须红。
 */
async function scrollBlocks(page: Page, n: number, rowsPerBlock: number) {
  const vp = page.locator('.ag-body-vertical-scroll-viewport').first()
  for (let i = 1; i <= n; i++) {
    const done = page
      .waitForResponse((r) => /\/browse\//.test(r.url()), { timeout: 30_000 })
      .then(() => true)
      .catch(() => false)
    await vp.evaluate((el, top) => {
      ;(el as HTMLElement).scrollTop = top
    }, i * rowsPerBlock * ROW_HEIGHT)
    await done
  }
}

/** 产物的 shape 段：数字必须与产生它的那组配置一起走，否则读数的人只能猜分母。 */
interface ProbeShape {
  probeKey: string
  rowsPerBlock: number
  blocks: number
  colCount: number | null
  totalRows: number | null
  cellsPerBlock: number | null
  tabs: string[]
}

/**
 * 产物落盘：中途炸了也要把已经量到的数字留下来 —— 探针的产物比结论先有用。
 *
 * `{ shape, rows }` 而不是裸 `rows`：设计稿 §5 Q4 是 `Q1 / 每块单元格数`，
 * 而每块行数 / 列数 / 块数 / 标签只写在 console.log（=另一个文件、另一个生命周期）里的话，
 * 下游唯一能自带分母的地方就是这份 JSON。已知事故形态是分母误读 7 倍。
 */
function dump(rows: MetricRow[], shape: ProbeShape): string {
  mkdirSync(OUT_DIR, { recursive: true })
  const outFile = path.join(OUT_DIR, `renderer-probe-${PROBE_KEY}.json`)
  writeFileSync(outFile, JSON.stringify({ shape, rows }, null, 2))
  return outFile
}

test(`@p2 [${PROBE_KEY}] 1 块 / 满缓存 / 4 标签的堆与 long task`, async ({ page }) => {
  // 千列文件翻 20 块再开 4 个标签，单条就是要几分钟；config 里的 60s 是给业务用例定的。
  test.setTimeout(600_000)

  // 配置不成立就立刻红在这一条上（门控关着时整条用例是 skip，永远走不到这里）。
  const configErrors = validateProbeConfig()
  if (configErrors.length) {
    throw new Error(`探针配置不成立：\n  - ${configErrors.join('\n  - ')}`)
  }

  const shape: ProbeShape = {
    probeKey: PROBE_KEY,
    rowsPerBlock: PROBE_PAGE_SIZE,
    blocks: BLOCKS,
    colCount: null,
    totalRows: null,
    cellsPerBlock: null,
    tabs: [PROBE_KEY, ...TAB_KEYS],
  }

  const m = await startRendererMetrics(page)
  const rows: MetricRow[] = []
  /**
   * Task 4 的生命周期守卫：`gridApi` 由 onGridReady 赋值后从不置空，卸载后的异步续体
   * （账号设置那条 GET）就会打在已销毁的 grid 上（生产实测两条 `AG Grid: warning #26`）。
   * 探针正好在制造这个形状：开 4 个标签 + 切走切回，非激活那份要 purge 缓存。
   * 监听装在动作之前（lessons R2④）。
   */
  const destroyedWarnings: string[] = []
  page.on('console', (msg) => {
    if (msg.type() === 'warning' && /#26|has been destroyed/.test(msg.text())) {
      destroyedWarnings.push(msg.text())
    }
  })
  let originalPageSize: number | null = null
  let restore: { putStatus: number | null; restored: number | null } = { putStatus: null, restored: null }
  let outFile = ''
  try {
    originalPageSize = await pinPageSize(page, PROBE_PAGE_SIZE)

    await openViewTab(page, PROBE_FILE)
    // 首块真的渲染出来才取样：探针里「导航后补等一个 browse 响应」有漏窗（首块可能在
    // openViewTab 返回前就到了），等第一行才与「首屏」同义（lessons R2④）。
    await expect(page.locator('.ag-row').first()).toBeVisible({ timeout: 30_000 })
    rows.push(await m.snapshot('1 块（首屏）'))

    await scrollBlocks(page, BLOCKS - 1, PROBE_PAGE_SIZE)
    rows.push(await m.snapshot(`${BLOCKS} 块满缓存（1 个标签）`))

    for (const key of TAB_KEYS) {
      await page.locator('.vf-tab--add').first().click()
      // 监听装在动作之前：新标签那份网格是点「查看」后才挂载取数的
      const loaded = page.waitForResponse((r) => /\/browse\//.test(r.url()), { timeout: 60_000 })
      await openFileInViewTab(page, SEEDED_FILES[key])
      await loaded
    }
    await expect(page.locator('.vf-tab:not(.vf-tab--add)')).toHaveCount(1 + TAB_KEYS.length)
    // 标签名里的「各 1 块」在 Task 4 之后不成立了：非激活那份会被交掉缓存 ⇒ 只有激活那份有块
    rows.push(await m.snapshot(`${1 + TAB_KEYS.length} 个标签（仅激活那份留缓存）`))

    // 切走再切回：非激活那份交缓存、切回来 IRM 按视口重新取块，全程不许出现 #26。
    // 选择器必须限定在**可见的那份**网格里（lessons R2②：4 个标签常驻 DOM，
    // 裸 `.ag-row` 的 first() 会解到隐藏标签那份的行 ⇒ 永远 not visible，实测假红一次）。
    const chips = page.locator('.vf-tab:not(.vf-tab--add)')
    const visibleRows = page.locator('.ag-grid-wrapper:visible .ag-row')
    await chips.first().click()
    await expect(visibleRows.first()).toBeVisible({ timeout: 30_000 })
    await chips.last().click()
    await expect(visibleRows.first()).toBeVisible({ timeout: 30_000 })

    // 分母放在三次 snapshot 之后取：这一次额外的 /browse/ 请求不会污染任何一行产物。
    const datafileId = rows[0].requests
      .filter((r) => /\/browse\//.test(r.url))
      .map((r) => urlParam(r.url, 'datafile_id'))
      .find((v) => v !== null)
    if (datafileId !== null && datafileId !== undefined) {
      const denom = await probeDenominator(page, datafileId, PROBE_PAGE_SIZE).catch(() => null)
      if (denom) {
        shape.colCount = denom.colCount
        shape.totalRows = denom.totalRows
        shape.cellsPerBlock =
          denom.colCount === null ? null : denom.colCount * PROBE_PAGE_SIZE
      }
    }
  } finally {
    await m.stop()
    outFile = dump(rows, shape)
    // **无条件**写回。`if (originalPageSize !== null)` 那种写法是反的：PUT 在 try 里已经成功，
    // 读原值失败（响应形状变了 / token 过期）并不等于「没改过设置」，跳过写回就是把 50 漏进库。
    // 代价不对称：池模式自愈（slot 库是本 RUN_ID 从模板拷的，`scripts/e2e_pool.mjs:108`，
    // 判 MEASURED 后整目录 rmSync，:484），但**直跑** —— 也就是本文件头部那条
    // `npx playwright test --project=P2 …` —— migrate/seed 到持久的
    // `test/e2e-data/db.sqlite3`（`frontend/e2e/global-setup.ts:44`），漏一个 50 会改变之后
    // 每次直跑量的块大小，探针的前提就没了。读不到原值时回落出厂默认（`page-size.spec.ts:89,106`）。
    const target = originalPageSize ?? PAGE_SIZE_FALLBACK
    restore = await restorePageSize(page, target)
    console.log(
      `[probe] page_size 写回：目标 ${target}（读到的原值 ${originalPageSize}）` +
        ` PUT=${restore.putStatus} 写回后读回 ${restore.restored}`,
    )
  }

  // 收尾卫生：写回必须**落库**（读回为准，PUT 200 不算）。放在 try/finally 之后，
  // 所以它既不会被 finally 的抛出盖掉，也不会被咽掉。
  const expectedPageSize = originalPageSize ?? PAGE_SIZE_FALLBACK
  expect(
    restore.restored,
    `收尾必须把 page_size 写回 ${expectedPageSize}（PUT=${restore.putStatus}，读回=${restore.restored}）`,
  ).toBe(expectedPageSize)

  // 生命周期：开 4 个标签 + 切走切回之后，不许有打在已销毁 grid 上的调用（AG Grid #26）
  expect(
    destroyedWarnings,
    `已销毁 grid 仍被调用（#26）：\n${destroyedWarnings.join('\n')}`,
  ).toEqual([])

  // 承重前置①：块大小真的被钉住了（没接上时形状就不是「20 块」而是「15 块」）
  const firstBrowse = rows[0].requests.find((r) => /\/browse\//.test(r.url))
  expect(firstBrowse?.url, '首屏应有 /browse/ 响应且带上钉住的 page_size').toContain(
    `page_size=${PROBE_PAGE_SIZE}`,
  )

  // 承重前置②（整条下游阈值链只认这一条）：形状 2 必须真的翻出 BLOCKS 个**不同页**。
  // 数请求条数不够格：`requests` 已被 /(browse|summary)/ 过滤（`rendererMetrics.ts:21`），
  // 形状 1 就自带 1 browse + 1 summary，所以 `length >= 20` 用 19 块也能绿；而且条数还会计上
  // 重复页 —— `applyBlockSize` + `purgeInfiniteCache`（`DataBrowserAgGrid.vue:282-287`）之后
  // 预取重取同一块是可能发生的。按 page 参数去重才是「翻了 BLOCKS 块」。
  // 这一行产物里只挂了被测文件一个网格（标签是之后才开的，实测 shape2 的
  // datafile_id 只有一个），所以 page 单独就是块身份；多文件那一行不做这个判据。
  const browsePages = rows[1].requests
    .filter((r) => /\/browse\//.test(r.url))
    .map((r) => urlParam(r.url, 'page'))
    .filter((v): v is number => v !== null)
  const distinctPages = new Set(browsePages).size
  expect(
    distinctPages,
    `形状 2 必须翻满 ${BLOCKS} 个不同页（browse 请求 ${browsePages.length} 条，去重后 ${distinctPages} 页）`,
  ).toBeGreaterThanOrEqual(BLOCKS)

  expect(rows[1].jsHeapUsedMiB).toBeGreaterThan(rows[0].jsHeapUsedMiB)

  // 承重前置③：分母必须是从后端取到的实数，且装得下这个形状
  expect(shape.colCount, '/browse/ 的 headers 长度（每块列数）必须取到').not.toBeNull()
  expect(shape.totalRows, '文件总行数必须取到').not.toBeNull()
  expect(
    shape.totalRows!,
    `文件只有 ${shape.totalRows} 行，装不下 ${BLOCKS} 块 × ${PROBE_PAGE_SIZE} 行 —— 这个形状不存在`,
  ).toBeGreaterThanOrEqual(BLOCKS * PROBE_PAGE_SIZE)

  console.log(
    `形状：${PROBE_FILE} 每块 ${PROBE_PAGE_SIZE} 行 × ${BLOCKS} 块（去重后实翻 ${distinctPages} 页）` +
      `，${shape.colCount} 列 × ${PROBE_PAGE_SIZE} 行 = ${shape.cellsPerBlock} 格/块，` +
      `总行数 ${shape.totalRows}，标签 = ${shape.tabs.join(',')}，产物 ${outFile}`,
  )
  for (const r of rows) {
    console.log(
      `${r.label}: heap=${r.jsHeapUsedMiB}MiB longTask=${r.longTasksMsTotal}ms max=${r.longestTaskMs}ms` +
        ` tasks=${r.longTasks.length} reqs=${r.requests.length}`,
    )
  }
})
