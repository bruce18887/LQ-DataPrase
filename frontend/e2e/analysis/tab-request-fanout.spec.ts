import { test, expect, type Page } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile } from '../helpers/params'
import { RECOMMENDED } from '../fixtures/test-data'
import { waitLoadingGone } from '../helpers/charts'

/**
 * 分析页请求扇出（2026-09-02 审计批次 2）。
 *
 * 改造前实测（4 个 el-tab-pane 全都不是 lazy，进页面即全部挂载并跑各自 setup/watch）：
 *  1. 相关性对比 tab 与单文件 tab 共用同一组数据筛选开关（store 双向同步），
 *     用户停在单文件 tab 勾「仅用Pass数据」时，隐藏的相关性 tab 也会重发一次
 *     全量 correlation 计算；
 *  2. URL 带 ?mf_ids= 打开（刷新/分享链接）时，人还在单文件 tab，
 *     多文件 tab 的 onMounted 已经打了一次 multi_lot（两文件全量解析）。
 *
 * 本用例锁改造后的期望：没访问过的 tab 一个请求都不发；访问过但当前隐藏的 tab
 * 不因共享开关变化重发；切回该 tab 时把隐藏期间的变化补一次（不静默留旧数据）。
 *
 * 断言口径是真实网络请求（R2），不是组件内部状态；页面加载自身触发的请求
 * 一律等 UI 状态，不在 goto 之后注册响应等待器（R2④）。
 */

test.describe.configure({ timeout: 240_000 })

const MULTI = '.multi-file-tab'
const SINGLE = '.single-param-tab'
const BIN1 = '仅用Pass数据(Bin1)'

/** 统计发往指定端点的 POST 数（谓词按 URL 片段精确匹配） */
function postCounter(page: Page, fragment: string) {
  const state = { count: 0 }
  page.on('request', (req) => {
    if (req.method() === 'POST' && req.url().includes(fragment)) state.count += 1
  })
  return state
}

/** 等单文件侧的参数列表请求完成（说明文件已选中、页面稳定） */
async function waitHistogramSettled(page: Page, postDataIncludes?: string) {
  await page.waitForResponse(
    (r) =>
      r.url().includes('/analysis/histogram/') &&
      r.request().method() === 'POST' &&
      (postDataIncludes === undefined ||
        r.request().postData()?.includes(postDataIncludes) === true),
    { timeout: 120_000 },
  )
}

/** 多文件 tab：选 BUYOFF_FT + BUYOFF_QA1，等首次 multi_lot 返回 */
async function selectTwoFilesInMultiTab(page: Page) {
  await page.getByRole('tab', { name: /多文件分析/ }).click()
  const select = page.locator(`${MULTI} .left-panel .el-select`).first()
  await expect(select).toBeVisible({ timeout: 30_000 })
  await select.click()
  const dropdown = page.locator('.el-select-dropdown:visible').last()
  await expect(dropdown).toBeVisible({ timeout: 10_000 })
  await select.locator('input').first().pressSequentially('BPD60320')

  const firstResp = page.waitForResponse(
    (r) => r.url().includes('/analysis/multi_lot/') && r.request().method() === 'POST',
    { timeout: 120_000 },
  )
  for (const name of RECOMMENDED.analysisMulti) {
    const opt = dropdown.locator('.el-select-dropdown__item').filter({ hasText: name }).first()
    await expect(opt).toBeVisible({ timeout: 5_000 })
    await opt.click()
    await page.waitForTimeout(300)
  }
  await page.keyboard.press('Escape')
  await firstResp
  await expect(page.locator(`${MULTI} .common-hint`)).toBeVisible({ timeout: 60_000 })
}

/** 相关性 tab：选 X/Y 参数触发一次 correlation */
async function selectScatterParams(page: Page) {
  await page.getByRole('tab', { name: /相关性对比/ }).click()
  const xCard = page.locator('.el-tab-pane:visible .el-card').filter({ hasText: 'X 轴测试项' }).first()
  const xSelect = xCard.locator('.el-select').first()
  await xSelect.click()
  await page.locator('.el-select-dropdown:visible .el-select-dropdown__item')
    .filter({ hasText: 'Index_No' }).first().click()
  const yCard = page.locator('.el-tab-pane:visible .el-card').filter({ hasText: 'Y 轴测试项' }).first()
  const ySelect = yCard.locator('.el-select').first()
  await ySelect.click()
  await ySelect.locator('input').first().pressSequentially('Kelvin_VIN')
  await page.waitForTimeout(600)
  await page.locator('.el-select-dropdown:visible .el-select-dropdown__item')
    .filter({ hasText: 'Kelvin_VIN' }).first().click()
  await expect(xSelect).toContainText('Index_No')
  await expect(ySelect).toContainText('Kelvin_VIN')
  await page.waitForResponse(
    (r) => r.url().includes('/analysis/correlation/') && r.request().method() === 'POST',
    { timeout: 120_000 },
  )
}

