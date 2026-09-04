import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { expectChartRendered, waitLoadingGone } from '../helpers/charts'
import { selectAnalysisFile, listParams } from '../helpers/params'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 图表配置「数据筛选」开关（忽略无Limit / 仅用Pass数据 / 仅显示Fail测试项 / 仅显示低CPK项 / 忽略无测试值）。
 *
 * 需求：
 *   - 开关切换后，参数列表（快路径）与直方图/序列分布请求都携带对应字段；
 *   - 筛选测试项的开关会收缩参数下拉列表；
 *   - 无 Bin 列或全 Pass 文件下 data_only_bin1 不影响列表。
 *
 * 竞态防护（lessons.md）：
 *   - waitForResponse 一律按请求体字段过滤（data_only_bin1 / only_fail_test_item 等），
 *     防 onFileChange 瘦请求与旧响应覆盖；
 *   - el-checkbox 用 role=checkbox + name 定位，避开 Element Plus 内部结构。
 */

const SINGLE = '.single-param-tab'

/** 点击数据筛选区的开关（el-checkbox 的 input 是视觉隐藏元素，需点击根容器） */
async function toggleFilter(page: import('@playwright/test').Page, name: string) {
  await page.locator('.filter-section .el-checkbox').filter({ hasText: name }).first().click()
}

function histogramReqWith(...fragments: string[]) {
  return (r: { url(): string; request(): { method(): string; postData(): string | null }; status(): number }) =>
    r.url().includes('/analysis/histogram/') &&
    r.request().method() === 'POST' &&
    r.request().postData()?.includes('"params":') === true &&
    fragments.every((f) => r.request().postData()?.includes(f) === true) &&
    r.status() < 500
}

