import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, selectParam, listParams } from '../helpers/params'
import { waitLoadingGone } from '../helpers/charts'
import { RECOMMENDED } from '../fixtures/test-data'

const SINGLE = '.single-param-tab'

interface OutlierInfo {
  has_outliers: boolean
  outlier_count: number
  lower_bound: number
  upper_bound: number
  outlier_values?: number[]
  normal_count: number
}

async function findParamWithOutliers(page: import('@playwright/test').Page): Promise<{ param: string; info: OutlierInfo } | null> {
  // Listen for histogram responses and pick the first param with outliers.
  const results: { param: string; info: OutlierInfo }[] = []
  const handler = async (response: import('@playwright/test').Response) => {
    const url = response.url()
    if (!url.includes('/analysis/histogram/') || response.request().method() !== 'POST') return
    if (response.status() !== 200) return
    try {
      const body = await response.json()
      const res = body.results as Record<string, { outlier_info: OutlierInfo }>
      for (const [param, data] of Object.entries(res || {})) {
        if (data?.outlier_info?.has_outliers) {
          results.push({ param, info: data.outlier_info })
        }
      }
    } catch {}
  }
  page.on('response', handler)

  await gotoApp(page, '/analysis')
  await selectAnalysisFile(page, RECOMMENDED.analysis)
  await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
  await waitLoadingGone(page.locator(SINGLE))

  // Try the initially loaded param first, then iterate if needed.
  const allParams = await listParams(page)
  for (const param of allParams) {
    if (results.length > 0) break
    await selectParam(page, param)
    await waitLoadingGone(page.locator(SINGLE))
    // Give the response listener a tick to populate results.
    await page.waitForTimeout(300)
  }

  page.off('response', handler)
  return results[0] || null
}

