import { test, expect, type Page } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, listParams, selectParam, pickOutlierMode } from '../helpers/params'
import { waitLoadingGone } from '../helpers/charts'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 回归：「📊 范围对比」「📱 Site统计」在页面缩放后必须**无需横向滚动就同屏看全每一列**。
 *
 * 2026-09-14 修复前：左栏宽度 = el-col 的 25%，1920 视口 125% 缩放下只剩 307px，
 * 而两表的列宽由内容决定（范围对比 404px / Site统计 339px）→ Gap+Unit、>Max
 * 列在视口里根本看不到。旧用例把「表格内部能滚到最后一列」当通过口径，
 * 恰好掩盖了这一点（滚动条存在 ≠ 列可见）。
 *
 * 修复三处（详见各自文件注释）：
 *  - AnalysisTabLayout：左栏 min-width 385px（扣掉卡片内边距 30px 后容器 ~355px，
 *    两表内在宽实测 ~275 / ~319px），右栏改吃剩余空间；≤1120px 视口改纵向堆叠；
 *  - 范围对比：单位提到卡头（后端 unit 每个参数只有一个值），省掉一整列；
 *  - 两表单元格内边距 6px → 4px。
 *
 * 用例口径（升级后）：列清单固定 + 表格零横向溢出 + 最后一列右缘落在表格内。
 * 只留「滚动兜底」不成立也没关系 —— 极端内容仍可由表格自带横向滚动条兜底，
 * 但那是退化路径，不再作为通过条件。
 */
const SINGLE = '.single-param-tab'
const RANGE = '范围对比'
const SITE = 'Site统计'
const RANGE_COLS = ['', 'Low', 'High', 'Gap']
const SITE_COLS = ['Site', 'Yield', 'Fail', '<Min', '>Max']

interface TableMetrics {
  cols: string[]
  /** 表格内部横向溢出量（>0 即需要横向滚动才能看全列） */
  innerOverflow: number
  /** 最后一列表头右缘超出表格右缘的像素（>0 即被裁） */
  lastColOverflow: number
  /** 行 label 是否带 " (cut)" 后缀（裁剪范围模式下最宽的行标签） */
  hasCut: boolean
}

function tableMetrics(page: Page, title: string): Promise<TableMetrics | null> {
  return page.evaluate((t) => {
    const card = [...document.querySelectorAll<HTMLElement>('.left-panel .el-card')]
      .find((c) => c.querySelector('.table-header')?.textContent?.includes(t))
    const table = card?.querySelector<HTMLElement>('.el-table')
    if (!table) return null
    const wrap = table.querySelector<HTMLElement>('.el-scrollbar__wrap')
      ?? table.querySelector<HTMLElement>('.el-table__body-wrapper')
    // 列清单只看真实列：body 出现纵向滚动条时 EP 会在 thead 末尾塞一个 gutter 占位 th
    const ths = [...table.querySelectorAll<HTMLElement>('thead th')]
      .filter((th) => !th.classList.contains('gutter'))
    const last = ths[ths.length - 1]
    return {
      cols: ths.map((th) => th.textContent?.trim() ?? ''),
      innerOverflow: wrap ? wrap.scrollWidth - wrap.clientWidth : -1,
      lastColOverflow: last
        ? Math.round(last.getBoundingClientRect().right - table.getBoundingClientRect().right)
        : -1,
      hasCut: [...table.querySelectorAll('tbody tr td:first-child')]
        .some((td) => td.textContent?.includes('(cut)')),
    }
  }, title)
}

/** 两张表都要：列清单正确、零横向溢出、最后一列完整落在表格内 */
async function expectNoClippedColumns(page: Page) {
  const expected: [string, string[]][] = [[RANGE, RANGE_COLS], [SITE, SITE_COLS]]
  for (const [title, cols] of expected) {
    await expect
      .poll(async () => (await tableMetrics(page, title)) !== null, {
        message: `${title} 应已渲染`,
      })
      .toBe(true)
    const m = (await tableMetrics(page, title))!
    expect(m.cols, `${title} 列清单`).toEqual(cols)
    expect(m.innerOverflow, `${title} 不应需要横向滚动才能看全列`).toBeLessThanOrEqual(1)
    expect(m.lastColOverflow, `${title} 最后一列右缘应在表格内`).toBeLessThanOrEqual(1)
  }
}

