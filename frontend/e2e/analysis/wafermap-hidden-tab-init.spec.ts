import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile } from '../helpers/params'

/**
 * 回归：晶圆图「点击加载后无显示」——隐藏 tab 容器下的僵尸 init handle。
 *
 * 根因：WaferMapPanel 挂在非 lazy 的 el-tab-pane 里（未激活时 display:none、
 * 零尺寸）。useChart 首次 ensureInit 时 initEchartsWhenReady 因容器无尺寸
 * 进入等待，5s 超时后其内部 ResizeObserver/轮询被永久断开（handle.chart
 * 永远为 null = 僵尸 handle）。用户停留其他 tab 超过 5s 再打开晶圆图：
 * 容器已可见，但 ensureInit 被僵尸 handle 短路（`if (handle) return true`）、
 * renderOption 因 chartInstance 为空静默空转——统计卡片出现，图表区永久空白。
 *
 * 修复：ensureInit 遇到 handle.chart 为 null 的僵尸 handle 时 dispose 重建。
 * 本用例：停留 >5s 超时窗口 → 打开晶圆图 → 加载 → 断言图表实例与散点真实渲染。
 */

const FILE_SUBSTR = 'BN281R3CYCAA'
// initEchartsWhenReady 的等待超时是 5s，停留必须超过该窗口才会制造僵尸 handle
const STAY_DURATION_MS = 7_000

test('隐藏 tab 超时后打开晶圆图并加载：图表必须真实渲染散点', {
  tag: ['@p1', '@analysis'],
}, async ({ page }) => {
  await gotoApp(page, '/analysis')
  await selectAnalysisFile(page, FILE_SUBSTR)
  const loadBtn = page.locator('button').filter({ hasText: '加载晶圆图' })
  await expect(loadBtn).toBeEnabled({ timeout: 120_000 })

  // 关键步骤：停留在默认 tab 超过 init 超时窗口，模拟真实用户（先看别的 tab）
  await page.waitForTimeout(STAY_DURATION_MS)
  await page.getByRole('tab', { name: /晶圆图/ }).click()

  const panel = page.getByRole('tabpanel', { name: /晶圆图/ })
  const chart = panel.locator('div[_echarts_instance_]').first()
  // 修复前：容器可见但 ECharts 从未初始化（僵尸 handle），该 div 不存在
  await expect(chart).toHaveCount(1, { timeout: 15_000 })

  const respPromise = page.waitForResponse(
    (r) => r.url().includes('/analysis/wafer_map/') && r.request().method() === 'POST',
    { timeout: 180_000 },
  )
  await loadBtn.click()
  expect((await respPromise).status()).toBe(200)

  // 数据已返回：统计卡片出现
  await expect(panel.getByText('Total Dies')).toBeVisible({ timeout: 30_000 })

  // 图表实例必须持有数据系列（修复前 series 为空、图表空白）
  const seriesInfo = await chart.evaluate((el: any) => {
    const chart = el.__echartsInstance__
    if (!chart) return { inited: false }
    const opt = chart.getOption()
    return {
      inited: true,
      series: opt.series?.map((s: any) => ({ name: s.name, count: s.data?.length ?? 0 })) ?? [],
    }
  })
  expect(seriesInfo.inited, '图表应已初始化').toBe(true)
  const pass = seriesInfo.series?.find((s: any) => s.name === 'Pass')
  expect(pass?.count ?? 0, 'Pass 散点应已渲染').toBeGreaterThan(0)
  const fail = seriesInfo.series?.find((s: any) => s.name === 'Fail')
  expect(fail?.count ?? 0, 'Fail 散点应已渲染').toBeGreaterThan(0)
})
