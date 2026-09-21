import { test, expect, type Locator, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { gotoApp } from '../helpers/nav'
import { startSftpServer, type SftpTestServer } from '../helpers/sftpServer'
import { captureDownload } from '../helpers/download'

/**
 * SFTP 搜索子系统 e2e（计划 Task 18 / spec §3.13、§4.4）。四条不显然的前提：
 * - **fixture**：主树是 `sftp_server.py:write_fixture_tree`（`startSftpServer({fixture:true})`
 *   打开），与 Task 11B 的 Python 集成测试同一份字节。本文件只额外造 `lots/`，它不为内容
 *   对不对而存在，只为把一次内容搜索拉到十几秒 —— 「进行中」的性质要有够长的窗口。
 * - **「进行中」怎么钉（计划 Step 4）**：`page.route` 压住 `POST /sftp/search/` 的响应几秒，
 *   这期间 fetch 拿不到字节，store 恒为 running。abort 后 `route.continue()` 必 reject（不
 *   catch 就是未处理拒绝），断言完必须 `unroute`，否则下一条用例的搜索也被压住。
 * - **切页不能 `page.goto`**：那是整页导航，文档销毁 → Pinia store 连同它持有的 SSE 读循环
 *   一起没了，正好把「跨页面驻留」测成反面。切页一律走侧边栏链接（同文档跳转）。计划 Step 5
 *   两段代码写的就是 `page.goto('/data')`，照抄必然失败。
 * - **行数口径（AG Grid 虚拟滚动）**：DOM 里只有视口内的行**与列** → 不能用 `toHaveCount`
 *   断言行数（那测的是渲染）。比的是计数徽章（`表格 N 行`）+ 可见 path 数组的相等与去重。
 *
 * 跑法：`npx playwright test e2e/sftp/search.spec.ts --project=P1 --workers=1` —— 会话与主机
 * 密钥按 user 存，必须 serial（R6）；不带 `--project=P1` 会落进 Edge 那个 `grepInvert`
 * project 被静默跳过（假绿）。本文件不触发下载导入，故无 DB 残留要清。
 */
const PASSWORD = 'e2e123'
const SEARCH_ROUTE = '**/sftp/search/'
const STATUS = 'sftp-search-status'

let server: SftpTestServer

// ---------------------------------------------------------------- 连接与导航
function fieldByLabel(page: Page, label: string): Locator {
  return page
    .locator('.connect-form .el-form-item')
    .filter({ has: page.locator('.el-form-item__label', { hasText: label }) })
    .locator('input')
    .first()
}

/** 与 reconnect.spec.ts 同款：断线续连的预填异步到达，先等它稳定再 fill（R4） */
async function manualConnect(page: Page, srv: SftpTestServer) {
  const host = page.getByPlaceholder('例如: 192.168.1.1')
  await expect.poll(async () => {
    const v1 = await host.inputValue()
    await page.waitForTimeout(300)
    return v1 === (await host.inputValue())
  }, { timeout: 10_000 }).toBe(true)
  await host.fill(srv.host)
  await fieldByLabel(page, '端口').fill(String(srv.port))
  await fieldByLabel(page, '端口').blur()      // el-input-number 要 blur 才发 model-value
  await fieldByLabel(page, '用户名').fill('e2e')
  await fieldByLabel(page, '密码').fill(PASSWORD)
  await page.getByRole('button', { name: '连接' }).click()
  await expect(page.locator('.toolbar-card')).toBeVisible({ timeout: 20_000 })
}

async function ensureDisconnected(page: Page) {
  await page.locator('.toolbar-card').waitFor({ state: 'visible', timeout: 20_000 }).catch(() => {})
  if (await page.locator('.toolbar-card').isVisible()) {
    await page.getByRole('button', { name: '断开' }).click()
    await expect(page.locator('.connect-card')).toBeVisible({ timeout: 15_000 })
  }
}

/**
 * 连接 → 用浏览器页走到 `root` → 从工具栏「高级搜索」进搜索页（roots 就是那个目录）。
 *
 * 不能 `gotoApp('/sftp/search')`：① 整页加载会连带清掉 `SftpBrowser.vue` 的 `connected`
 * 这份**页面状态**（后端会话还在，页面却回到连接表单），用例 8a/9 之后要回浏览器页看下载
 * 按钮，那时根本没表格；② 预填的 roots 由面包屑当前目录决定，而连接落在哪个目录取决于上一条
 * 用例（断线续连是设计行为）→ 先把浏览器页开到明确目录，roots 才可复现。
 */
async function connectAndOpenSearch(page: Page, root = '/') {
  await gotoApp(page, '/sftp')
  await ensureDisconnected(page)
  await manualConnect(page, server)
  await page.waitForTimeout(500)                   // 等「跳到上次访问目录」那一步先落地
  await page.locator('.toolbar-card .el-breadcrumb__item').first().click()   // Home 回根
  await waitTableReady(page)
  await expect(page.locator('.file-name', { hasText: 'root.csv' })).toBeVisible({ timeout: 20_000 })
  for (const seg of root.split('/').filter(Boolean)) {
    await page.locator('.file-name', { hasText: seg }).first().click()
    await expect(page.locator('.toolbar-card .el-breadcrumb')).toContainText(seg, { timeout: 20_000 })
    await waitTableReady(page)
  }
  await page.getByTestId('sftp-advanced-search').click()
  await expect(page.getByTestId('sftp-search-run')).toBeVisible({ timeout: 15_000 })
  await expect(page.locator('.sc-tags .el-tag')).toHaveText([root], { timeout: 10_000 })
}

/** 同文档导航（**不能**用 page.goto，见文件头） */
async function spaTo(page: Page, menuLabel: string) {
  await page.locator('aside.sidebar').getByRole('link', { name: menuLabel, exact: true }).click()
  await page.waitForURL(/.+/)
  await page.waitForTimeout(400)
}

/** 等表格真正可交互：listLoading 期间遮罩吃掉全部鼠标事件（右键「弹不出」的真相，R2④） */
async function waitTableReady(page: Page) {
  await expect(page.locator('.el-loading-mask')).toHaveCount(0, { timeout: 30_000 })
  await page.waitForTimeout(200)
}

/**
 * 真鼠标右键（move + down/up）。`click({button:'right'})` 会**额外**派发 click → 目录行
 * row-click 顺手导航，刚弹的浮层被 scroll 监听收掉；`dispatchEvent('contextmenu')` 是通用
 * Event，clientX/Y 进不去 → 浮层被挤到视口外。两个坑都实测过。
 */
async function rightClick(page: Page, target: Locator) {
  await target.scrollIntoViewIfNeeded()
  const box = await target.boundingBox()
  if (!box) throw new Error('rightClick: 目标不可见')
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down({ button: 'right' })
  await page.mouse.up({ button: 'right' })
}

// ---------------------------------------------------------------- 表单与读数
async function openAdvanced(page: Page) {
  await page.locator('.sc-adv .el-collapse-item__header').click()
  await expect(page.getByTestId('sftp-search-workers')).toBeVisible({ timeout: 5_000 })
}

async function addTag(page: Page, testId: string, value: string) {
  const box = page.getByTestId(testId)
  await box.fill(value)
  await box.press('Enter')
  await expect(box).toHaveValue('')             // 回车即收录（草稿清空 = addRoot 跑过了）
}

interface SearchForm {
  mode?: 'name' | 'content' | 'column'
  term?: string
  pattern?: string
  depth?: 'self' | 'children' | 'all' | 'custom'
  prune?: string[]
  workers?: string
  maxCandidates?: string
  maxMatches?: string
  stopAfterListing?: boolean
}

const MODE_LABEL = { name: '文件名', content: '内容含', column: '列名' } as const
const DEPTH_LABEL = { self: '仅当前层', children: '含下一层', all: '全部递归', custom: '自定义' } as const

/**
 * 填条件并点「搜索」。模式先切（term 输入框是 v-if 出来的，切了才渲染）。
 * roots 不在这里填：它由 `connectAndOpenSearch` 走「高级搜索」预填进来（含 `resetSearchPage`
 * 之后 —— URL 上的 `?root=` 还在，重载后照样预填），这样每条用例只有一处决定搜哪个目录。
 */
async function runSearch(page: Page, form: SearchForm) {
  if (form.mode) {
    await page.getByTestId('sftp-search-mode').getByText(MODE_LABEL[form.mode]).click()
  }
  if (form.term) await page.getByTestId('sftp-search-term').fill(form.term)
  if (form.pattern) await page.getByTestId('sftp-search-pattern').fill(form.pattern)
  if (form.depth) {
    await page.getByTestId('sftp-search-depth').getByText(DEPTH_LABEL[form.depth]).click()
  }
  for (const p of form.prune ?? []) await addTag(page, 'sftp-search-prune', p)
  if (form.stopAfterListing || form.workers || form.maxCandidates || form.maxMatches) {
    await openAdvanced(page)
    if (form.stopAfterListing) {
      await page.getByTestId('sftp-search-stop-after-listing').click()
    }
    if (form.workers) await page.getByTestId('sftp-search-workers').fill(form.workers)
    if (form.maxCandidates) await page.getByTestId('sftp-search-max-candidates').fill(form.maxCandidates)
    if (form.maxMatches) await page.getByTestId('sftp-search-max-matches').fill(form.maxMatches)
  }
  await page.getByTestId('sftp-search-run').click()
}

/**
 * 整页重载搜索页 = store 与表单一起清零，让**下一条 run 成为唯一的一条**。
 *
 * 本地 SFTP 上一次列目录档的搜索不到 100ms 就跑完，`running` 那一帧在第一次轮询前就翻成
 * done/partial（实测 43 次轮询全看到终态），「等它变 running」对快查询不成立；而不等又
 * 危险 —— DOM 上还挂着上一条 run 的终态徽章，`waitSettled` 会立刻拿旧 run 判绿。
 */
async function resetSearchPage(page: Page) {
  await page.reload()
  await expect(page.getByTestId('sftp-search-run')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId(STATUS)).toHaveCount(0)
}

/** 等这条 run 收尾（done/partial/cancelled/error 都是终态） */
async function waitSettled(page: Page, timeout = 90_000) {
  await expect(page.getByTestId(STATUS))
    .toHaveText(/done|partial|cancelled|error/, { timeout })
}

/** 结果表徽章：store 落到 DOM 的行数口径（虚拟滚动下唯一可信的「有多少行」） */
async function badge(page: Page): Promise<{ candidates: number; matches: number; rows: number }> {
  const text = await page.getByTestId('sftp-search-results-count').innerText()
  const pick = (re: RegExp) => Number((text.match(re) ?? [])[1] ?? NaN)
  return { candidates: pick(/候选 (\d+)/), matches: pick(/命中 (\d+)/), rows: pick(/表格 (\d+) 行/) }
}

/**
 * 读 AG Grid 某一列的**数据**单元格（计划 Step 5 的 `pathCells` 的加固版）。原文照抄会被两处
 * 渲染细节咬到：① **列也参与虚拟** —— `path` 是最后一列，内容档多出「命中行/命中片段」后它
 * 被挤出可视区，实测读到空数组，所以第一遍读不到才滚到最右再读（能读到就不滚，滚了反而把
 * snippet 那侧推出去）；② **filler row** —— 未渲染的行也占一个同 `col-id` 的空格。
 */
async function agColumnCells(page: Page, colId: string): Promise<string[]> {
  const read = () => page.locator(`.ag-cell[col-id="${colId}"]`)
    .evaluateAll((els) => els.map((e) => e.textContent?.trim() ?? ''))
  let cells = await read()
  if (!cells.some((c) => c !== '')) {
    await page.locator('.ag-body-viewport').first()
      .evaluate((el) => { el.scrollLeft = el.scrollWidth }).catch(() => {})
    await page.waitForTimeout(150)
    cells = await read()
  }
  return cells.filter((c) => c !== '')
}

/** 计划 Step 5 的读数 helper（加固见 agColumnCells）：可见的**数据行**路径 */
async function pathCells(page: Page): Promise<string[]> {
  return agColumnCells(page, 'path')
}

/** 顺序不参与断言的比较：把可见路径排序后再比集合 */
async function sortedPaths(page: Page): Promise<string[]> {
  return (await pathCells(page)).sort()
}

/** 把搜索响应压住 `ms` 毫秒（制造确定的「进行中」窗口），返回解除阻塞用的收尾函数 */
async function holdSearchResponse(page: Page, ms = 4000) {
  await page.route(SEARCH_ROUTE, async (route) => {
    await new Promise((r) => setTimeout(r, ms))
    // 取消后 continue() 必 reject（fetch 已 abort），不吞掉就是测试进程里的未处理拒绝
    await route.continue().catch(() => {})
  })
  return async () => { await page.unroute(SEARCH_ROUTE) }
}

// ---------------------------------------------------------------- 造 lots/ 慢树
/**
 * 60 目录 × 100 份小文件、每份含查询串：本地 SFTP 一次 open+read+close 约 2–3ms，workers=1
 * 下整轮十几秒 —— 够从容走完「切页 → 计数在涨 → 从 chip 取消」。摊到 60 个目录而不是堆一个：
 * 单目录 4000 行会把 SFTP 浏览器页的 `el-table`（无虚拟滚动）拖死。
 *
 * 文件名一律 `L_*`，不沿用 fixture 树的 `RT_*`：用例 3/4 拿 `RT_3*` / `RT_9*` 在整棵 `/` 上
 * 跑，慢树沾上这两个前缀就会把「唯一命中」变成上百命中。
 */
function writeLotsTree(root: string): void {
  for (let lot = 0; lot < 60; lot++) {
    const dir = path.join(root, 'lots', `lot${lot}`)
    fs.mkdirSync(dir, { recursive: true })
    for (let k = 0; k < 100; k++) {
      let body = '[DATA]\r\nSN,ShadowReg2\r\n'
      for (let r = 0; r < 40; r++) body += `row${r},${r * 2}\r\n`
      fs.writeFileSync(path.join(dir, `L_${lot}_${k}.csv`), body)
    }
  }
  // 名字带逗号的那一份是导出用例的靶子（路径列必须不被劈成两列）
  fs.writeFileSync(path.join(root, 'lots', 'lot0', 'RT_a,b.csv'), '[DATA]\r\nSN,ShadowReg2\r\n')
  // XSS 探针（用例 13）：`term` 与片段都是用户/文件里的字面文本，走 v-html 就是自造 XSS 面
  fs.writeFileSync(
    path.join(root, 'lots', 'lot0', 'XSS_probe.csv'),
    '[DATA]\r\nSN,<img src=x onerror=alert(1)>\r\nShadowReg2,1\r\n',
  )
}

// ---------------------------------------------------------------- 用例
test.describe.configure({ mode: 'serial', timeout: 240_000 })

// 结果表在 1280 视口下会把「路径」列挤出可视区（AG Grid 横向虚拟列），读数就成空数组。
// 给一个够宽的视口让七列都排得下，读数才只反映数据、不反映窗口大小。
test.use({ viewport: { width: 1680, height: 1000 } })

test.describe('@sftp SFTP 搜索', { tag: ['@p1', '@sftp'] }, () => {
  test.beforeAll(async () => {
    server = await startSftpServer({ fixture: true })
    writeLotsTree(server.root)
    console.log(`[search.spec] sftp root=${server.root} port=${server.port}`)
  })

  test.afterAll(() => { server?.stop() })

  test('1 仅文件名搜索：*RT* 的命中集合与路径', async ({ page }) => {
    await connectAndOpenSearch(page, '/batch1')
    await runSearch(page, { mode: 'name', pattern: '*RT*', depth: 'self' })
    await waitSettled(page)
    await expect(page.getByTestId(STATUS)).toHaveText(/done|partial/)
    expect(await sortedPaths(page)).toEqual(['/batch1/RT_1.csv', '/batch1/RT_2.csv'])
    // name 档后端只发候选、不发命中（runner 在该档不下内容）——「命中 0」是契约不是缺数据
    const b = await badge(page)
    expect(b.rows).toBe(2)
    expect(b.candidates).toBe(2)
    expect(b.matches).toBe(0)
  })

  test('2 内容搜索命中：片段含 term 且带行号', async ({ page }) => {
    await connectAndOpenSearch(page, '/batch1')
    await runSearch(page, { mode: 'content', term: 'ShadowReg2', depth: 'self' })
    await waitSettled(page)
    // /batch1 直属：RT_1、RT_2、BIG.csv 命中；FT_1 不含该串；Sum_total 被 data_files_only 排除
    expect(await sortedPaths(page)).toEqual(
      ['/batch1/BIG.csv', '/batch1/RT_1.csv', '/batch1/RT_2.csv'])
    const snippets = await agColumnCells(page, 'snippet')
    expect(snippets.length).toBeGreaterThan(0)
    for (const s of snippets) expect(s).toContain('ShadowReg2')
    const lines = await agColumnCells(page, 'line')
    expect(lines.every((l) => /^\d+$/.test(l.trim()))).toBe(true)
  })

  test('3 深度档位：children 搜不到两层下的文件，all 搜得到', async ({ page }) => {
    await connectAndOpenSearch(page, '/')
    // /batch1/Deep/RT_3.csv 在根的第二个子层下（batch1=1 层，Deep=2 层）
    await runSearch(page, { mode: 'name', pattern: 'RT_3*', depth: 'children' })
    await waitSettled(page)
    expect(await sortedPaths(page)).toEqual([])
    expect((await badge(page)).rows).toBe(0)

    await resetSearchPage(page)
    await runSearch(page, { mode: 'name', pattern: 'RT_3*', depth: 'all' })
    await waitSettled(page)
    expect(await sortedPaths(page)).toEqual(['/batch1/Deep/RT_3.csv'])
  })

  test('4 剪枝：prune_dirs 让 backup 整棵子树消失', async ({ page }) => {
    await connectAndOpenSearch(page, '/')
    await runSearch(page, { mode: 'name', pattern: 'RT_9*', depth: 'children' })
    await waitSettled(page)
    expect(await sortedPaths(page)).toEqual(['/backup/RT_9.csv'])

    await resetSearchPage(page)
    await runSearch(page, { mode: 'name', pattern: 'RT_9*', depth: 'children', prune: ['backup'] })
    await waitSettled(page)
    const paths = await pathCells(page)
    expect(paths).toEqual([])
    expect(paths.filter((p) => p.includes('/backup/'))).toEqual([])
  })

  test('5 中文 term：回落客户端引擎且 GBK 文件被命中', async ({ page }) => {
    await connectAndOpenSearch(page, '/batch2')
    await runSearch(page, { mode: 'content', term: '漏电电流', depth: 'self' })
    await waitSettled(page)
    // 引擎徽章只在收到 hello 后出现（未确定时压根不渲染这个 testid，见 SearchProgress）
    await expect(page.getByTestId('sftp-search-engine')).toHaveText('client', { timeout: 20_000 })
    // 真断言的是「非 ASCII 不静默漏」：GBK 那份必须命中且片段解码正确
    expect(await sortedPaths(page)).toEqual(['/batch2/RT_10.csv'])
    const snippets = await agColumnCells(page, 'snippet')
    expect(snippets.join('|')).toContain('漏电电流')
  })

  test('6 仅列候选：只出范围不出命中', async ({ page }) => {
    await connectAndOpenSearch(page, '/')
    const started = Date.now()
    await runSearch(page, {
      mode: 'content', term: 'ShadowReg2', depth: 'self', stopAfterListing: true,
    })
    await waitSettled(page)
    expect(Date.now() - started, '仅列候选不该等真扫描').toBeLessThan(60_000)
    const b = await badge(page)
    expect(b.candidates).toBeGreaterThan(0)
    expect(b.matches).toBe(0)
    // 表里这时列的是「待扫描的候选」，页面必须说清楚，否则用户以为这就是最终结果
    await expect(page.locator('.srt-hint')).toContainText('还没有命中')
  })

  test('7 取消：进行中可取消，取消后真实链路仍可用', async ({ page }) => {
    const release = await holdSearchResponse(page)
    try {
      await connectAndOpenSearch(page, '/batch1')
      await runSearch(page, { mode: 'content', term: 'ShadowReg2', depth: 'self' })
      const chip = page.getByTestId('sftp-search-chip')
      // 响应被压住 → 一个事件都没到 → running 是一段有保证的窗口（不是撞运气）
      await expect(page.getByTestId(STATUS)).toHaveText('running')
      await expect(chip).toBeVisible()
      // 进度面板与 chip 各挂一个取消按钮（计划 Step 4 的钩子，两处都要在）
      await expect(page.getByTestId('search-cancel-btn')).toHaveCount(2)
      await expect(page.getByTestId('sftp-search-run')).toBeDisabled()
      await chip.getByTestId('search-cancel-btn').click()
      await expect(chip).toBeHidden()
      await expect(page.getByTestId(STATUS)).toHaveText('cancelled')
      // 取消冷却（store 那 1.2s）期间不许立刻再开一条流在同一批临时连接上打架
      await expect(page.getByTestId('sftp-search-run')).toBeDisabled()
      await expect(page.getByTestId('sftp-search-run')).toBeEnabled({ timeout: 6_000 })
    } finally {
      await release()
    }
    // 真实链路没被刚才的 abort 弄坏：同一套条件再搜一次，这次要拿到结果
    await resetSearchPage(page)
    await runSearch(page, { mode: 'content', term: 'ShadowReg2', depth: 'self' })
    await waitSettled(page)
    expect((await badge(page)).matches).toBe(3)
  })

  test('8a 驻留：搜索已结束，切页再回来结果不丢不重不重排', async ({ page }) => {
    await connectAndOpenSearch(page, '/batch1')
    await runSearch(page, { mode: 'content', term: 'ShadowReg2', depth: 'self' })
    await waitSettled(page)

    const expected = await pathCells(page)
    expect(expected.length).toBeGreaterThanOrEqual(3)
    expect(new Set(expected).size).toBe(expected.length)      // 基线：本身无重复
    const before = await badge(page)

    await spaTo(page, '数据管理')
    // 已结束 → chip 必须已经消失（计划 Step 4 明写这条要显式断，不默认它在）
    await expect(page.getByTestId('sftp-search-chip')).toBeHidden()
    await spaTo(page, 'SFTP浏览器')
    await page.getByTestId('sftp-advanced-search').click()

    const after = await pathCells(page)
    expect(after).toEqual(expected)                            // 无丢失、无重排
    expect(new Set(after).size).toBe(after.length)             // 无重复回灌
    expect(await badge(page)).toEqual(before)                  // 行数口径也没变
  })

  test('8b 驻留：进行中切页 chip 计数仍在涨，可在别页取消', async ({ page }) => {
    await connectAndOpenSearch(page, '/lots')
    // lots/ 那 6000 份 + workers=1 才有十几秒窗口；上限要抬到树之上，否则 2000 命中处
    // 自停，用户还没切完页它就已经跑完了 —— 那时断言的是「已结束」，不是本条要证的性质
    await runSearch(page, {
      mode: 'content', term: 'ShadowReg2', depth: 'all',
      workers: '1', maxCandidates: '20000', maxMatches: '30000',
    })
    await expect(page.getByTestId(STATUS)).toHaveText('running', { timeout: 20_000 })

    await spaTo(page, '数据管理')
    const chip = page.getByTestId('sftp-search-chip')
    await expect(chip).toBeVisible()                           // 离开 SFTP 页仍然可见
    const matched = chip.getByTestId('sftp-search-chip-matched')
    const scanned = chip.getByTestId('sftp-search-chip-scanned')
    const firstMatched = Number(await matched.textContent())
    const firstScanned = Number((await scanned.textContent()).match(/\d+/)?.[0] ?? 0)
    // 「计数确实在涨」= 流在别人页面上也还在被读、还在往 store 里灌
    await expect.poll(async () => Number(await matched.textContent()),
      { timeout: 60_000, intervals: [500, 1000, 2000] }).toBeGreaterThan(firstMatched)
    await expect.poll(async () => Number((await scanned.textContent()).match(/\d+/)?.[0] ?? 0),
      { timeout: 60_000, intervals: [500, 1000, 2000] }).toBeGreaterThan(firstScanned)

    await chip.getByTestId('search-cancel-btn').click()
    await expect(chip).toBeHidden()
    await spaTo(page, 'SFTP浏览器')
    await page.getByTestId('sftp-advanced-search').click()
    await expect(page.getByTestId(STATUS)).toHaveText('cancelled')
  })

  test('9 互斥：搜索进行中浏览器页的下载入口全部禁用且有原因', async ({ page }) => {
    const release = await holdSearchResponse(page, 12_000)
    try {
      // 根 '/'：浏览器页要能同时看到**目录行**（batch1）与**文件行**（root.csv）的下载按钮
      await connectAndOpenSearch(page, '/')
      await runSearch(page, { mode: 'content', term: 'ShadowReg2', depth: 'self' })
      await expect(page.getByTestId(STATUS)).toHaveText('running')
      await spaTo(page, 'SFTP浏览器')
      await waitTableReady(page)
      const dirRow = page.locator('.file-table .el-table__row').filter({ hasText: 'batch1' }).first()
      await expect(dirRow.getByRole('button', { name: '下载' })).toBeDisabled()
      const fileRow = page.locator('.file-table .el-table__row').filter({ hasText: 'root.csv' }).first()
      await expect(fileRow.getByRole('button', { name: '下载' })).toBeDisabled()
      await expect(fileRow.getByRole('button', { name: '解析' })).toBeDisabled()
      // 禁了还得说为什么：浏览器不给 disabled 的 button 派发鼠标事件，所以触发物是外层 span
      await fileRow.locator('.tip-anchor').first().hover()
      await expect(page.locator('.el-popper:visible', { hasText: '搜索进行中' }).first())
        .toBeVisible({ timeout: 5_000 })
    } finally {
      await page.getByTestId('sftp-search-chip').getByTestId('search-cancel-btn')
        .click().catch(() => {})
      await release()
    }
  })

  test('10 截断告知：partial 黄条常驻且不可关，且说的是中文', async ({ page }) => {
    await connectAndOpenSearch(page, '/')
    // 上限只在**两批目录之间**判（`walker.walk` 的循环头），所以要一个「还有下一批」的形状：
    // 根 '/' + depth all + name 档（不读内容，纯列举触发）。拿 /batch1 的 self 档试过：列完
    // 唯一那个目录后 pending 已空，`truncated_candidates` 根本不会被记，黄条只剩
    // truncated_depth —— 这条用例就变成在测深度档。
    await runSearch(page, { mode: 'name', depth: 'all', maxCandidates: '1' })
    await waitSettled(page)
    await expect(page.getByTestId(STATUS)).toHaveText('partial')
    const alert = page.getByTestId('sftp-search-truncated')
    await expect(alert).toBeVisible()
    await expect(alert).toContainText('结果不完整')
    // 说的是「候选上限」这条截断（不是顺带被深度档位挡了一下）：码名只在 data-code 上，
    // 用户读到的那句中文直接来自后端 notice.message —— 前端没有第二份码表可对照。
    await expect(alert.locator('[data-code="truncated_candidates"]'))
      .toHaveText('候选数已达上限，结果集不完整')
    const shown = (await alert.locator('p').allInnerTexts()).join('\n')
    expect(shown).not.toMatch(/truncated_|scan_budget_|dir_unreadable/)
    // 不可关：EP 的关闭按钮压根不该渲染出来（:closable="false"），而不是「有但藏起来」
    await expect(alert.locator('.el-alert__close-btn')).toHaveCount(0)
    await page.locator('.srt-title').click()                  // 碰一下别处，验证它不自动消失
    await page.waitForTimeout(1_500)
    await expect(alert).toBeVisible()
  })

  test('11 导出 CSV：带 BOM 且含逗号字段不被拆列', async ({ page }) => {
    await connectAndOpenSearch(page, '/lots/lot0')
    await runSearch(page, { mode: 'name', pattern: 'RT_a*', depth: 'self' })
    await waitSettled(page)
    expect(await sortedPaths(page)).toEqual(['/lots/lot0/RT_a,b.csv'])

    const { savedPath, suggestedName } = await captureDownload(
      page, () => page.getByTestId('sftp-results-export').click(), 'sftp-search')
    expect(suggestedName).toMatch(/^sftp_search_name_\d{8}_\d{6}\.csv$/)
    const buf = fs.readFileSync(savedPath)
    // 无 BOM → Excel 按本地代码页猜编码，中文列名全乱码
    expect([...buf.subarray(0, 3)]).toEqual([0xEF, 0xBB, 0xBF])

    const rows = splitCsv(buf.subarray(3).toString('utf8'))
    expect(rows[0]).toEqual(['名称', '完整路径', '字节', '修改时间(epoch秒)'])
    expect(rows.length).toBe(2)
    // 含逗号的路径必须仍是**一列**（劈成两列的话这行就比表头多一格）
    expect(rows[1][1]).toBe('/lots/lot0/RT_a,b.csv')
    for (const r of rows) expect(r.length).toBe(rows[0].length)
    fs.rmSync(savedPath, { force: true })
  })

  test('12 roots 入口：目录行右键「在此目录搜索」带路径进页', async ({ page }) => {
    await gotoApp(page, '/sftp')
    await ensureDisconnected(page)
    await manualConnect(page, server)
    await page.locator('.toolbar-card .el-breadcrumb__item').first().click()
    await waitTableReady(page)
    // 文件行右键不该出菜单（只有目录行才谈得上「以它为根」）
    const fileRow = page.locator('.file-table .el-table__row').filter({ hasText: 'root.csv' }).first()
    await rightClick(page, fileRow.locator('.file-name').first())
    expect(await page.getByTestId('sftp-search-in-dir').count()).toBe(0)
    const dirRow = page.locator('.file-table .el-table__row').filter({ hasText: 'batch1' }).first()
    await rightClick(page, dirRow.locator('.file-name').first())
    await expect(page.getByTestId('sftp-search-in-dir')).toBeVisible({ timeout: 5_000 })
    // 右键不该顺手导航进目录（只有左键 row-click 才导航）：根目录独有的 root.csv 还在
    expect(await page.locator('.file-name', { hasText: 'root.csv' }).count()).toBeGreaterThan(0)
    await page.getByTestId('sftp-search-in-dir').click()
    await expect(page).toHaveURL(/\/sftp\/search/)
    await expect(page.locator('.sc-tags .el-tag').first()).toContainText('/batch1', { timeout: 10_000 })

    // 另一个入口：工具栏「高级搜索」预填的是**当时**的面包屑目录（计划 Step 5.1）
    await spaTo(page, 'SFTP浏览器')
    await waitTableReady(page)
    await page.locator('.file-name', { hasText: 'batch2' }).first().click()
    await expect(page.locator('.toolbar-card .el-breadcrumb')).toContainText('batch2', { timeout: 20_000 })
    await page.getByTestId('sftp-advanced-search').click()
    await expect(page.locator('.sc-tags .el-tag')).toHaveText(['/batch1', '/batch2'], { timeout: 10_000 })
  })

  test('13 命中片段是字面文本：XSS 红线（spec §3.13 四条硬约束之一）', async ({ page }) => {
    let dialogFired = false
    page.on('dialog', async (d) => { dialogFired = true; await d.dismiss().catch(() => {}) })
    await connectAndOpenSearch(page, '/lots/lot0')
    await runSearch(page, {
      mode: 'content', term: '<img src=x onerror=alert(1)>', depth: 'self',
    })
    await waitSettled(page)
    expect(await sortedPaths(page)).toEqual(['/lots/lot0/XSS_probe.csv'])
    const snippets = await agColumnCells(page, 'snippet')
    expect(snippets.join('|')).toContain('onerror=alert(1)')     // 原样是**文本**
    expect(await page.locator('.srt-snippet img').count()).toBe(0)  // 不是被解析出来的节点
    expect(await page.evaluate(() => document.querySelectorAll('img[src="x"]').length)).toBe(0)
    expect(dialogFired, '片段渲染不得执行用户输入里的脚本').toBe(false)
  })

  test('14 未连接：400 not_connected 变引导条，「去连接」跳回浏览器页', async ({ page }) => {
    // 计划 Step 2 / spec §3.13 末段：搜索页**不探测**连接状态，只认 400 里那句哨兵。
    // 「断开」按钮只在浏览器页 UI 认为已连接时才渲染，而 `connected` 是**页面状态**：新页面
    // 一进来就是连接表单，`ensureDisconnected` 原地空转，后端按用户存的那条会话还活着 →
    // 搜索会真跑起来，要测的 400 永远不来。所以先连一次让按钮出现、再点它。
    await gotoApp(page, '/sftp')
    await ensureDisconnected(page)
    await manualConnect(page, server)
    await page.getByRole('button', { name: '断开' }).click()
    await expect(page.locator('.connect-card')).toBeVisible({ timeout: 15_000 })
    await gotoApp(page, '/sftp/search')
    await expect(page.getByTestId('sftp-search-roots')).toBeVisible({ timeout: 15_000 })
    await addTag(page, 'sftp-search-roots', '/batch1')      // 没有浏览器页可预填，手工给一个
    await runSearch(page, { mode: 'content', term: 'ShadowReg2' })
    const alert = page.locator('.ssp-alert')
    await expect(alert).toContainText('尚未建立 SFTP 连接', { timeout: 20_000 })
    await expect(page.getByTestId(STATUS)).toHaveText('error')
    await page.getByTestId('sftp-search-goto-connect').click()
    await expect(page).toHaveURL(/\/sftp$/)
  })

  test('15 只影响快慢的降级不染黄：grep 回落是中性一行，状态仍是 done', async ({ page }) => {
    // e2e 那台 SFTP 服务器拒一切 exec 请求（`helpers/sftp_server.py` 的
    // `check_channel_request` 只放行 session），所以「服务器没有 grep」在这里是常态、在生产
    // 环境更是常态。这类码只改快慢不改结果，一旦并进黄条判据，每次内容搜索都会被报成
    // partial（用户于是把完整结果当残缺结果重搜 —— 假警报比静默更耗信任）。
    // 深度用 **全部递归**：`self`/`children` 档会实打实记一条 `truncated_depth`（更深的目录
    // 确实没遍历），那是「少结果」该出黄条，测不到这条用例想测的性质。
    await connectAndOpenSearch(page, '/batch1')
    await runSearch(page, { mode: 'content', term: 'ShadowReg2', depth: 'all' })
    await waitSettled(page)
    await expect(page.getByTestId(STATUS)).toHaveText('done')
    await expect(page.getByTestId('sftp-search-truncated')).toHaveCount(0)
    const neutral = page.getByTestId('sftp-search-notices')
    await expect(neutral).toBeVisible()
    const line = neutral.locator('[data-code="grep_unavailable"]')
    await expect(line).toHaveCount(1)
    // 文案仍是后端给的那句（含探测原因），不许退化成裸码
    expect(await line.innerText()).toMatch(/grep/)
    expect(await line.innerText()).not.toContain('grep_unavailable')
    expect((await badge(page)).matches).toBeGreaterThan(0)
  })
})

/**
 * 最小 RFC 4180 解析（只够验导出这一份形状）：CRLF 分行、引号内的逗号不是分隔符、`""` 是一
 * 个引号。不用现成库：为一条断言加一个依赖不值。
 */
function splitCsv(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (quoted) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++ } else { quoted = false }
      } else field += c
      continue
    }
    if (c === '"') { quoted = true; continue }
    if (c === ',') { row.push(field); field = ''; continue }
    if (c === '\r' && text[i + 1] === '\n') {
      row.push(field); rows.push(row); row = []; field = ''; i++; continue
    }
    field += c
  }
  if (field !== '' || row.length) { row.push(field); rows.push(row) }
  return rows
}
