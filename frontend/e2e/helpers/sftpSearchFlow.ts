import { expect, type Locator, type Page } from '@playwright/test'
import { gotoApp } from './nav'
import type { SftpTestServer } from './sftpServer'

/**
 * SFTP 搜索页的共用流程层（连接 → 进搜索页 → 填条件 → 读结果）。
 *
 * 从 `sftp/search.spec.ts` 原样抽出，断言语义一条没改；抽出来是因为布局用例
 * （`sftp/search-layout.spec.ts`）要走**同一条**真链路：复制一份连接流程的话，
 * 连接页改版时两处会各自漂移，而这两处对「什么时候算连上」的判断必须一致。
 *
 * 四条不显然的前提（原文注释一并搬来，别当装饰删掉）：
 * - **不能 `page.goto` 切页**：整页导航会销毁文档 → Pinia store 连同 SSE 读循环一起没，
 *   正好把「跨页面驻留」测成反面；切页一律 `spaTo` 走侧边栏链接。
 * - **进搜索页走浏览器页的「高级搜索」**：roots 由面包屑当前目录预填，这样每条用例只有
 *   一处决定搜哪个目录；直接 `gotoApp('/sftp/search')` 拿到的是空表单。
 * - **`el-date-picker` 的 `data-testid` 只能挂外层 span**：EP 把未识别属性并进 tooltip 后
 *   整个丢掉（渲染走查实测挂组件上命中 0）。
 * - **数值框用 `el-input[type=number]` 不用 `el-input-number`**：后者 fallthrough 落在根 div，
 *   `fill()` 打在非编辑元素上。
 */
const PASSWORD = 'e2e123'

/** 三态徽章的 testid：等终态、判「有没有 run」都读它 */
export const STATUS = 'sftp-search-status'

function fieldByLabel(page: Page, label: string): Locator {
  return page
    .locator('.connect-form .el-form-item')
    .filter({ has: page.locator('.el-form-item__label', { hasText: label }) })
    .locator('input')
    .first()
}

/** 与 reconnect.spec.ts 同款：断线续连的预填异步到达，先等它稳定再 fill（R4） */
export async function manualConnect(page: Page, srv: SftpTestServer) {
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

export async function ensureDisconnected(page: Page) {
  await page.locator('.toolbar-card').waitFor({ state: 'visible', timeout: 20_000 }).catch(() => {})
  if (await page.locator('.toolbar-card').isVisible()) {
    await page.getByRole('button', { name: '断开' }).click()
    await expect(page.locator('.connect-card')).toBeVisible({ timeout: 15_000 })
  }
}

/**
 * 连接 → 用浏览器页走到 `root` → 从工具栏「高级搜索」进搜索页（roots 就是那个目录）。
 *
 * 不能 `gotoApp(page, '/sftp')` 之后省掉中间步：① 整页加载会连带清掉 `SftpBrowser.vue` 的
 * `connected` 这份**页面状态**（后端会话还在，页面却回到连接表单），要看下载按钮的用例
 * 那时根本没表格；② 预填的 roots 由面包屑当前目录决定，而连接落在哪个目录取决于上一条
 * 用例（断线续连是设计行为）→ 先把浏览器页开到明确目录，roots 才可复现。
 */
export async function connectAndOpenSearch(page: Page, srv: SftpTestServer, root = '/') {
  await gotoApp(page, '/sftp')
  await ensureDisconnected(page)
  await manualConnect(page, srv)
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
export async function spaTo(page: Page, menuLabel: string) {
  await page.locator('aside.sidebar').getByRole('link', { name: menuLabel, exact: true }).click()
  await page.waitForURL(/.+/)
  await page.waitForTimeout(400)
}

/** 等表格真正可交互：listLoading 期间遮罩吃掉全部鼠标事件（右键「弹不出」的真相，R2④） */
export async function waitTableReady(page: Page) {
  await expect(page.locator('.el-loading-mask')).toHaveCount(0, { timeout: 30_000 })
  await page.waitForTimeout(200)
}

// ---------------------------------------------------------------- 表单与读数

/** 展开「高级」折叠区（折叠体里的控件默认不在 DOM 交互路径上） */
export async function openAdvanced(page: Page) {
  await page.locator('.sc-adv .el-collapse-item__header').click()
  await expect(page.getByTestId('sftp-search-workers')).toBeVisible({ timeout: 5_000 })
}

export async function addTag(page: Page, testId: string, value: string) {
  const box = page.getByTestId(testId)
  await box.fill(value)
  await box.press('Enter')
  await expect(box).toHaveValue('')             // 回车即收录（草稿清空 = addRoot 跑过了）
}

export interface SearchForm {
  mode?: 'name' | 'content' | 'column'
  term?: string
  column?: string
  pattern?: string
  depth?: 'self' | 'children' | 'all' | 'custom'
  prune?: string[]
  workers?: string
  maxCandidates?: string
  maxMatches?: string
  stopAfterListing?: boolean
}

export const MODE_LABEL = { name: '文件名', content: '内容含', column: '列名' } as const
export const DEPTH_LABEL = { self: '仅当前层', children: '含下一层', all: '全部递归', custom: '自定义' } as const

/**
 * 填条件并点「搜索」。模式先切（term 输入框是 v-if 出来的，切了才渲染）。
 * roots 不在这里填：它由 `connectAndOpenSearch` 走「高级搜索」预填进来（含 `resetSearchPage`
 * 之后 —— URL 上的 `?root=` 还在，重载后照样预填），这样每条用例只有一处决定搜哪个目录。
 */
export async function runSearch(page: Page, form: SearchForm) {
  // 模式必须**先**切：term / column 两个输入框是 v-if 出来的，切了档才渲染
  if (form.mode) {
    await page.getByTestId('sftp-search-mode').getByText(MODE_LABEL[form.mode]).click()
  }
  if (form.term) await page.getByTestId('sftp-search-term').fill(form.term)
  if (form.column) await page.getByTestId('sftp-search-column').fill(form.column)
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
export async function resetSearchPage(page: Page) {
  await page.reload()
  await expect(page.getByTestId('sftp-search-run')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId(STATUS)).toHaveCount(0)
}

/** 等这条 run 收尾（done/partial/cancelled/error 都是终态） */
export async function waitSettled(page: Page, timeout = 90_000) {
  await expect(page.getByTestId(STATUS))
    .toHaveText(/done|partial|cancelled|error/, { timeout })
}

/** 结果表徽章：store 落到 DOM 的行数口径（虚拟滚动下唯一可信的「有多少行」） */
export async function badge(page: Page): Promise<{ candidates: number; matches: number; rows: number }> {
  const text = await page.getByTestId('sftp-search-results-count').innerText()
  const pick = (re: RegExp) => Number((text.match(re) ?? [])[1] ?? NaN)
  return { candidates: pick(/候选 (\d+)/), matches: pick(/命中 (\d+)/), rows: pick(/表格 (\d+) 行/) }
}
