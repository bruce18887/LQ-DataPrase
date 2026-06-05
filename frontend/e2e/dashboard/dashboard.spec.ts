import { test, expect } from '@playwright/test'
import { gotoApp, collectConsoleErrors } from '../helpers/nav'
import { expectChartRendered, waitForCharts, waitLoadingGone } from '../helpers/charts'

/**
 * 仪表板（/dashboard）。
 * 使用注入的 admin storageState（仅需 token，本页不要求管理员角色）。
 * 数据驱动：DB 中已存在激活数据文件，/summary/ 返回 200，故图表会渲染。
 *
 * 选择器依据（DashboardPage.vue）：
 *  - KPI 卡片标签：「总记录数 / Pass 数量 / Yield / 数据格式」
 *  - 章节标题 <h2>：「Bin 分布」「Site 良率分布」「Fail 测试项分析」等
 *  - 图表挂载在 <div ref> 上的 ECharts，各 div 带 role="img" aria-label
 *  - UPH 卡片：components/UphCard.vue 头部「⚡ UPH 效率分析」、单位「Units/Hour」
 */

test.describe('仪表板', { tag: ['@p0', '@p1', '@p2', '@dashboard'] }, () => {
  test('@p0 页面渲染无报错', async ({ page }) => {
    const errors = collectConsoleErrors(page)
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)
    await page.waitForTimeout(1200)
    expect(errors, `控制台错误:\n${errors.join('\n')}`).toEqual([])
  })

  test('@p1 KPI 指标卡片可见', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)
    await expect(page.getByText('总记录数')).toBeVisible()
    await expect(page.getByText('Pass 数量')).toBeVisible()
    await expect(page.getByText('Yield', { exact: false }).first()).toBeVisible()
    await expect(page.getByText('数据格式')).toBeVisible()
  })

  test('@p1 图表渲染（Bin 饼图 / Yield 仪表盘 / Fail 柱状 / CPK）', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)
    // 章节标题确认内容区已进入（非空/错误态）。/Bin 分布/ 同时匹配 h2 与 info-card h4，取首个
    await expect(page.getByRole('heading', { name: /Bin 分布/ }).first()).toBeVisible()
    // 至少两个 ECharts canvas（Bin 饼图 + Yield 仪表盘等）
    await waitForCharts(page, 2)
    // 首个 canvas（Bin 分布饼图区域）已正确渲染（可见 + 尺寸 > 0）
    await expectChartRendered(page, 0)
  })

  test('@p1 UPH 卡片显示', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)
    // UphCard.vue 头部文本（行 6），多处含 "UPH 效率分析"，取第一处
    await expect(page.getByText('UPH 效率分析').first()).toBeVisible()
    // 数据态下展示 UPH 指标与单位（UphCard.vue 行 21/23）
    await expect(page.getByText('Units/Hour')).toBeVisible()
  })

  test('@p1 良率趋势可视化渲染', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)

    // 说明：YieldTrendChart.vue 当前未被 DashboardPage.vue 引入挂载（孤儿组件，
    // 见 report）。仪表板上真正呈现的良率可视化是「整体Yield仪表盘」(行 83)。
    // 为保持对未来接线的健壮性：断言 YieldTrend 画布/空态文本，或退回到 Yield 仪表盘。
    const yieldTrendEmpty = page.getByText('暂无良率趋势数据')
    const yieldTrendImg = page.getByRole('img', { name: '良率趋势图' })
    const yieldGauge = page.getByRole('img', { name: '整体Yield仪表盘' })

    if (await yieldTrendEmpty.isVisible().catch(() => false)) {
      // 单文件场景：YieldTrend 显示空态
      await expect(yieldTrendEmpty).toBeVisible()
    } else if (await yieldTrendImg.count()) {
      // 已接线且有数据：YieldTrend 画布渲染
      await expectChartRendered(yieldTrendImg, 0)
    } else {
      // 实际情况：仪表板呈现 Yield 仪表盘（ECharts canvas）
      await expect(yieldGauge).toBeVisible()
      await expectChartRendered(yieldGauge, 0)
    }
  })

  test('@p2 批次良率 tab 可见并可切换', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)

    // 批次良率 tab should be visible
    const batchTab = page.locator('.el-tabs__item').filter({ hasText: '批次良率' })
    await expect(batchTab).toBeVisible()

    // Click to switch
    await batchTab.click()

    // Batch selector should appear
    await expect(page.locator('.batch-yield-tab')).toBeVisible()

    // Switch back to single file tab
    const singleTab = page.locator('.el-tabs__item').filter({ hasText: '单文件分析' })
    await singleTab.click()
    await expect(page.locator('.kpi-row')).toBeVisible()
  })
})
