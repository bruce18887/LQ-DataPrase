import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { expectChartRendered, waitLoadingGone } from '../helpers/charts'
import { selectAnalysisFile } from '../helpers/params'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * dock 面板缩放回归（2026-09-06）：
 *  - 底部横条改整体高度 → 直方图/序列/QQ/箱线 4 张图都随面板变高缩放（不再固定/塌陷）。
 *  - 行间自定义拖拽条改两行占比 → 上/下行此消彼长。
 * 行不再用 el-splitter（它把行尺寸一次性锁成 px、容器变高不重算），改自定义 % 行。
 * 度量用面板整体高度（.chart-panel），最稳、不受 ECharts 内部 svg/canvas 层级影响。
 */

const SINGLE = '.single-param-tab'

async function panelHeight(page: import('@playwright/test').Page, key: string): Promise<number> {
  const panel = page.locator(`.chart-panel[data-chart-key="${key}"]`)
  return (await panel.boundingBox())?.height ?? 0
}

function toggle(page: import('@playwright/test').Page, label: string) {
  return page.locator(`${SINGLE} .chart-toggles .el-checkbox`).filter({ hasText: label })
}

async function enterAll(page: import('@playwright/test').Page) {
  await gotoApp(page, '/analysis')
  await selectAnalysisFile(page, RECOMMENDED.analysis)
  await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
  await waitLoadingGone(page.locator(SINGLE))
  await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)
  for (const label of ['显示序列分布', '显示QQ图', '显示箱线图']) {
    await toggle(page, label).click()
  }
  for (const k of ['serial', 'qq', 'box']) {
    await expect(page.locator(`.chart-panel[data-chart-key="${k}"]`)).toBeVisible({ timeout: 20_000 })
  }
}

test.describe('@p1 dock 面板缩放自适应', { tag: ['@p1', '@analysis'] }, () => {
  test('底部横条撑高 → 直方图/序列/QQ/箱线 4 图都跟随缩放', async ({ page }) => {
    await enterAll(page)
    const bar = page.locator('.chart-dock__resize').first()
    await expect(bar).toBeVisible({ timeout: 5_000 })
    await bar.scrollIntoViewIfNeeded()
    await page.waitForTimeout(400)

    // 先拖到很矮（基线小），再大幅撑高 → 4 图面板都显著变高
    let b = (await bar.boundingBox())!
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2)
    await page.mouse.down()
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2 - 260, { steps: 10 })
    await page.mouse.up()
    await page.waitForTimeout(400)
    const before = {
      hist: await panelHeight(page, 'hist'),
      serial: await panelHeight(page, 'serial'),
      qq: await panelHeight(page, 'qq'),
      box: await panelHeight(page, 'box'),
    }

    b = (await (page.locator('.chart-dock__resize').first()).boundingBox())!
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2)
    await page.mouse.down()
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2 + 600, { steps: 15 })
    await page.mouse.up()

    for (const key of ['hist', 'serial', 'qq', 'box'] as const) {
      await expect
        .poll(async () => await panelHeight(page, key), { timeout: 8_000, message: `${key} 面板应随 dock 撑高变高` })
        .toBeGreaterThan(before[key] + 40)
    }
  })
})
