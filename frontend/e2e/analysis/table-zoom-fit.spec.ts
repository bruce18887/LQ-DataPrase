import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, listParams, selectParam } from '../helpers/params'
import { waitLoadingGone } from '../helpers/charts'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 回归：Ctrl+滚轮页面缩放后，「📊 范围对比」「📱 Site统计」表格必须能完整查看每一列。
 *
 * 行为约定（修复后）：
 * - 表格内容超过容器宽度时（内容本身较宽，或页面放大后容器变窄），
 *   表格内部出现常显横向滚动条（scrollbar-always-on）；
 * - 滚动到末尾后最后一列表头完整落在表格可视区域内 —— 任何缩放级别下每一列都可达。
 */
const SINGLE = '.single-param-tab'
const VIEWPORT = { width: 1920, height: 1080 }
const TABLES = [
  { title: '📊 范围对比', lastHeader: 'Unit' },
  { title: '📱 Site统计', lastHeader: '>Max' },
]

/** 通过真实的 Ctrl+滚轮事件放大页面 steps 步（每步 0.1） */
async function zoomInBy(page: import('@playwright/test').Page, steps: number) {
  for (let i = 0; i < steps; i++) {
    await page.evaluate(() => {
      const event = new WheelEvent('wheel', { deltaY: -100, ctrlKey: true, bubbles: true })
      window.dispatchEvent(event)
    })
  }
  await expect
    .poll(() => page.evaluate(() => parseFloat(document.documentElement.style.zoom || '1')))
    .toBeGreaterThanOrEqual(1 + steps * 0.1)
}

/** 读取表格内部可横向滚动容器的尺寸（优先 el-scrollbar，回退 body-wrapper） */
function scrollMetrics(page: import('@playwright/test').Page, title: string) {
  return page.evaluate((t) => {
    const card = [...document.querySelectorAll<HTMLElement>('.el-card')].find((c) =>
      c.textContent?.includes(t),
    )
    const table = card?.querySelector<HTMLElement>('.el-table')
    if (!table) return null
    const wrap =
      table.querySelector<HTMLElement>('.el-scrollbar__wrap') ??
      table.querySelector<HTMLElement>('.el-table__body-wrapper')
    if (!wrap) return null
    return {
      wrapClientWidth: wrap.clientWidth,
      wrapScrollWidth: wrap.scrollWidth,
    }
  }, title)
}

/** 滚动表格到最右并返回最后一列表头的可视边界 */
function scrollToLastColumn(page: import('@playwright/test').Page, title: string) {
  return page.evaluate((t) => {
    const card = [...document.querySelectorAll<HTMLElement>('.el-card')].find((c) =>
      c.textContent?.includes(t),
    )
    const table = card?.querySelector<HTMLElement>('.el-table')
    if (!table) return null
    const wrap =
      table.querySelector<HTMLElement>('.el-scrollbar__wrap') ??
      table.querySelector<HTMLElement>('.el-table__body-wrapper')
    if (!wrap) return null
    wrap.scrollLeft = wrap.scrollWidth
    const ths = [...table.querySelectorAll<HTMLElement>('th')]
    const last = ths[ths.length - 1]
    if (!last) return null
    const tRect = table.getBoundingClientRect()
    const lRect = last.getBoundingClientRect()
    return {
      tableLeft: tRect.left,
      tableRight: tRect.right,
      lastLeft: lRect.left,
      lastRight: lRect.right,
      scrollLeft: wrap.scrollLeft,
    }
  }, title)
}

/** 表格内横向滚动条（el-scrollbar bar）是否存在且有实际宽度 */
function horizontalBarWidth(page: import('@playwright/test').Page, title: string) {
  return page.evaluate((t) => {
    const card = [...document.querySelectorAll<HTMLElement>('.el-card')].find((c) =>
      c.textContent?.includes(t),
    )
    const bar = card?.querySelector<HTMLElement>('.el-scrollbar__bar.is-horizontal .el-scrollbar__thumb')
    return bar ? bar.getBoundingClientRect().width : 0
  }, title)
}

/** 断言：滚动表格到末尾后，最后一列表头完整落在表格可视区域内 */
async function expectLastColumnReachable(
  page: import('@playwright/test').Page,
  title: string,
  lastHeader: string,
) {
  const box = await scrollToLastColumn(page, title)
  expect(box, `${title} 应存在内部横向滚动容器`).not.toBeNull()
  expect(box!.lastRight, `${title} 最后一列右缘不超出表格`).toBeLessThanOrEqual(box!.tableRight + 1)
  expect(box!.lastLeft, `${title} 最后一列左缘不早于表格左缘`).toBeGreaterThanOrEqual(box!.tableLeft - 1)
  await expect(page.locator(SINGLE).getByText(lastHeader).last()).toBeVisible()
}

test.describe('@p2 表格随缩放完整显示每一列', { tag: ['@p2', '@analysis'] }, () => {
  test('zoom 1.0 与 zoom 2.0 下均可滚动到最后一列，滚动条可见', async ({ page }) => {
    await page.setViewportSize(VIEWPORT)
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })

    const params = await listParams(page)
    expect(params.length).toBeGreaterThan(0)
    await selectParam(page, params[0])
    await waitLoadingGone(page.locator(SINGLE))

    // 左面板两个表格渲染出数据行
    for (const { title } of TABLES) {
      await expect(page.locator(SINGLE).getByText(title)).toBeVisible()
    }
    await expect(page.locator(SINGLE).locator('.el-table__row').first()).toBeVisible({
      timeout: 15_000,
    })

    // 1) zoom 1.0（1920 视口）：每一列都可通过表格内部横向滚动完整查看
    for (const { title, lastHeader } of TABLES) {
      await expectLastColumnReachable(page, title, lastHeader)
    }

    // 2) 放大到 2.0：容器变窄导致横向溢出扩大，滚动范围 > 1px
    await zoomInBy(page, 10)
    for (const { title } of TABLES) {
      await expect
        .poll(async () => {
          const m = await scrollMetrics(page, title)
          return m ? m.wrapScrollWidth - m.wrapClientWidth : null
        })
        .toBeGreaterThan(1)
    }

    // 3) zoom 2.0 下横向滚动条常显（scrollbar-always-on），且每一列仍可完整查看
    for (const { title, lastHeader } of TABLES) {
      await expect
        .poll(() => horizontalBarWidth(page, title), { message: `${title} 横向滚动条应可见` })
        .toBeGreaterThan(0)
      await expectLastColumnReachable(page, title, lastHeader)
    }
  })
})
