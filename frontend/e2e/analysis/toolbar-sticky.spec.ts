import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile } from '../helpers/params'
import { waitLoadingGone } from '../helpers/charts'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 单文件分析顶部工具区（2026-09-13）：
 *  - 「文件选择 + 参数选择 + 图表勾选」行 sticky 冻结——向下滚动看图表时仍可见；
 *  - 数据筛选行（#toolbar-2）与内容一起滚动；
 *  - 统计摘要压缩成单行紧凑条（原 5 列卡片网格最多 3 行 ≈126px）。
 *
 * 前提：sticky 的滚动祖先要落在 .content-area（EP 的 .el-tabs__content 默认
 * overflow:hidden 会困住 sticky，AnalysisPage 已放开——本用例即该覆盖的回归钉）。
 */

const SINGLE = '.single-param-tab'

async function openSingle(page: import('@playwright/test').Page) {
  await gotoApp(page, '/analysis')
  await selectAnalysisFile(page, RECOMMENDED.analysis)
  await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
  await waitLoadingGone(page.locator(SINGLE))
}

/** 滚动容器 .content-area 的可滚动余量 */
function scrollRoom(page: import('@playwright/test').Page) {
  return page.evaluate(() => {
    const el = document.querySelector('.content-area') as HTMLElement | null
    return el ? el.scrollHeight - el.clientHeight : 0
  })
}

async function scrollToBottom(page: import('@playwright/test').Page) {
  await page.evaluate(() => {
    const el = document.querySelector('.content-area') as HTMLElement | null
    if (el) el.scrollTop = el.scrollHeight
  })
}

test.describe('@p1 分析页顶部工具区冻结与统计条压缩', { tag: ['@p1', '@analysis'] }, () => {
  test('文件+参数行 sticky：滚动到底仍贴住滚动容器顶部，参数选择器在其内', async ({ page }) => {
    await openSingle(page)
    const toolbar = page.locator(`${SINGLE} > .toolbar`)
    await expect(toolbar).toBeVisible({ timeout: 20_000 })
    // 参数选择器在冻结行内（文件选择之后）
    await expect(toolbar.locator('.param-selector')).toBeVisible()
    await expect(toolbar.locator('.dp-analysis-filepicker')).toBeVisible()

    const room = await scrollRoom(page)
    test.skip(room < 120, '内容不足一屏，无 sticky 可验')

    await scrollToBottom(page)
    // 滚动到底后工具栏顶边仍贴在滚动容器的 scrollport 顶（= 容器顶 + padding-top，
    // sticky 的参照是 padding 盒而非 border 盒），±3px
    await expect
      .poll(async () => {
        const tb = await toolbar.boundingBox()
        const top = await page.locator('.content-area').evaluate((el) => {
          const r = el.getBoundingClientRect()
          return r.top + (parseFloat(getComputedStyle(el).paddingTop) || 0)
        })
        if (!tb) return 999
        return Math.abs(tb.y - top)
      }, { timeout: 5_000 })
      .toBeLessThanOrEqual(3)
  })

  test('数据筛选行不冻结：滚到底后滚出视口（与冻结行分离）', async ({ page }) => {
    await openSingle(page)
    const filters = page.locator(`${SINGLE} > .toolbar-2`)
    const room = await scrollRoom(page)
    test.skip(room < 120 || !(await filters.count()), '内容不足一屏或无次级工具栏')
    const before = (await filters.boundingBox())?.y ?? 0
    await scrollToBottom(page)
    await page.waitForTimeout(200)
    const after = (await filters.boundingBox())?.y ?? 0
    expect(after, '筛选行应随内容上移（不 sticky）').toBeLessThan(before - 20)
  })

  test('统计摘要为单行紧凑条（高度远小于旧卡片网格）', async ({ page }) => {
    await openSingle(page)
    const stats = page.locator(`${SINGLE} .stats-summary`).first()
    await expect(stats).toBeVisible({ timeout: 20_000 })
    const h = (await stats.boundingBox())!.height
    // 旧 5 列卡片网格：每项 min-height 42px、最多 3 行 ≈126px；单行条（含横向滚动条）≤ 36px
    expect(h, '统计条高度应 ≤ 36px').toBeLessThanOrEqual(36)
  })
})
