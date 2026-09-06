import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { expectChartRendered, waitLoadingGone } from '../helpers/charts'
import { selectAnalysisFile } from '../helpers/params'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * dock 图表面板缩放回归（2026-09-06）：
 *  req1：容器尺寸变化后，序列图应与直方图一样重排（画布跟随）——证明两图 resize 一致。
 *  本轮两 bug：
 *   - 序列图固定 grid.bottom=150 把 X 轴挤没/被遮 → 现随容器高自适应。
 *   - QQ 图 Y 轴缩放条初始算成窄条、resize 不更新 → 现随容器高重算、与绘图区等长。
 * 直接改面板容器高度（等价于拖分隔条最终产生的容器尺寸变化），比对 ECharts option。
 */

const SINGLE = '.single-param-tab'

async function plotHeight(page: import('@playwright/test').Page, key: string): Promise<number> {
  const panel = page.locator(`.chart-panel[data-chart-key="${key}"]`)
  const canvas = panel.locator('canvas')
  const target = (await canvas.count()) > 0 ? canvas.first() : panel.locator('svg').first()
  return (await target.boundingBox())?.height ?? 0
}

/** 把某面板的 ECharts 宿主容器设为固定高度（触发 ResizeObserver → resize + 布局重算） */
async function setPanelHeight(page: import('@playwright/test').Page, key: string, h: number) {
  await page.evaluate(({ key, h }) => {
    const el = document.querySelector(`.chart-panel[data-chart-key="${key}"] .chart-b`) as HTMLElement | null
    if (el) { el.style.height = `${h}px`; el.style.flex = '0 0 auto' }
  }, { key, h })
}

/** 读取某面板 ECharts 实例 option 的指定值（遍历面板找真正挂了 __echartsInstance__ 的元素） */
async function readOption(page: import('@playwright/test').Page, key: string, pick: string): Promise<number> {
  return page.evaluate(({ key, pick }) => {
    const panel = document.querySelector(`.chart-panel[data-chart-key="${key}"]`)
    if (!panel) return -1
    let inst: any = null
    for (const el of [panel, ...Array.from(panel.querySelectorAll('*'))]) {
      const c = (el as any).__echartsInstance__
      if (c) { inst = c; break }
    }
    if (!inst) return -1
    const o = inst.getOption()
    if (pick === 'qqSliderBottom') return (o.dataZoom?.[0]?.bottom ?? -1) as number
    if (pick === 'qqGridBottom') return (o.grid?.[0]?.bottom ?? -1) as number
    return -2
  }, { key, pick })
}

function toggle(page: import('@playwright/test').Page, label: string) {
  return page.locator(`${SINGLE} .chart-toggles .el-checkbox`).filter({ hasText: label })
}

async function enterWith(page: import('@playwright/test').Page, serial: boolean, qq: boolean) {
  await gotoApp(page, '/analysis')
  await selectAnalysisFile(page, RECOMMENDED.analysis)
  await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
  await waitLoadingGone(page.locator(SINGLE))
  await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)
  if (serial) await toggle(page, '显示序列分布').click()
  if (qq) await toggle(page, '显示QQ图').click()
}

test.describe('@p1 dock 面板缩放自适应', { tag: ['@p1', '@analysis'] }, () => {
  test('req1：序列图与直方图都随容器变高而重排', async ({ page }) => {
    await enterWith(page, true, false)
    await expect(page.locator('.chart-panel[data-chart-key="serial"]')).toBeVisible({ timeout: 20_000 })
    await expectChartRendered(page.locator('.chart-panel[data-chart-key="serial"]'), 0)

    // 先压到 200 建立明确基线，再撑到 620 → 两图都应有显著增长（避免默认高度贴边 flaky）
    await setPanelHeight(page, 'hist', 200)
    await setPanelHeight(page, 'serial', 200)
    await page.waitForTimeout(300)
    const histBefore = await plotHeight(page, 'hist')
    const serialBefore = await plotHeight(page, 'serial')
    expect(histBefore).toBeGreaterThan(40)
    expect(serialBefore).toBeGreaterThan(40)

    await setPanelHeight(page, 'hist', 620)
    await setPanelHeight(page, 'serial', 620)

    await expect
      .poll(async () => await plotHeight(page, 'hist'), { timeout: 8_000, message: '直方图应随容器变高重排' })
      .toBeGreaterThan(histBefore + 60)
    await expect
      .poll(async () => await plotHeight(page, 'serial'), { timeout: 8_000, message: '序列图应随容器变高重排' })
      .toBeGreaterThan(serialBefore + 60)
  })

  test('QQ 图 Y 轴缩放条与 grid 同源锚定（top/bottom 对齐 → 随面板变高自动撑满）', async ({ page }) => {
    await enterWith(page, false, true)
    await expect(page.locator('.chart-panel[data-chart-key="qq"]')).toBeVisible({ timeout: 20_000 })
    await expectChartRendered(page.locator('.chart-panel[data-chart-key="qq"]'), 0)

    // 滑块 bottom 必须等于 grid bottom（=40）：这样 ECharts resize() 会按容器高
    // 自动重算滑块长度，面板变高时滑块始终与 Y 轴等长（旧实现用固定 height 会脱节）
    await setPanelHeight(page, 'qq', 520)
    await expect
      .poll(async () => await readOption(page, 'qq', 'qqSliderBottom'), { timeout: 8_000 })
      .toBe(40)
    const gridBottom = await readOption(page, 'qq', 'qqGridBottom')
    expect(gridBottom, '滑块底部应与 grid 底部同源（随轴变长）').toBe(40)
  })
})
