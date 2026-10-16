import { test, expect, type Locator, type Page } from '@playwright/test'
import { startSftpServer, type SftpTestServer } from '../helpers/sftpServer'
import { gotoApp } from '../helpers/nav'
import {
  addTag, badge, connectAndOpenSearch, runSearch, waitSettled,
} from '../helpers/sftpSearchFlow'

/**
 * SFTP 搜索页的**版式承重**用例（2026-09-25 改版：条件表单从定宽单列改成响应式网格，
 * 结果表从写死 520px 改成跟随视口，条件卡可收起成一行摘要）。
 *
 * 为什么值得单独一个文件：这些断言读的是**像素与几何**，不是数据。它们与 `search.spec.ts`
 * 共用 `helpers/sftpSearchFlow`，但结论只在窗口尺寸变化时才会变 —— 混进功能套件会让那边
 * 每条用例都背重视口耦合。
 *
 * 前置分两档：**L4/L5 要真链路**（要跑一次搜索才知道摘要与表格长成什么样）；**L1/L2/L3/L6
 * 只读版式**，走 `openSearchForm` 的直接入口，一次连接都不用 —— 连接那条链路的成本（约
 * 15s/例）比它们要测的东西贵得多。
 *
 * 三条不显然的口径：
 * - **一页的预算是 796px**：基准视口 1440×900，`.content-area` 客户高实测 844（900 − 顶栏 56），
 *   再减它自己的上下 24px 内边距。改版前光条件卡就 821px —— 一进页就要滚 1.7 屏。
 * - **并排怎么判**：比较两个字段**整行**（`.el-form-item`）的 `boundingBox().y`。
 *   `label-position="left"` 下标签与控件同行，所以「同 y」=「同一行」；用 `offsetTop` 会被
 *   flex 居中的父级骗到（差几像素），量像素三条陷阱之一。
 * - **表格要证的是「会跟着窗口长」**：只测 900 高的话流体值(396)反而比写死的 520 小，看不出
 *   改了什么。所以关键断言是**增量**：视口从 900 升到 1200（+300），grid 必须至少 +200。
 *   写死 520px 时这条永远不成立，而它不依赖任何一方的绝对像素估计。
 *
 * 跑法同 `search.spec.ts`：`--project=P1 --workers=1`（不带 `--project` 会落进 Edge project
 * 的 `grepInvert` 被静默跳过 = 假绿）。所有读数都 `console.log`，红的时候先看到真实像素，
 * 再判是版式坏了还是断言写错。
 */
let server: SftpTestServer

/**
 * 版式用例的免连接入口：只量几何、不发搜索，因此不需要活的 SFTP 会话。
 *
 * 直接 `gotoApp('/sftp/search')` 拿到的是空表单（roots 平时由浏览器页的面包屑预填），
 * 所以要手工补一个与预填同文的 tag —— 少这一格占位条件卡就矮一截，而 L1/L6 的阈值离实测
 * 只差 1px，占位不齐就测不出同一份版式。做法同 `search.spec.ts` 的「未连接」那条用例。
 */
async function openSearchForm(page: Page, root = '/batch1') {
  await gotoApp(page, '/sftp/search')
  await expect(page.getByTestId('sftp-search-roots')).toBeVisible({ timeout: 15_000 })
  await addTag(page, 'sftp-search-roots', root)
  await expect(page.locator('.sc-tags .el-tag')).toHaveText([root])
}

async function heightOf(loc: Locator): Promise<number> {
  const box = await loc.boundingBox()
  if (!box) throw new Error('目标不可见，量不到高度')
  return Math.round(box.height)
}

async function topOf(loc: Locator): Promise<number> {
  const box = await loc.boundingBox()
  if (!box) throw new Error('目标不可见，量不到位置')
  return Math.round(box.y)
}

/** 表单里某个 testid 所属的那一行（el-form-item）—— 判并排要比整行，不比控件 */
function itemOf(page: Page, testId: string): Locator {
  return page.locator('.el-form-item').filter({ has: page.getByTestId(testId) })
}

async function sameRow(page: Page, a: string, b: string): Promise<boolean> {
  const [ya, yb] = [await topOf(itemOf(page, a)), await topOf(itemOf(page, b))]
  console.log(`[几何] ${a}.y=${ya} ${b}.y=${yb}`)
  return ya === yb
}

/** 整页还要滚多少：`.content-area` 才是滚动容器（`overflow-x:hidden`，所以溢出只能靠 scrollWidth 判） */
async function pageScroll(page: Page): Promise<number> {
  const [sh, ch] = await page.locator('.content-area')
    .evaluate((el) => [el.scrollHeight, el.clientHeight])
  return Math.round(sh - ch)
}

