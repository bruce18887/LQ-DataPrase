import { test, expect, type Page } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, pickTabFile, filterControl } from '../helpers/params'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 数据筛选开关（仅用Pass/仅Fail/忽略无测试值/低CPK）在多文件分析与
 * 相关性对比图表（散点/矩阵）的移植（需求6，2026-08-20）。
 *
 * 与单文件口径一致：请求必须携带开关字段（R2：谓词按请求体精确串过滤）；
 * 多文件「仅Fail项」收缩 common 参数列表；相关性散点/矩阵请求携带全部开关。
 */

const TAB = '.multi-file-tab'

/** 点击指定数据筛选开关（el-checkbox 的 input 视觉隐藏，点击根容器） */
async function toggleFilter(page: Page, scope: string, name: string) {
  await page.locator(scope + ' .el-checkbox').filter({ hasText: name }).first().click()
}

/** 多文件分析 tab：选 2 个文件并等参数列表加载 */
async function openMultiFile(page: Page) {
  await gotoApp(page, '/analysis')
  await selectAnalysisFile(page, RECOMMENDED.analysis)
  await page.getByRole('tab', { name: /多文件分析/ }).click()
  const select = page.locator(`${TAB} .left-panel .el-select`).first()
  await expect(select).toBeVisible({ timeout: 20_000 })
  await select.click()
  const dropdown = page.locator('.el-select-dropdown:visible').last()
  await expect(dropdown).toBeVisible({ timeout: 10_000 })
  // 用 filterable 输入过滤到 BPD60320 三个文件再逐个选（126 个选项全量渲染
  // 时滚动定位不稳定；过滤后选项少且已选置顶重排影响小）
  const input = select.locator('input').first()
  await input.pressSequentially('BPD60320')
  for (const name of RECOMMENDED.analysisMulti) {
    const opt = dropdown.locator('.el-select-dropdown__item').filter({ hasText: name.slice(0, 12) }).first()
    await expect(opt).toBeVisible({ timeout: 5_000 })
    await opt.click()
    await page.waitForTimeout(300)
  }
  await page.keyboard.press('Escape')
  // 等公共参数列表加载（合并请求响应到达）
  await expect(page.locator(`${TAB} .common-hint`)).toBeVisible({ timeout: 20_000 })
  await expect(page.locator(`${TAB} svg, ${TAB} canvas`).first()).toBeVisible({ timeout: 20_000 })
}

function multiLotReqWith(...fragments: string[]) {
  return (r: { url(): string; request(): { method(): string; postData(): string | null }; status(): number }) =>
    r.url().includes('/analysis/multi_lot/') &&
    r.request().method() === 'POST' &&
    fragments.every((f) => r.request().postData()?.includes(f) === true) &&
    r.status() < 500
}

/** 当前可见相关性对比 tab 的容器（el-tabs 隐藏 pane display:none） */
function corrScope(page: Page) {
  return page.locator('.el-tab-pane').filter({ hasText: '文件相关性' }).filter({ visible: true }).first()
}

/**
 * 打开相关性 tab 并选上本 tab 自己的文件。
 *
 * 2026-09-05 起四个 tab 各持一份文件选择：在单文件 tab 选的文件不会
 * 自动带给相关性 tab，不显式选到 CTA8280F 就没有 Index_No / Kelvin_VIN。
 */
async function openCorrelationTab(page: Page) {
  await gotoApp(page, '/analysis')
  await page.getByRole('tab', { name: /相关性对比/ }).click()
  await pickTabFile(page, 'correlation', RECOMMENDED.analysis)
  // 等本 tab 的参数列表到达（选 X/Y 依赖它）
  await expect(filterControl(page, 'data-only-bin1')).toBeVisible({ timeout: 20_000 })
}