async function getHistogramChartOption(page: import('@playwright/test').Page): Promise<any | null> {
  // Poll for the ECharts instance because initEchartsWhenReady may defer
  // initialization until the container has a non-zero size.
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

function getXAxisRange(option: any) {
  const xAxis = option?.xAxis?.[0]
  if (!xAxis) return null
  return { min: xAxis.min, max: xAxis.max }
}

function hasLimitMarkLines(option: any) {
  const lines = option?.series?.flatMap((s: any) => s.markLine?.data || []) || []
  const formatters = lines.map((m: any) => m.label?.formatter)
  return formatters.includes('LSL') && formatters.includes('USL')
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

function countNonEmptyBins(option: any, lower: number, upper: number) {
  const barSeries = (option?.series || []).filter((s: any) => s.type === 'bar')
  let total = 0
  for (const s of barSeries) {
    total += (s.data || []).filter((d: any) => {
      const center = Array.isArray(d) ? d[0] : d.value?.[0]
      const value = Array.isArray(d) ? d[1] : d.value?.[1]
      return center >= lower && center <= upper && value > 0
    }).length
  }
  return total
}

test.describe('@p1 异常值处理', { tag: ['@p1', '@analysis'] }, () => {
  test('裁剪范围模式显示异常值提示条与数值列表', async ({ page }) => {
    const found = await findParamWithOutliers(page)
    test.skip(!found, '当前数据文件未找到含异常值的参数')

    const { info } = found

    // Ensure clip mode is selected.
    const outlierSelect = page.locator('.el-form-item').filter({ hasText: '异常值处理' }).locator('.el-select').first()
    await outlierSelect.click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: '裁剪范围' }).first().click()
    await waitLoadingGone(page.locator(SINGLE))

    // Hint bar should be visible and describe the outlier count and bounds.
    const hintBar = page.locator(`${SINGLE} .outlier-hint-bar`)
    await expect(hintBar).toBeVisible({ timeout: 10_000 })
    const hintText = await hintBar.textContent()
    expect(hintText).toContain('已裁剪')
    expect(hintText).toContain(`${info.outlier_count} 个异常值`)
    expect(hintText).toContain(info.lower_bound.toFixed(4))
    expect(hintText).toContain(info.upper_bound.toFixed(4))

    // Hovering the hint bar should reveal the tooltip with the actual values.
    await hintBar.hover()
    const tooltip = page.locator('.el-popper.is-light:visible, .el-popper.is-dark:visible').last()
    await expect(tooltip).toBeVisible({ timeout: 5_000 })
    const tooltipText = await tooltip.textContent()
    expect(tooltipText).toContain('异常值列表')
    expect(tooltipText).toContain(`共 ${info.outlier_count} 个`)
    // The first outlier value should appear in the tooltip.
    if (info.outlier_values && info.outlier_values.length > 0) {
      expect(tooltipText).toContain(info.outlier_values[0].toFixed(4))
    }
  })

  test('切换异常值处理模式控制提示条显隐', async ({ page }) => {
    const found = await findParamWithOutliers(page)
    test.skip(!found, '当前数据文件未找到含异常值的参数')

    const outlierSelect = page.locator('.el-form-item').filter({ hasText: '异常值处理' }).locator('.el-select').first()

    // 默认状态为「不处理」，提示条应不可见。
    await expect(page.locator(`${SINGLE} .outlier-hint-bar`)).not.toBeVisible()

    // Switch to "裁剪范围" → 提示条出现。
    await outlierSelect.click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: '裁剪范围' }).first().click()
    await waitLoadingGone(page.locator(SINGLE))
    await expect(page.locator(`${SINGLE} .outlier-hint-bar`)).toBeVisible({ timeout: 10_000 })

    // Switch back to "不处理" → 提示条消失。
    await outlierSelect.click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: '不处理' }).first().click()
    await waitLoadingGone(page.locator(SINGLE))
    await expect(page.locator(`${SINGLE} .outlier-hint-bar`)).not.toBeVisible()
  })

  test('RowDataLimit 下裁剪不缩小 X 轴范围且保留 Limit 线', async ({ page }) => {
    const found = await findParamWithOutliers(page)
    test.skip(!found, '当前数据文件未找到含异常值的参数')

    const outlierSelect = page.locator('.el-form-item').filter({ hasText: '异常值处理' }).locator('.el-select').first()
    const rangeSelect = page.locator(`${SINGLE} .config-section`).filter({ hasText: '范围类型' }).locator('.el-select').first()

    // Ensure we are in RDL mode for this assertion.
    await rangeSelect.click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: 'RowDataLimit' }).first().click()
    await waitLoadingGone(page.locator(SINGLE))

    // 1) Switch to "不处理" and record the baseline chart option.
    await outlierSelect.click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: '不处理' }).first().click()
    await waitLoadingGone(page.locator(SINGLE))
    await page.waitForTimeout(500)

    const baselineOption = await getHistogramChartOption(page)
    expect(baselineOption, '应能获取基准图表配置').not.toBeNull()
    const baselineRange = getXAxisRange(baselineOption)
    expect(baselineRange, '应能读取基准 X 轴范围').not.toBeNull()

    // 2) Switch back to "裁剪范围".
    await outlierSelect.click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: '裁剪范围' }).first().click()
    await waitLoadingGone(page.locator(SINGLE))
    await page.waitForTimeout(500)

    const clippedOption = await getHistogramChartOption(page)
    expect(clippedOption, '应能获取裁剪后图表配置').not.toBeNull()
    const clippedRange = getXAxisRange(clippedOption)
    expect(clippedRange, '应能读取裁剪后 X 轴范围').not.toBeNull()

    // X-axis range should remain unchanged.
    expect(clippedRange!.min).toBeCloseTo(baselineRange!.min, 3)
    expect(clippedRange!.max).toBeCloseTo(baselineRange!.max, 3)

    // Limit lines should still be present.
    expect(hasLimitMarkLines(clippedOption), '裁剪后应保留 LSL/USL 线').toBe(true)

    // In RDL mode, bins inside the original Limit lines must not be hidden.
    const { lower, upper } = extractLimitLines(clippedOption)
    expect(lower, '应能读取 LSL').not.toBeNull()
    expect(upper, '应能读取 USL').not.toBeNull()
    const baselineNonEmpty = countNonEmptyBins(baselineOption, lower!, upper!)
    const clippedNonEmpty = countNonEmptyBins(clippedOption, lower!, upper!)
    expect(clippedNonEmpty, 'RDL 裁剪后 Limit 线内非空 bin 不应减少').toBeGreaterThanOrEqual(baselineNonEmpty)
  })
})
