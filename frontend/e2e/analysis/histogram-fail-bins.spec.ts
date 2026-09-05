import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, selectParam, pickOutlierMode } from '../helpers/params'
import { waitLoadingGone } from '../helpers/charts'
import { SEEDED_FILES } from '../fixtures/test-data'

const SINGLE = '.single-param-tab'
async function getHistogramChartOption(page: import('@playwright/test').Page): Promise<any | null> {
  for (let i = 0; i < 50; i++) {
    const option = await page.evaluate((selector) => {
      const dom = document.querySelector(`${selector} .chart-container`)
      if (!dom) return null
      const chart = (dom as any).__echartsInstance__
      if (!chart) return null
      return chart.getOption()
    }, SINGLE)
    if (option) return option
    await page.waitForTimeout(100)
  }
  return null
}

function extractBarData(series: any): { center: number; value: number; hasCustomStyle?: boolean }[] {
  return (series.data || []).map((d: any) => {
    if (Array.isArray(d)) {
      return { center: d[0], value: d[1] }
    }
    return {
      center: d.value?.[0] ?? 0,
      value: d.value?.[1] ?? 0,
      hasCustomStyle: !!d.itemStyle,
    }
  })
}

function extractLimitLines(option: any): { lower: number | null; upper: number | null } {
  const lines = option?.series?.flatMap((s: any) => s.markLine?.data || []) || []
  let lower: number | null = null
  let upper: number | null = null
  for (const line of lines) {
    if (line.label?.formatter === 'LSL' && line.xAxis != null) lower = Number(line.xAxis)
    if (line.label?.formatter === 'USL' && line.xAxis != null) upper = Number(line.xAxis)
  }
  return { lower, upper }
}

test.describe('@p1 柱状图 Fail Bin 可视化', { tag: ['@p1', '@analysis'] }, () => {
  test('RDL 模式下超出 Limit 的 bin 保持原始 series 颜色', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, SEEDED_FILES.STS8200_CP)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))

    // Ensure Igss_3V is selected; if the file auto-loads another first param,
    // explicitly switch to Igss_3V.
    const paramSelectWrapper = page.locator('.param-selector .el-select')
    const currentParam = await paramSelectWrapper.locator('.el-select__placeholder').textContent()
    if (!currentParam?.includes('Igss_3V')) {
      await selectParam(page, 'Igss_3V')
      await waitLoadingGone(page.locator(SINGLE))
    }
    // Fail bins are only visible when outlier handling is disabled.
    await pickOutlierMode(page, '不处理')
    await waitLoadingGone(page.locator(SINGLE))

    // Wait for the chart to render the target param.
    await expect(page.locator(`${SINGLE} .chart-container`)).toBeVisible({ timeout: 10_000 })
    await page.waitForTimeout(500)

    const option = await getHistogramChartOption(page)
    expect(option, '应能获取柱状图配置').not.toBeNull()

    const { lower, upper } = extractLimitLines(option)
    expect(lower, '应能读取 LSL').not.toBeNull()
    expect(upper, '应能读取 USL').not.toBeNull()

    const barSeries = (option.series || []).filter((s: any) => s.type === 'bar')
    expect(barSeries.length, '应至少存在一个 bar series').toBeGreaterThan(0)

    // Fail bins should not have any per-bar itemStyle override; they keep the
    // original series color so they match the legend.
    let failBinCount = 0
    for (const s of barSeries) {
      const bars = extractBarData(s)
      for (const bar of bars) {
        if (bar.value > 0 && (bar.center < lower! || bar.center > upper!)) {
          failBinCount++
          expect(bar.hasCustomStyle, `fail bin (center=${bar.center}) 不应有自定义 itemStyle`).toBeFalsy()
        }
      }
    }
    expect(failBinCount, '应存在超出 Limit 的非空 fail bin').toBeGreaterThan(0)
  })
})