test.describe('@p1 图表配置数据筛选开关', { tag: ['@p1', '@analysis'] }, () => {
  test('仅用Pass数据(Bin1)：直方图与参数列表请求都携带开关且图表正常渲染', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)

    const respPromise = page.waitForResponse(histogramReqWith('"data_only_bin1":true'), { timeout: 20_000 })
    await toggleFilter(page, '仅用Pass数据(Bin1)')
    const resp = await respPromise
    expect(resp.request().postData() || '', '直方图请求应携带 data_only_bin1').toContain('"data_only_bin1":true')
    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)

    // 参数列表刷新请求同样携带开关（快路径，body 无 params 字段）
    const fastResp = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/histogram/') &&
        r.request().method() === 'POST' &&
        r.request().postData()?.includes('"data_only_bin1":true') === true &&
        r.request().postData()?.includes('"params":') === false &&
        r.status() < 500,
      { timeout: 20_000 },
    )
    // 再切回再勾选，确保捕获到列表刷新请求
    await toggleFilter(page, '仅用Pass数据(Bin1)')
    await toggleFilter(page, '仅用Pass数据(Bin1)')
    const fast = await fastResp
    expect(fast.request().postData() || '', '参数列表请求应携带 data_only_bin1').toContain('"data_only_bin1":true')
    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)
  })

  test('仅显示Fail测试项 / 仅显示低CPK项：参数列表收缩且请求携带开关', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))

    const allParams = await listParams(page)
    expect(allParams.length).toBeGreaterThan(1)

    // 仅显示 Fail 测试项
    // 参数下拉列表来自**快路径**响应（body 不含 "params"），而计算路径响应
    // （含 "params"）只驱动图表。旧写法只等计算路径就去读下拉，而两个请求的
    // 到达顺序不保证 → 偶发读到刷新前的全量列表（实测隔离连跑 3 次：1 绿 2 红）。
    // 后端本身是对的：同一文件同口径实测 numeric_cols=180、fail_items=80、
    // filter_test_items(only_fail_test_item=True) → 80。
    // 修法：两个响应都注册在触发动作**之前**（R2①），并用条件轮询代替
    // 「等一次就读」的固定时序（condition-based waiting）。
    const fastFailResp = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/histogram/') &&
        r.request().method() === 'POST' &&
        r.request().postData()?.includes('"only_fail_test_item":true') === true &&
        r.request().postData()?.includes('"params":') === false &&
        r.status() < 500,
      { timeout: 20_000 },
    )
    const failResp = page.waitForResponse(histogramReqWith('"only_fail_test_item":true'), { timeout: 20_000 })
    await toggleFilter(page, '仅显示Fail测试项')
    const fr = await failResp
    expect(fr.request().postData() || '').toContain('"only_fail_test_item":true')
    const fastFr = await fastFailResp
    expect(fastFr.request().postData() || '', '参数列表刷新请求应携带 only_fail_test_item')
      .toContain('"only_fail_test_item":true')
    await waitLoadingGone(page.locator(SINGLE))
    await expect
      .poll(async () => (await listParams(page)).length, {
        timeout: 15_000,
        message: 'Fail 项应少于全量参数（下拉列表应已按快路径响应刷新）',
      })
      .toBeLessThan(allParams.length)
    const failParams = await listParams(page)
    expect(failParams.length, 'Fail 项列表不应为空').toBeGreaterThan(0)

    // 叠加仅显示低 CPK 项（Fail∩低CPK，可能为空集——允许为空但请求必须正确）
    const cpkResp = page.waitForResponse(histogramReqWith('"only_low_cpk":true'), { timeout: 20_000 })
    await toggleFilter(page, '仅显示低CPK项')
    const cr = await cpkResp
    expect(cr.request().postData() || '').toContain('"only_low_cpk":true')
    await waitLoadingGone(page.locator(SINGLE))
    const cpkParams = await listParams(page)
    expect(cpkParams.length).toBeLessThanOrEqual(failParams.length)
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)
  })

  test('忽略无测试值：请求携带开关且界面无错误', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))

    const respPromise = page.waitForResponse(histogramReqWith('"ignore_no_test_value":true'), { timeout: 20_000 })
    await toggleFilter(page, '忽略无测试值')
    const resp = await respPromise
    expect(resp.request().postData() || '').toContain('"ignore_no_test_value":true')
    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)
    const params = await listParams(page)
    expect(params.length).toBeGreaterThan(0)
  })

  test('序列分布模式：勾选仅用Pass数据后序列图按过滤数据重新加载', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))

    // 切到序列分布（el-radio-button 的 input 同样隐藏，点击按钮容器）
    await page.locator('.el-radio-button').filter({ hasText: '序列分布' }).first().click()
    await waitLoadingGone(page.locator(SINGLE))

    const respPromise = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/serial_distribution/') &&
        r.request().method() === 'POST' &&
        r.request().postData()?.includes('"data_only_bin1":true') === true &&
        r.status() < 500,
      { timeout: 20_000 },
    )
    await toggleFilter(page, '仅用Pass数据(Bin1)')
    const resp = await respPromise
    expect(resp.request().postData() || '', '序列分布请求应携带 data_only_bin1').toContain('"data_only_bin1":true')
    await waitLoadingGone(page.locator(SINGLE))
  })

  test('数值分布：勾选仅用Pass数据后 QQ 图请求携带开关且图表正常渲染', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))

    // 开启 QQ 图（首次请求无开关，为后续带开关的谓词铺垫）
    await page.getByText('显示QQ图').click()
    await expect
      .poll(() => page.locator(`${SINGLE} svg`).count(), { timeout: 15_000 })
      .toBeGreaterThanOrEqual(2)

    const respPromise = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/qqplot/') &&
        r.request().method() === 'POST' &&
        r.request().postData()?.includes('"data_only_bin1":true') === true &&
        r.status() < 500,
      { timeout: 20_000 },
    )
    await toggleFilter(page, '仅用Pass数据(Bin1)')
    const resp = await respPromise
    expect(resp.request().postData() || '', 'QQ 图请求应携带 data_only_bin1').toContain('"data_only_bin1":true')
    // 响应携带 probplot 拟合参数（前端画参考线 y = intercept + slope·x 用）
    const qqBody = await resp.json()
    expect(typeof qqBody.slope, 'qqplot 响应应携带 slope').toBe('number')
    expect(typeof qqBody.intercept, 'qqplot 响应应携带 intercept').toBe('number')
    await waitLoadingGone(page.locator(SINGLE))
    await expect
      .poll(() => page.locator(`${SINGLE} svg`).count(), { timeout: 15_000 })
      .toBeGreaterThanOrEqual(2)

    // 参考线是拟合线而非 y=x：DA35 首参数 Index_No 均值≈5000 → 参考线端点 y 必然 ≠ x
    // （useChart 把 ECharts 实例挂载在容器 div 本身，属性即在其上）
    const lineData = await page.locator('.qqplot-container[_echarts_instance_]').evaluate((el: any) =>
      el.__echartsInstance__?.getOption?.()?.series?.[1]?.data ?? null,
    )
    expect(lineData, '参考线（series[1]）应存在').toBeTruthy()
    expect(lineData[0][1], '参考线端点 y ≠ x（数据均值非 0，拟合线被抬升）').not.toBe(lineData[0][0])

    // Y 轴 dataZoom：右侧滑块（slider）+ 滚轮（inside）作用于 yAxis 0，
    // dispatch 缩放后 start/end 更新（注意：getOption() 每次返回新快照，
    // 必须 dispatch 后再取，不能复用旧数组引用）
    const zoomState = await page.locator('.qqplot-container[_echarts_instance_]').evaluate((el: any) => {
      const inst = el.__echartsInstance__
      const dz = inst?.getOption?.()?.dataZoom ?? []
      inst?.dispatchAction?.({ type: 'dataZoom', dataZoomIndex: 0, start: 20, end: 60 })
      const dz2 = inst?.getOption?.()?.dataZoom ?? []
      const grid = (inst?.getOption?.()?.grid ?? [])[0] ?? {}
      return {
        count: dz.length,
        firstType: dz[0]?.type ?? null,
        yAxis: dz[0]?.yAxisIndex ?? null,
        after: dz2[0]?.start ?? null,
        // 滑块与 Y 轴同源定位：top 对齐 grid 顶，高度 = 容器高 − top − bottom
        sliderTop: dz[0]?.top ?? null,
        sliderHeight: dz[0]?.height ?? null,
        gridTop: grid.top ?? null,
        gridBottom: grid.bottom ?? null,
        containerHeight: el.clientHeight,
      }
    })
    expect(zoomState.count, '应配置 slider + inside 两个 dataZoom').toBeGreaterThanOrEqual(2)
    expect(zoomState.firstType, '首个 dataZoom 应为 slider 滑块').toBe('slider')
    expect(zoomState.yAxis, 'dataZoom 应作用于 Y 轴').toBe(0)
    expect(zoomState.after, '拖动滑块后 dataZoom.start 应更新').toBe(20)
    expect(zoomState.sliderTop, '滑块顶部应与 Y 轴（grid）顶部对齐').toBe(zoomState.gridTop)
    expect(zoomState.sliderHeight, '滑块高度应与 Y 轴等长（容器高 − top − bottom）')
      .toBe(zoomState.containerHeight - zoomState.gridTop - zoomState.gridBottom)
  })

  test('数值分布：勾选仅用Pass数据后箱线图请求携带开关且图表正常渲染', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))

    // 开启箱线图（首次请求无开关，GET query 断言 data_only_bin1=true）
    await page.getByText('显示箱线图').click()
    await expect
      .poll(() => page.locator(`${SINGLE} .chart-wrapper--bottom svg`).count(), { timeout: 15_000 })
      .toBeGreaterThanOrEqual(1)

    const respPromise = page.waitForResponse(
      (r) =>
        r.url().includes('/statistics/boxplot/') &&
        r.url().includes('data_only_bin1=true') &&
        r.status() < 500,
      { timeout: 20_000 },
    )
    await toggleFilter(page, '仅用Pass数据(Bin1)')
    const resp = await respPromise
    expect(resp.url(), '箱线图请求应携带 data_only_bin1').toContain('data_only_bin1=true')
    await waitLoadingGone(page.locator(SINGLE))
    await expect
      .poll(() => page.locator(`${SINGLE} .chart-wrapper--bottom svg`).count(), { timeout: 15_000 })
      .toBeGreaterThanOrEqual(1)
  })

  test('全 Pass 文件（Gage）：勾选仅用Pass数据后参数列表不变', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.gage[0])
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))

    const before = await listParams(page)
    expect(before.length).toBeGreaterThan(0)

    await toggleFilter(page, '仅用Pass数据(Bin1)')
    await waitLoadingGone(page.locator(SINGLE))
    const after = await listParams(page)
    expect(after, '全 Pass 文件过滤后列表应保持不变').toEqual(before)
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)
  })

  test('忽略无Limit：位于数据筛选区首位，切换后快路径请求携带 ignore_no_limit', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)

    // 首位断言：数据筛选区第一个 el-checkbox 即「忽略无Limit」
    await expect(page.locator('.filter-section .el-checkbox').first()).toContainText('忽略无Limit')

    // 快路径请求（body 无 params 字段，AnalysisPage onFileChange）必须携带 ignore_no_limit:true；
    // 谓词用「无 params」排除 useHistogram watch 发的计算路径请求
    const fastResp = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/histogram/') &&
        r.request().method() === 'POST' &&
        r.request().postData()?.includes('"ignore_no_limit":true') === true &&
        r.request().postData()?.includes('"params":') === false &&
        r.status() < 500,
      { timeout: 20_000 },
    )
    // 先勾再取消再勾，确保注册后有请求到达（沿用 data_only_bin1 的防竞态模式）
    await toggleFilter(page, '忽略无Limit')
    await toggleFilter(page, '忽略无Limit')
    await toggleFilter(page, '忽略无Limit')
    const fast = await fastResp
    expect(fast.request().postData() || '', '快路径请求应携带 ignore_no_limit').toContain('"ignore_no_limit":true')
    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)
  })
})

