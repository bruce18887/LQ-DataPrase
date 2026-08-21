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

function findSeriesData(option: any, name: string): any {
  const series = option?.series || []
  return series.find((s: any) => s.name === name)?.data ?? null
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

  test('KDE 曲线口径与异常值模式解耦（开关全局生效：勾选=全量 / 不勾选=剔除）', async ({ page }) => {
    const found = await findParamWithOutliers(page)
    test.skip(!found, '当前数据文件未找到含异常值的参数')

    const outlierSelect = page.locator('.el-form-item').filter({ hasText: '异常值处理' }).locator('.el-select').first()
    const kdeFullCheckbox = page.locator(`${SINGLE} .config-checkboxes .el-checkbox`).filter({ hasText: 'KDE含超限' })

    // 确保 RDL + 不处理（默认状态，KDE 默认勾选、含超限默认不勾选）
    const rangeSelect = page.locator(`${SINGLE} .config-section`).filter({ hasText: '范围类型' }).locator('.el-select').first()
    await rangeSelect.click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: 'RowDataLimit' }).first().click()
    await waitLoadingGone(page.locator(SINGLE))
    await outlierSelect.click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: '不处理' }).first().click()
    await waitLoadingGone(page.locator(SINGLE))
    await page.waitForTimeout(500)

    // off + 开关关（默认）：KDE = 剔除曲线（不含超限数据，主峰忠实）
    const kdeOffFiltered = findSeriesData(await getHistogramChartOption(page), 'KDE曲线')
    expect(kdeOffFiltered, 'off 模式应渲染 KDE 曲线').toBeTruthy()

    // off + 勾选「KDE含超限」→ 全量曲线（含超限数据）——开关全局生效的关键断言
    await kdeFullCheckbox.click()
    await expect(kdeFullCheckbox, '勾选后应为选中态').toHaveClass(/is-checked/)
    await page.waitForTimeout(500)
    const kdeOffFull = findSeriesData(await getHistogramChartOption(page), 'KDE曲线')
    expect(kdeOffFull, 'off 下勾选含超限应为全量曲线（≠ 剔除曲线）').not.toEqual(kdeOffFiltered)
    await kdeFullCheckbox.click()

    // 裁剪范围 + 开关关 → 剔除曲线，与 off 不勾选逐字节一致（与模式解耦）
    await outlierSelect.click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: '裁剪范围' }).first().click()
    await waitLoadingGone(page.locator(SINGLE))
    await page.waitForTimeout(500)
    const kdeClipFiltered = findSeriesData(await getHistogramChartOption(page), 'KDE曲线')
    expect(kdeClipFiltered, 'clip 模式应渲染 KDE 曲线').toBeTruthy()
    expect(kdeClipFiltered, 'clip 不勾选应为剔除曲线（= off 不勾选，与模式解耦）').toEqual(kdeOffFiltered)

    // 裁剪范围 + 开关开 → 全量曲线（= off 勾选）
    await kdeFullCheckbox.click()
    await expect(kdeFullCheckbox, '勾选后应为选中态').toHaveClass(/is-checked/)
    await page.waitForTimeout(500)
    const kdeClipFull = findSeriesData(await getHistogramChartOption(page), 'KDE曲线')
    expect(kdeClipFull, 'clip 下勾选含超限应为全量曲线（= off 勾选）').toEqual(kdeOffFull)

    // 清理：取消开关、恢复不处理
    await kdeFullCheckbox.click()
    await outlierSelect.click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: '不处理' }).first().click()
    await waitLoadingGone(page.locator(SINGLE))
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

  test('裁剪模式下 3σ 卡片与图表标记线使用后端 filtered_sigma 值（回归 σ 口径）', async ({ page }) => {
    const found = await findParamWithOutliers(page)
    test.skip(!found, '当前数据文件未找到含异常值的参数')

    // 切到裁剪模式（此操作不重发请求，histogramUpdateView 复用 lastResults）
    const outlierSelect = page.locator('.el-form-item').filter({ hasText: '异常值处理' }).locator('.el-select').first()
    await outlierSelect.click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: '裁剪范围' }).first().click()
    await waitLoadingGone(page.locator(SINGLE))

    // 开启 3σ 线（默认 chartConfig 只有 limit/s6/kde；点击容器而非隐藏 input）
    await page.locator('.el-checkbox', { hasText: '3σ线' }).first().click()

    // 捕获后端 histogram 响应（改范围类型触发重请求）
    let captured: any = null
    const handler = async (response: import('@playwright/test').Response) => {
      const url = response.url()
      if (!url.includes('/analysis/histogram/') || response.request().method() !== 'POST') return
      if (response.status() !== 200) return
      try {
        const body = await response.json()
        const r = body.results?.[found!.param]
        if (r?.filtered_sigma3_min != null) captured = r
      } catch {}
    }
    page.on('response', handler)

    const rangeSelect = page.locator(`${SINGLE} .config-section`).filter({ hasText: '范围类型' }).locator('.el-select').first()
    await rangeSelect.click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: 'Data Range' }).first().click()
    await waitLoadingGone(page.locator(SINGLE))
    page.off('response', handler)
    expect(captured, '应捕获到带 filtered_sigma 的 histogram 响应').not.toBeNull()
    if (!captured) return

    // 卡片 3σ 显示后端裁剪口径值（修复前前端用本地重算值，与标记线矛盾）
    const sigmaCard = page.locator(`${SINGLE} .stats-summary .stat-item`).filter({ hasText: '3σ' }).first()
    await expect(sigmaCard).toBeVisible()
    await expect(sigmaCard.locator('.stat-value')).toHaveText(
      `[${captured.filtered_sigma3_min.toFixed(4)}, ${captured.filtered_sigma3_max.toFixed(4)}]`,
    )

    // 图表标记线 3σ下限 与卡片同一组值（后端 filtered_sigma3_min）
    const option = await getHistogramChartOption(page)
    expect(option).not.toBeNull()
    const lines = option?.series?.flatMap((s: any) => s.markLine?.data || []) || []
    const s3Line = lines.find((m: any) => m.label?.formatter === '3σ下限')
    expect(s3Line, '应存在 3σ下限 标记线').toBeTruthy()
    expect(Number(s3Line.xAxis)).toBeCloseTo(captured.filtered_sigma3_min, 4)
  })

  test('切换范围类型只触发一次站点统计请求（回归 #8 重复请求）', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))

    // 选中一个参数（site_stats 需要 param 才发请求）
    const params = await listParams(page)
    expect(params.length).toBeGreaterThan(0)
    await selectParam(page, params[0])
    await waitLoadingGone(page.locator(SINGLE))

    // 只统计携带新 range_type 的请求：初始加载可能在途的旧 range_type
    // 请求即使晚到也不会被计入（精确匹配请求体，避免误计）
    let siteStatsRequests = 0
    page.on('request', (req) => {
      if (req.url().includes('/statistics/site_stats/') && req.method() === 'POST') {
        const body = req.postData() || ''
        if (body.includes('"range_type":"S3"')) siteStatsRequests++
      }
    })

    const rangeSelect = page.locator(`${SINGLE} .config-section`).filter({ hasText: '范围类型' }).locator('.el-select').first()
    await expect(rangeSelect).toBeVisible()
    await rangeSelect.click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: '3 Sigma' }).first().click()
    await waitLoadingGone(page.locator(SINGLE))
    // 给修复前 histResult watch 会带来的第二次请求留出窗口
    await page.waitForTimeout(500)

    expect(siteStatsRequests, '改范围类型应只触发一次 site_stats 请求').toBe(1)
  })

  test('QQ 图裁剪后 Y 轴锚定可见观测值区间（回归 qq-yaxis-outlier-range）', async ({ page }) => {
    const found = await findParamWithOutliers(page)
    test.skip(!found, '当前数据文件未找到含异常值的参数')

    await selectParam(page, found.param)
    await waitLoadingGone(page.locator(SINGLE))

    // 开启 QQ 图并捕获 qqplot 响应：outlier_info 与 observed_quantiles 都在响应里。
    // 切换异常值模式不重发请求（useQQPlot 只 watch 参数/过滤开关），前端用同一份
    // result 重渲染，期望值必须从开启时捕获的响应计算。
    const qqResp = page.waitForResponse(
      (r) => r.url().includes('/analysis/qqplot/') && r.request().method() === 'POST' && r.status() < 500,
      { timeout: 25_000 },
    )
    await page.getByText('显示QQ图').click()
    const body = await (await qqResp).json()
    const info = body.outlier_info
    expect(info?.has_outliers, 'qqplot 响应应携带 has_outliers').toBe(true)
    const obs: number[] = body.observed_quantiles
    const filtered = obs.filter((v: number) => v >= info.lower_bound && v <= info.upper_bound)
    expect(filtered.length, '过滤后应保留 >2 个点（否则前端不过滤、轴不 pin）').toBeGreaterThan(2)
    const fMin = Math.min(...filtered)
    const fMax = Math.max(...filtered)
    const pad = (fMax - fMin) * 0.05 || 0.5
    const fullMax = obs[obs.length - 1]
    expect(fullMax, '全量最大值应为离群点（超出上界）').toBeGreaterThan(info.upper_bound)

    // 读取 QQ 容器上 ECharts 实例的 yAxis（useChart 把实例挂在容器 DOM）
    const readYAxis = async () => {
      for (let i = 0; i < 150; i++) {
        const v = await page
          .locator(`${SINGLE} .qqplot-container`)
          .evaluate((el: any) => {
            const chart = el.__echartsInstance__
            if (!chart) return null
            const y = chart.getOption()?.yAxis?.[0]
            return { min: y?.min, max: y?.max }
          })
          .catch(() => null)
        if (v) return v
        await page.waitForTimeout(100)
      }
      return null
    }

    const outlierSelect = page.locator('.el-form-item').filter({ hasText: '异常值处理' }).locator('.el-select').first()

    // 裁剪范围：Y 轴应 pin 到过滤后观测值区间（±5% 边距），不再被全量拟合
    // 参考线撑到含离群点的范围
    await outlierSelect.click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: '裁剪范围' }).first().click()
    await waitLoadingGone(page.locator(SINGLE))
    await expect
      .poll(async () => (await readYAxis())?.min, { timeout: 15_000 })
      .not.toBeNull()
    const clipped = (await readYAxis())!
    expect(clipped.min).toBeCloseTo(fMin - pad, 4)
    expect(clipped.max).toBeCloseTo(fMax + pad, 4)
    expect(clipped.max, '裁剪后轴不应再覆盖离群点').toBeLessThan(fullMax)

    // 不处理：不 pin，轴恢复自动缩放（覆盖全量数据）
    await outlierSelect.click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: '不处理' }).first().click()
    await waitLoadingGone(page.locator(SINGLE))
    await expect
      .poll(async () => {
        const v = await readYAxis()
        return v ? typeof v.min : 'no-chart'
      }, { timeout: 15_000 })
      .toBe('undefined')
  })
})
