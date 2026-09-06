import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { expectChartRendered, waitLoadingGone } from '../helpers/charts'
import { selectAnalysisFile } from '../helpers/params'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * req1 回归：dock 图表面板容器尺寸变化后，序列分布图应与直方图一样真正重排（画布跟随）。
 *
 * 根因（2026-09-06）：useChart 的 ResizeObserver 曾在每帧 resize 的同时跑全量
 * setOption(notMerge)，序列图 20 万点重建卡住 → 看似「不缩放」。修成纯尺寸变化
 * 只 resize() 后，所有 dock 图共用同一 resize 路径。本用例直方图在上、序列在下，
 * 把两张图的容器撑高（等价于拖分隔条改容器尺寸），断言两图绘制区高度都随之增长。
 */

const SINGLE = '.single-param-tab'

/** 取某面板的绘图元素（渲染器无关：canvas 优先、回退 svg），返回其高度（CSS px） */
async function plotHeight(page: import('@playwright/test').Page, key: string): Promise<number> {
  const panel = page.locator(`.chart-panel[data-chart-key="${key}"]`)
  const canvas = panel.locator('canvas')
  const target = (await canvas.count()) > 0 ? canvas.first() : panel.locator('svg').first()
  const box = await target.boundingBox()
  return box?.height ?? 0
}

/**
 * 直接把某面板容器（.chart-b，即 ECharts 画布宿主）设为固定高度，触发 useChart 的
 * ResizeObserver → resize()。这正是拖分隔条最终产生的效果（改容器尺寸），但比模拟
 * el-splitter 的 window-mousemove 拖拽可靠。返回改前高度、改后即生效。
 */
async function setPanelHeight(page: import('@playwright/test').Page, key: string, h: number) {
  await page.evaluate(({ key, h }) => {
    const panel = document.querySelector(`.chart-panel[data-chart-key="${key}"] .chart-b`) as HTMLElement | null
    if (panel) { panel.style.height = `${h}px`; panel.style.flex = '0 0 auto' }
  }, { key, h })
}

function serialCheckbox(page: import('@playwright/test').Page) {
  return page.locator(`${SINGLE} .chart-toggles .el-checkbox`).filter({ hasText: '显示序列分布' })
}

test.describe('@p1 dock 分隔条缩放', { tag: ['@p1', '@analysis'] }, () => {
  test('拖动分隔条后序列图与直方图 canvas 同步重排', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)

    // 打开序列分布 → dock 变两行（直方图在上、序列在下），中间出现横向分隔条
    await serialCheckbox(page).click()
    await expect(page.locator('.chart-panel[data-chart-key="serial"]')).toBeVisible({ timeout: 20_000 })
    await expectChartRendered(page.locator('.chart-panel[data-chart-key="serial"]'), 0)

    const histBefore = await plotHeight(page, 'hist')
    const serialBefore = await plotHeight(page, 'serial')
    expect(histBefore, '前置：直方图绘图元素有高度').toBeGreaterThan(80)
    expect(serialBefore, '前置：序列图绘图元素有高度').toBeGreaterThan(80)

    // 直方图(SVG)与序列图(canvas)都必须随容器尺寸变化重排。把两张 .chart-b 容器
    // 撑到 520px（模拟拖大），useChart 的 ResizeObserver 应 resize() 让画布跟随。
    await setPanelHeight(page, 'hist', 520)
    await setPanelHeight(page, 'serial', 520)

    await expect
      .poll(async () => await plotHeight(page, 'hist'), { timeout: 8_000, message: '直方图应随容器变高而重排' })
      .toBeGreaterThan(histBefore + 40)
    await expect
      .poll(async () => await plotHeight(page, 'serial'), { timeout: 8_000, message: '序列图应随容器变高而重排（req1：与直方图一致）' })
      .toBeGreaterThan(serialBefore + 40)
  })
})