test.describe('@p1 柱宽设置生效', { tag: ['@p1', '@analysis'] }, () => {
  test('拖动柱宽 slider：ECharts barWidth 与实际柱宽像素同步变化', async ({ page }) => {
    // 回归：ChartConfigPanel 曾只监听 @change，而 EP slider 的值更新走
    // update:modelValue、change 发出的是 props.modelValue（单向绑定下永远
    // 是旧值 20）→ 柱宽设置永远无效。修复后点轨道/拖动实时生效。
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))

    const chartEl = page.locator(`${SINGLE} .chart-wrapper div[_echarts_instance_]`)
    await expect(chartEl).toBeVisible({ timeout: 15_000 })

    const readBar = () => chartEl.evaluate((el: any) => {
      const inst = el.__echartsInstance__
      const opt = inst?.getOption?.()
      let px: number | null = null
      try {
        px = inst?.getModel?.()?.getSeriesByIndex?.(0)?.getData?.()?.getItemLayout?.(0)?.width ?? null
      } catch { /* ignore */ }
      return { opt: opt?.series?.[0]?.barWidth ?? null, px }
    })

    const before = await readBar()
    // 默认生效值 = min(20, 上限)——多系列文件上限 <20（CTA8280F 4 site → 18%）
    expect(before.opt).toMatch(/^\d+%$/)

    // 展开「更多」露出柱宽 slider（第一个），End 键拖到上限
    await page.locator(`${SINGLE} .more-btn`).click()
    const slider = page.locator(`${SINGLE} .el-slider`).first()
    await expect(slider).toBeVisible({ timeout: 10_000 })
    const hint = page.locator(`${SINGLE} .config-section .value-hint`).first()
    await expect(hint).toContainText(before.opt)

    const btn = slider.locator('.el-slider__button-wrapper')
    await btn.click()
    await page.keyboard.press('End')

    // 值标签更新 + ECharts option barWidth 与 slider 值同步（上限随系列数/重合度
    // 联动，读实际上限而非硬编码；多系列场景上限可能 <20，故不断言像素变大方向）
    await expect
      .poll(async () => await btn.getAttribute('aria-valuemax'), { timeout: 5_000 })
      .not.toBeNull()
    const sliderMax = await btn.getAttribute('aria-valuemax')
    await expect
      .poll(async () => await btn.getAttribute('aria-valuenow'), { timeout: 5_000 })
      .toBe(sliderMax)
    await expect.poll(() => readBar().then((s) => s.opt)).toBe(`${sliderMax}%`)
    const after = await readBar()
    expect(after.px, '柱宽像素应有效').toBeGreaterThan(0)
  })
})