test.describe('@p1 多文件分析与相关性筛选开关', { tag: ['@p1', '@analysis'] }, () => {
  test('多文件分析：仅用Pass数据 → multi_lot 请求携带 data_only_bin1 且分布重算', async ({ page }) => {
    await openMultiFile(page)

    const respPromise = page.waitForResponse(multiLotReqWith('"data_only_bin1":true'), { timeout: 20_000 })
    await toggleFilter(page, TAB, '仅用Pass数据(Bin1)')
    const resp = await respPromise
    expect(resp.request().postData() || '', 'multi_lot 请求应携带 data_only_bin1')
      .toContain('"data_only_bin1":true')
    // 分布仍正常渲染（合并响应）
    await expect(page.locator(`${TAB} svg, ${TAB} canvas`).first()).toBeVisible({ timeout: 20_000 })
  })

  test('多文件分析：仅显示Fail测试项 → 公共参数列表收缩', async ({ page }) => {
    await openMultiFile(page)

    const hint = page.locator(`${TAB} .common-hint`)
    const beforeText = await hint.innerText()
    const before = Number((beforeText.match(/(\d+) 项/) ?? [])[1] ?? 0)
    expect(before).toBeGreaterThan(0)

    const respPromise = page.waitForResponse(multiLotReqWith('"only_fail_test_item":true'), { timeout: 20_000 })
    await toggleFilter(page, TAB, '仅显示Fail测试项')
    const resp = await respPromise
    expect(resp.request().postData() || '', 'multi_lot 请求应携带 only_fail_test_item')
      .toContain('"only_fail_test_item":true')
    // 列表收缩（Fail 项 ⊂ 全部；文件无公共 fail 项时列表为空 → 提示消失、切空态）
    await expect
      .poll(async () => {
        const hintVisible = await hint.isVisible().catch(() => false)
        if (!hintVisible) return 0 // 空态「没有共有测试项」= 收缩为 0
        const t = await hint.innerText()
        return Number((t.match(/(\d+) 项/) ?? [])[1] ?? -1)
      }, { timeout: 20_000 })
      .toBeLessThan(before)
  })

  test('相关性散点：勾选仅用Pass数据 → correlation 请求携带开关', async ({ page }) => {
    await openCorrelationTab(page)

    // 选 X/Y 参数（CTA8280F_FT 固定存在的两个数值列），自动触发 correlation 请求。
    // 注意：el-select 必须按「含 label 的卡片」定位——pane 级 hasText 会把
    // X/Y 两个下拉都命中，first() 恒取到 X 轴（2026-08-20 踩坑）
    const xCard = page.locator('.el-tab-pane:visible .el-card').filter({ hasText: 'X 轴测试项' }).first()
    const xSelect = xCard.locator('.el-select').first()
    await xSelect.click()
    await page.locator('.el-select-dropdown:visible .el-select-dropdown__item').filter({ hasText: 'Index_No' }).first().click()
    const yCard = page.locator('.el-tab-pane:visible .el-card').filter({ hasText: 'Y 轴测试项' }).first()
    const ySelect = yCard.locator('.el-select').first()
    await ySelect.click()
    // 参数下拉 filterable：输入过滤后等渲染稳定再普通点击（Kelvin_VIN 在
    // 180 项列表中在可视区外；过滤渲染期间项持续重排，force 点击可能落空）
    await ySelect.locator('input').first().pressSequentially('Kelvin_VIN')
    await page.waitForTimeout(600)
    await page.locator('.el-select-dropdown:visible .el-select-dropdown__item').filter({ hasText: 'Kelvin_VIN' }).first().click()
    // 选中值必须生效（防落空导致 localX/localY 未设 → 开关 watch 跳过请求）
    await expect(xSelect).toContainText('Index_No')
    await expect(ySelect).toContainText('Kelvin_VIN')
    await expect
      .poll(() => page.locator('.el-tab-pane:visible .chart-wrapper svg, .el-tab-pane:visible .chart-wrapper canvas').count(), { timeout: 15_000 })
      .toBeGreaterThan(0)

    // 谓词只匹配请求体（不带状态过滤——Vite 代理偶发 502 属基础设施噪声，
    // 状态在断言处校验）
    const respPromise = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/correlation/') &&
        r.request().method() === 'POST' &&
        r.request().postData()?.includes('"data_only_bin1":true') === true,
      { timeout: 20_000 },
    )
    await filterControl(page, 'data-only-bin1').click()
    // 勾选态必须生效（防点击落空导致请求缺失的假失败）
    await expect(filterControl(page, 'data-only-bin1')).toHaveClass(/is-checked/)
    const resp = await respPromise
    expect(resp.request().postData() || '', 'correlation 请求应携带 data_only_bin1')
      .toContain('"data_only_bin1":true')
    expect(resp.status(), 'correlation 应 200').toBeLessThan(500)
  })

  test('相关性矩阵：勾选仅用Pass数据 → correlation_matrix 请求携带开关', async ({ page }) => {
    await openCorrelationTab(page)

    // 切到矩阵模式并计算（默认参数全选）
    await page.locator('.el-radio-button').filter({ hasText: '相关性矩阵' }).first().click()
    const respPromise = page.waitForResponse(
      (r) =>
        r.url().includes('/statistics/correlation_matrix/') &&
        r.request().method() === 'POST' &&
        r.request().postData()?.includes('"data_only_bin1":true') === true &&
        r.status() < 500,
      { timeout: 20_000 },
    )
    await filterControl(page, 'data-only-bin1').click()
    await page.getByRole('button', { name: /计算相关性矩阵/ }).click()
    const resp = await respPromise
    expect(resp.request().postData() || '', 'correlation_matrix 请求应携带 data_only_bin1')
      .toContain('"data_only_bin1":true')
    expect(resp.status()).toBe(200)
  })
})
