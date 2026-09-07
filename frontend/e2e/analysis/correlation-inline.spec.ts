import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { pickTabFile } from '../helpers/params'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 同屏改造新增能力（2026-09-07）：
 * 1. MatrixParamPicker：搜索过滤 chips / 点选取消 / 全选可见项 / 清空；
 * 2. 散点卡头一行指标：r 值星标 + p + n + 回归式；
 * 3. 抽样注记：仅当已画点数 < n 时出现「抽样 N/M 点」。
 *
 * X/Y 下拉用实例级 popper-class（dp-corr-x/y-popper）定位——多 teleport
 * 面板共存时全局 :visible 查询会命中隐藏 pane 的面板（lessons 2026-09-05）。
 */

const PICKER = '[data-matrix-param-picker]'
const SCATTER_CARD = '[data-corr-scatter-card]'

/** 打开 X 或 Y 轴下拉并选第 offset 个可见选项（限定本实例 popper 面板） */
async function pickAxisOption(page: import('@playwright/test').Page, axis: 'x' | 'y', offset: number) {
  await page.locator(`.el-select:has(> .el-select__wrapper) input`).first()
  await (axis === 'x'
    ? page.locator('.el-select').filter({ hasText: '选择 X 轴参数' })
    : page.locator('.el-select').filter({ hasText: '选择 Y 轴参数' })
  ).first().click()
  await page.locator(`.dp-corr-${axis}-popper:visible .el-select-dropdown__item`)
    .nth(offset).click()
}

test.describe('@p2 相关性同屏新增能力', { tag: ['@p2', '@analysis'] }, () => {
  test('参数搜索/chips 选择 + 散点卡头指标行', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await page.getByRole('tab', { name: /相关性对比/ }).click()
    await pickTabFile(page, 'correlation', RECOMMENDED.analysis)

    const picker = page.locator(PICKER)
    await expect(picker).toBeVisible({ timeout: 15_000 })

    // 1) chips 渲染且默认前 12 选中（不足 12 个参数时 = min(12, 参数总数)）
    // 显式等 chips 出现：卡片壳先渲染，chips 等参数列表请求回来才有内容
    const chips = picker.locator('.chip')
    await expect(chips.first()).toBeVisible({ timeout: 15_000 })
    const chipCount = await chips.count()
    expect(chipCount, 'chips 应渲染当前文件参数列表').toBeGreaterThan(0)
    const onCount = await picker.locator('.chip.on').count()
    expect(onCount, '默认选中数 = min(12, 参数总数)').toBe(Math.min(12, chipCount))

    // 2) 搜索过滤 + 选中切换：默认前 12 已选，先取一个**未选中**参数
    //    （点已选 chip 是取消选择），搜索过滤到它，点击后已选数 +1
    const unselectedChip = picker.locator('.chip:not(.on)').first()
    const unselectedName = (await unselectedChip.textContent())!.trim()
    await picker.locator('[data-matrix-search]').fill(unselectedName)
    await expect(picker.locator('.chip')).toHaveCount(1)
    const before = await picker.locator('.chip.on').count()
    await picker.locator('.chip').first().click()
    await expect(picker.locator('.chip.on')).toHaveCount(before + 1)

    // 3) 清空按钮作用于真实选择（已选回 0，计算按钮 disabled）
    await picker.getByRole('button', { name: '清空' }).click()
    await expect(picker.locator('.chip.on')).toHaveCount(0)
    await expect(page.getByRole('button', { name: /计算相关性矩阵/ })).toBeDisabled()

    // 4) 搜索空态
    await picker.locator('[data-matrix-search]').fill('___no_such_param___')
    await expect(picker.locator('.chips-empty')).toBeVisible()
    await picker.locator('[data-matrix-search]').fill('')

    // 5) 散点卡头指标行：选 X/Y 触发自动加载
    const layout = page.locator('.analysis-tab-layout:visible')
    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/analysis/correlation/') && r.request().method() === 'POST' && r.status() < 500,
      { timeout: 25_000 },
    )
    await pickAxisOption(page, 'x', 0)
    await page.waitForTimeout(600)
    await pickAxisOption(page, 'y', 1)
    await respPromise

    const head = layout.locator(`${SCATTER_CARD} .inline-card-h`)
    await expect(head.locator('.head-metric').filter({ hasText: 'r=' })).toBeVisible({ timeout: 15_000 })
    await expect(head.locator('.head-metric').filter({ hasText: 'p=' })).toBeVisible()
    await expect(head.locator('.head-metric').filter({ hasText: /^n=/ })).toBeVisible()
    // 回归线默认开 → 回归式出现
    await expect(head.locator('.head-eq')).toBeVisible()
    // 卡头出现「散点明细 · X × Y」
    await expect(head).toContainText(/散点明细 · .+ × .+/)
  })

  test('抽样注记：已画点数 < n 时显示「抽样 N/M 点」', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await page.getByRole('tab', { name: /相关性对比/ }).click()
    await pickTabFile(page, 'correlation', RECOMMENDED.analysis)
    const layout = page.locator('.analysis-tab-layout:visible')
    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/analysis/correlation/') && r.request().method() === 'POST' && r.status() < 500,
      { timeout: 25_000 },
    )
    await pickAxisOption(page, 'x', 0)
    await page.waitForTimeout(600)
    await pickAxisOption(page, 'y', 1)
    const resp = await (await respPromise).json()
    const n = resp.n as number
    const drawn = (resp.series_data as { data: unknown[] }[]).reduce((s, sd) => s + sd.data.length, 0)
    test.skip(drawn >= n, `该文件未触发降采样（drawn=${drawn}, n=${n}），抽样注记用例不适用`)

    await expect(layout.locator(`${SCATTER_CARD} .sample-note`)).toBeVisible({ timeout: 15_000 })
    await expect(layout.locator(`${SCATTER_CARD} .sample-note`)).toContainText('抽样')
  })
})