test.describe('@p1 分析页请求扇出', { tag: ['@p1', '@analysis'] }, () => {
  test('只打开单文件 tab 时，其他 tab 的端点一次都不请求', async ({ page }) => {
    const multiLot = postCounter(page, '/analysis/multi_lot/')
    const correlation = postCounter(page, '/analysis/correlation/')
    const matrix = postCounter(page, '/statistics/correlation_matrix/')
    const wafer = postCounter(page, '/analysis/wafer_map/')

    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await waitHistogramSettled(page)
    await page.waitForTimeout(2_000)

    expect(multiLot.count, '未访问多文件 tab 不应发 multi_lot').toBe(0)
    expect(correlation.count, '未访问相关性 tab 不应发 correlation').toBe(0)
    expect(matrix.count, '未访问相关性 tab 不应发 correlation_matrix').toBe(0)
    expect(wafer.count, '晶圆图只在点击「加载晶圆图」时请求').toBe(0)
  })

  test('相关性 tab 访问过后隐藏：单文件侧切开关不重发，切回时补一次', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await waitHistogramSettled(page)
    await selectScatterParams(page)

    await page.getByRole('tab', { name: /单文件分析/ }).click()
    await expect(page.locator(SINGLE)).toBeVisible({ timeout: 30_000 })

    const corr = postCounter(page, '/analysis/correlation/')
    await page.locator(`${SINGLE} .el-checkbox`).filter({ hasText: BIN1 }).first().click()
    await expect(
      page.locator(`${SINGLE} .el-checkbox`).filter({ hasText: BIN1 }).first(),
    ).toHaveClass(/is-checked/)
    await waitHistogramSettled(page, '"data_only_bin1":true')
    await page.waitForTimeout(2_000)
    expect(corr.count, '隐藏的相关性 tab 不应跟着共享开关重算散点').toBe(0)

    // 切回相关性 tab：必须把隐藏期间的开关变化补上（不能静默留旧图）
    await page.getByRole('tab', { name: /相关性对比/ }).click()
    const resp = await page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/correlation/') &&
        r.request().method() === 'POST' &&
        r.request().postData()?.includes('"data_only_bin1":true') === true,
      { timeout: 120_000 },
    )
    expect(resp.status(), '补发的 correlation 请求应成功').toBeLessThan(500)
  })

  test('URL 带 mf_ids 进入：默认单文件 tab 不预打 multi_lot，点进去才算', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await waitHistogramSettled(page)
    await selectTwoFilesInMultiTab(page)
    // store 的 syncToQuery 把多选状态写进 URL（300ms 防抖）
    await expect.poll(() => page.url(), { timeout: 10_000 }).toContain('mf_ids=')
    const sharedUrl = page.url()

    // 计数器必须在 reload 之前装好：reload 后应用一挂载就自动选文件发请求，
    // 整轮约 500ms（实测余量仅 2ms）——goto 之后再注册会漏掉已到达的响应
    const multiLot = postCounter(page, '/analysis/multi_lot/')
    const baseline = multiLot.count // 扣掉前置阶段 selectTwoFilesInMultiTab 发的那次

    await page.goto(sharedUrl)
    await expect(page.locator(SINGLE)).toBeVisible({ timeout: 30_000 })
    await waitLoadingGone(page.locator(SINGLE))
    await page.waitForTimeout(2_000)
    expect(multiLot.count - baseline, '还没进多文件 tab 不应先做一次双文件全量解析').toBe(0)

    const opened = page.waitForResponse(
      (r) => r.url().includes('/analysis/multi_lot/') && r.request().method() === 'POST',
      { timeout: 120_000 },
    )
    await page.getByRole('tab', { name: /多文件分析/ }).click()
    await opened
    await expect(page.locator(`${MULTI} .common-hint`)).toBeVisible({ timeout: 60_000 })
  })
})
