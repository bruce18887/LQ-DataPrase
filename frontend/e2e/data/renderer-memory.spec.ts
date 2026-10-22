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

/** 被测文件由环境变量选，Task 2 要跑「千列」与「窄」两种形状，不改代码只换 env。 */
const PROBE_KEY = process.env.LQDP_PROBE_FILE ?? 'ETS88_FT'
/** `SEEDED_FILES` 的值**就是**文件名（`fixtures/test-data.ts:50-68`），不是 `{ filename }` 对象 */
const PROBE_FILE = SEEDED_FILES[PROBE_KEY] as string
if (!PROBE_FILE) throw new Error(`SEEDED_FILES 里没有 ${PROBE_KEY}`)

/**
 * 标签 2..4 的文件键。同一个 fileId 开不出两个标签（`DataManagement.vue` 的 `viewFile`
 * 按 fileId 去重：命中已有标签就只是切过去），所以「4 个标签同时在内存」这个形状
 * 必须由 4 个**不同**文件表达；第 1 个标签恒为被测文件。
 */
const TAB_KEYS = (process.env.LQDP_PROBE_TABS ?? 'CTA8290D_FT,BUYOFF_FT,CTA8280F_FT')
  .split(',')
  .map((k) => k.trim())
  .filter((k) => k && k !== PROBE_KEY)
for (const k of TAB_KEYS) {
  if (!SEEDED_FILES[k]) throw new Error(`SEEDED_FILES 里没有标签文件 ${k}`)
}
if (TAB_KEYS.length !== 3) {
  throw new Error(`第 3 个形状必须是 4 个标签（被测文件 + 3 个标签文件），当前 ${1 + TAB_KEYS.length} 个`)
}

/**
 * 每块行数 = 账号设置「默认每页行数」（`DataBrowserAgGrid.vue:223-229` applyBlockSize 读它）。
 * 探针必须自己钉住它，否则「20 块」这个形状根本不存在：ETS88 全文件 1,436 行 ÷ 出厂默认 100
 * = 15 块，连 maxBlocksInCache=20 都填不满，那组数字量的是 15 块。取设置域下限 50
 * （`apps/common/constants.py:14` PAGE_SIZE_MIN）→ 29 块，够翻 20 块满缓存。
 */
const PROBE_PAGE_SIZE = Number(process.env.LQDP_PROBE_PAGE_SIZE ?? 50)
/**
 * 必须翻满的块数 = `maxBlocksInCache`（DataBrowserAgGrid.vue:69 现在写死 20）。
 * 留 env 口：Task 4 把 cap 换成按格数预算算出来之后，同一个形状要用新的 cap 重量一次，
 * 不该为此改代码（也不该让「20 块满缓存」这个标签在 cap 变了之后继续骗人）。
 */
const BLOCKS = Number(process.env.LQDP_PROBE_BLOCKS ?? 20)
/** 行高 30px（同文件 `:rowHeight="30"`），滚动步长按它换算 */
const ROW_HEIGHT = 30

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
 * 承重判据是末尾那条 `requests.length >= BLOCKS`：形状没堆出来就必须红。
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

/** 产物落盘：中途炸了也要把已经量到的数字留下来 —— 探针的产物比结论先有用。 */
function dump(rows: MetricRow[]): string {
  mkdirSync(OUT_DIR, { recursive: true })
  const outFile = path.join(OUT_DIR, `renderer-probe-${PROBE_KEY}.json`)
  writeFileSync(outFile, JSON.stringify(rows, null, 2))
  return outFile
}

test(`@p2 [${PROBE_KEY}] 1 块 / 满缓存 / 4 标签的堆与 long task`, async ({ page }) => {
  // 千列文件翻 20 块再开 4 个标签，单条就是要几分钟；config 里的 60s 是给业务用例定的。
  test.setTimeout(600_000)

  const m = await startRendererMetrics(page)
  const rows: MetricRow[] = []
  let originalPageSize: number | null = null
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
    rows.push(await m.snapshot(`${1 + TAB_KEYS.length} 个标签（各 1 块）`))
  } finally {
    await m.stop()
    outFile = dump(rows)
    if (originalPageSize !== null) {
      await putPageSize(page, originalPageSize).catch(() => undefined)
    }
  }

  // 承重前置①：块大小真的被钉住了（没接上时形状就不是「20 块」而是「15 块」）
  const firstBrowse = rows[0].requests.find((r) => /\/browse\//.test(r.url))
  expect(firstBrowse?.url, '首屏应有 /browse/ 响应且带上钉住的 page_size').toContain(
    `page_size=${PROBE_PAGE_SIZE}`,
  )
  // 承重前置②：真的取到了 20 块，否则后面所有数字都是「没翻页」的假绿
  expect(rows[1].requests.length).toBeGreaterThanOrEqual(BLOCKS)
  expect(rows[1].jsHeapUsedMiB).toBeGreaterThan(rows[0].jsHeapUsedMiB)

  console.log(
    `形状：${PROBE_FILE} 每块 ${PROBE_PAGE_SIZE} 行 × ${BLOCKS} 块，` +
      `标签 = ${[PROBE_KEY, ...TAB_KEYS].join(',')}，产物 ${outFile}`,
  )
  for (const r of rows) {
    console.log(`${r.label}: heap=${r.jsHeapUsedMiB}MiB longTask=${r.longTasksMsTotal}ms max=${r.longestTaskMs}ms reqs=${r.requests.length}`)
  }
})