async function hOverflow(page: Page): Promise<number> {
  return page.locator('.content-area')
    .evaluate((el) => Math.round(el.scrollWidth - el.clientWidth))
}

test.describe.configure({ mode: 'serial', timeout: 240_000 })
test.use({ viewport: { width: 1440, height: 900 } })

test.describe('@sftp SFTP 搜索页版式', { tag: ['@p1', '@sftp'] }, () => {
  test.beforeAll(async () => {
    server = await startSftpServer({ fixture: true })
  })

  test.afterAll(() => { server?.stop() })

  test('L1 条件卡展开态不再吃掉一整屏', async ({ page }) => {
    await openSearchForm(page)
    const h = await heightOf(page.locator('.search-criteria'))
    console.log(`[L1] 条件卡展开=${h}px（改版前实测 821px；一页预算 796px）`)
    expect(h).toBeLessThanOrEqual(560)
    // 两套主题各留一张全页图（test-results/ 不入库）：版式改动光看像素断言不够，
    // chips 换行、栏间空隙这类只有看图才判得出来
    await page.screenshot({ path: 'test-results/sftp-search-layout-light.png', fullPage: true })
  })

  test('L2 短字段真的并排了：横向空间被用上', async ({ page }) => {
    await openSearchForm(page)
    // 切到内容档只为把「关键词」控件渲染出来（列名/关键词是 v-if 出来的）
    await page.getByTestId('sftp-search-mode').getByText('内容含').click()
    await page.getByTestId('sftp-search-term').fill('ShadowReg2')

    expect(await sameRow(page, 'sftp-search-pattern', 'sftp-search-time-from'),
      '名称模式与修改时间应同处一行').toBe(true)
    expect(await sameRow(page, 'sftp-search-mode', 'sftp-search-term'),
      '匹配模式与关键词应同处一行').toBe(true)

    // 跨整行的字段仍要独占地带：目录输入框得吃满它那一行
    const rootsW = (await page.getByTestId('sftp-search-roots').boundingBox())?.width ?? 0
    console.log(`[L2] 搜索目录输入框宽=${rootsW}px`)
    expect(rootsW).toBeGreaterThan(600)
  })

  test('L3 窄窗口回落单栏，且不出现横向溢出', async ({ page }) => {
    await openSearchForm(page)
    await page.setViewportSize({ width: 900, height: 900 })
    await expect(page.getByTestId('sftp-search-roots')).toBeVisible()

    expect(await sameRow(page, 'sftp-search-pattern', 'sftp-search-time-from'),
      '900 宽下应退回单栏（两者不同行）').toBe(false)
    const overflow = await hOverflow(page)
    console.log(`[L3] 900 宽横向溢出=${overflow}px`)
    expect(overflow, '条件区不得横向溢出被裁').toBeLessThanOrEqual(1)
  })

  test('L4 收起条件：压成一行摘要，摘要说清这次搜的是什么', async ({ page }) => {
    await connectAndOpenSearch(page, server, '/batch1')
    await runSearch(page, { mode: 'column', column: '*BV*2*', depth: 'self' })
    await waitSettled(page)

    const expanded = await heightOf(page.locator('.search-criteria'))
    await page.getByTestId('sftp-search-criteria-toggle').click()
    const collapsed = await heightOf(page.locator('.search-criteria'))
    console.log(`[L4] 条件卡 展开=${expanded}px 收起=${collapsed}px`)
    expect(collapsed).toBeLessThanOrEqual(72)

    const summary = page.getByTestId('sftp-search-criteria-summary')
    await expect(summary).toContainText('/batch1')
    await expect(summary).toContainText('*BV*2*')
    await expect(summary).toContainText('列名')
    // 收起走 v-show 而非卸载：条件值住在页面持有的 spec 上，但表单不销毁才不会引出
    // 「收起再展开后预填/草稿丢了」这类第三种真相
    await expect(page.locator('.sc-form')).toBeHidden()
    await expect(page.getByTestId('sftp-search-run')).toBeVisible()

    await page.getByTestId('sftp-search-criteria-toggle').click()
    expect(await heightOf(page.locator('.search-criteria'))).toBe(expanded)
    await page.getByTestId('sftp-search-criteria-toggle').click()
    await page.screenshot({ path: 'test-results/sftp-search-layout-collapsed.png', fullPage: true })
  })

  test('L5 结果表跟随视口增高，收起条件后整页不再滚动', async ({ page }) => {
    await connectAndOpenSearch(page, server, '/batch1')
    await runSearch(page, { mode: 'name', pattern: '*RT*', depth: 'self' })
    await waitSettled(page)
    expect((await badge(page)).rows).toBe(2)

    const grid = page.locator('.srt-grid')
    const expanded = await heightOf(grid)
    console.log(`[L5] 1440×900 条件展开 grid=${expanded}px 整页滚动=${await pageScroll(page)}px`)
    // 条件全展开时上方占位已经超出一屏，表格退到 `.srt` 的保底高度（约 10 行）+ 整页可滚，
    // 这是有意的取舍：不把条件表单压扁去换表格高度。保底值由样式声明，这里只兜住它。
    expect(expanded, '条件展开时表格仍要站住保底高度').toBeGreaterThanOrEqual(300)

    // **上面那条量的是宿主盒子，它挡不住 2026-10-16 那个真机故障**：AG Grid 的
    // `.ag-root-wrapper` 靠 `height: 100%` 撑开，而百分比高度要祖先有确定高度才解得出来。
    // 解不出来时 root-wrapper=0，它自带的 `overflow:hidden` 把表头和全部行一起裁光 ——
    // 宿主仍然有 446px（flex 给的），计数条仍然报「表格 7 行」（DOM 里 7 行真的在），
    // **且不报任何错**，界面只剩一个空框。所以必须往里量。
    // 实测判别力：用户真机窗口的坏态 root=0 / viewport=0，加包裹层后 root=445 / viewport=397。
    // ⚠ **但这个坏态在本仓 Playwright 里复现不出来** —— 同一份没有包裹层的旧代码，在
    // 1440×900 的 Edge 下 root 照样撑开、七行正常显示（2026-10-16 实测过两遍：dev 与生产包都绿）。
    // 所以这三条**拦不住用户那台机器上的原始故障**，只拦「在测试环境里也会塌」的同类退化。
    // 原故障的防线是组件里那条样式不变量：AG Grid 的宿主必须有确定高度。
    // 而行数与表头高度**没有**判别力（坏态下 `.ag-row` 照样存在、header 靠行内高度仍是 33），
    // 留行数那条只是为了钉住「画出来的 == 计数条报的」这个契约，别指望它拦塌框。
    const inner = await grid.evaluate((el) => ({
      root: el.querySelector<HTMLElement>('.ag-root-wrapper')?.clientHeight ?? -1,
      body: el.querySelector<HTMLElement>('.ag-body-viewport')?.clientHeight ?? -1,
      rows: el.querySelectorAll('.ag-center-cols-container .ag-row').length,
    }))
    console.log(`[L5] 内层 root=${inner.root} viewport=${inner.body} rows=${inner.rows}`)
    expect(inner.root, 'root-wrapper 塌成 0 = 百分比高度没解出来，整张表会被 overflow:hidden 裁光').toBeGreaterThan(0)
    expect(inner.body, 'body-viewport 塌成 0 = 一行都看不见，而宿主盒子仍是正常高度').toBeGreaterThan(0)
    expect(inner.rows, '渲染出的行数要等于计数条报的表格行数').toBe(2)

    await page.getByTestId('sftp-search-criteria-toggle').click()
    const collapsed = await heightOf(grid)
    const scrolled = await pageScroll(page)
    console.log(`[L5] 1440×900 条件收起 grid=${collapsed}px 整页滚动=${scrolled}px`)
    // 实测（1440×900）：收起条件后上方占位共 400px → grid 396px（13 行）且整页零滚动。
    // 阈值取 380：只兜住「flex 真的把剩余高度给了表格」这件事，不兜某个窗口的具体像素。
    expect(collapsed).toBeGreaterThanOrEqual(380)
    expect(scrolled, '900 高 + 收起条件应基本免整页滚动').toBeLessThanOrEqual(24)

    // 关键的一条：表格必须**跟着窗口长**。断言写成增量而不是绝对像素 —— 绝对值会随
    // 上方占位变化而失真，而「视口 +300 就得至少 +200」正是写死 520px 时永远不成立的性质。
    await page.setViewportSize({ width: 1440, height: 1200 })
    await expect.poll(() => heightOf(grid), { timeout: 10_000 }).toBeGreaterThanOrEqual(collapsed + 200)
    const at1200 = await heightOf(grid)
    console.log(`[L5] 1440×1200 grid=${at1200}px（视口 +300 → 表格 +${at1200 - collapsed}；改版前恒为 520px）`)
  })

  test('L6 深色主题下版式不变形', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('theme', 'night'))
    await openSearchForm(page)
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'night')

    const h = await heightOf(page.locator('.search-criteria'))
    console.log(`[L6] night 条件卡=${h}px 横向溢出=${await hOverflow(page)}px`)
    expect(h).toBeLessThanOrEqual(560)
    expect(await hOverflow(page)).toBeLessThanOrEqual(1)
    await page.screenshot({ path: 'test-results/sftp-search-layout-night.png', fullPage: true })
  })
})