/** 在给定时间内等范围对比表出现 (cut) 行标签；没有则返回 false（不抛错） */
async function hasCutWithin(page: Page, ms: number): Promise<boolean> {
  try {
    await expect
      .poll(async () => (await tableMetrics(page, RANGE))?.hasCut ?? false, { timeout: ms })
      .toBe(true)
    return true
  } catch {
    return false
  }
}

/** 打开单文件分析并选中第一个参数，返回抽样的参数列表 */
async function openSingleTab(page: Page): Promise<string[]> {
  await gotoApp(page, '/analysis')
  await selectAnalysisFile(page, RECOMMENDED.analysis)
  await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
  const params = await listParams(page)
  expect(params.length).toBeGreaterThan(0)
  await selectParam(page, params[0])
  await waitLoadingGone(page.locator(SINGLE))
  await expect(page.locator(`${SINGLE} .el-table__row`).first()).toBeVisible({ timeout: 15_000 })
  return params
}

test.describe('@p2 表格随缩放完整显示每一列', { tag: ['@p2', '@analysis'] }, () => {
  test('100% 与应用缩放 125% 下两表全列同屏可见（含裁剪范围最宽场景）', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    const params = await openSingleTab(page)

    // 1) 100%
    await expectNoClippedColumns(page)

    // 2) 125%：useZoom 的浏览器分支就是给 <html> 设 style.zoom（Ctrl+滚轮/`+`）
    await page.evaluate(() => { document.documentElement.style.zoom = '1.25' })
    await expectNoClippedColumns(page)

    // 3) 最宽场景：裁剪范围 → 行 label 带 " (cut)"（label 列最宽）。
    //    该后缀只在参数**确实有异常值**时出现（useFiltered = hasOutliers && 模式≠off），
    //    而哪些参数有异常值取决于数据 → 在抽样参数里找第一个带 (cut) 的。
    await pickOutlierMode(page, '裁剪范围')
    let cutCovered = (await tableMetrics(page, RANGE))?.hasCut ?? false
    for (const name of cutCovered ? [] : params) {
      await selectParam(page, name)
      await waitLoadingGone(page.locator(SINGLE))
      cutCovered = await hasCutWithin(page, 3_000)
      if (cutCovered) break
    }
    // 一个都没找到也不失败：本用例的不变量（列不裁）与 label 是否带后缀无关，
    // 只是没覆盖到最宽情况，用注解如实记录下来。
    test.info().annotations.push({
      type: 'cut-suffix',
      description: cutCovered ? '已覆盖带 (cut) 的最宽行标签' : '抽样参数均无异常值，未覆盖 (cut)',
    })
    await expectNoClippedColumns(page)
  })

  test('浏览器缩放 125%（1536 视口）下两表全列同屏可见', async ({ page }) => {
    // 浏览器 Ctrl+`+` 到 125%：1920 物理像素只剩 1536 CSS px，是同一问题的另一条路径
    await page.setViewportSize({ width: 1536, height: 864 })
    await openSingleTab(page)
    await expectNoClippedColumns(page)
  })

  test('窄视口（1024）左栏整行堆叠，页面无横向溢出', async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 900 })
    await openSingleTab(page)

    const left = (await page.locator(`${SINGLE} > .main-row > .left-panel`).boundingBox())!
    const right = (await page.locator(`${SINGLE} > .main-row > .right-panel`).boundingBox())!
    expect(right.y, '图表区应落在左栏下方（纵向堆叠）').toBeGreaterThan(left.y + left.height - 4)
    expect(left.width, '堆叠后左栏占整行').toBeGreaterThan(600)

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow, '页面不应横向溢出').toBeLessThanOrEqual(1)
    await expectNoClippedColumns(page)
  })
})
