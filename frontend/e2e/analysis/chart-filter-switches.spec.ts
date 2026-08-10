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
    const failResp = page.waitForResponse(histogramReqWith('"only_fail_test_item":true'), { timeout: 20_000 })
    await toggleFilter(page, '仅显示Fail测试项')
    const fr = await failResp
    expect(fr.request().postData() || '').toContain('"only_fail_test_item":true')
    await waitLoadingGone(page.locator(SINGLE))
    const failParams = await listParams(page)
    expect(failParams.length, 'Fail 项应少于全量参数').toBeLessThan(allParams.length)
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
