import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { pickOption } from '../helpers/elplus'
import { pickTabFile } from '../helpers/params'
import { RECOMMENDED, SEEDED_FILES } from '../fixtures/test-data'

/**
 * 相关性 tab 切文件后必须清空旧文件的散点/指标（回归钉，2026-09-05 审查 H1）。
 *
 * 缺陷形态：localX/localY 是组件本地 ref，切文件时 useTabFileParams 只清参数
 * 列表，X/Y 选择与 corrResult/matrixData 无人重置——散点图、Pearson r、回归
 * 方程无限期显示上一个文件的结果；新文件恰有同名参数时是静默错误数据。
 * 修复后 watch(fileId) 统一清空，界面回到「选择 X/Y 轴参数以分析相关性」空态。
 */

test.describe('@p1 相关性 tab 切文件清空旧结果', { tag: ['@p1', '@analysis'] }, () => {
  test('选好 X/Y 后切文件 → 散点与指标卡清空、X/Y 回到占位符', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await page.getByRole('tab', { name: /相关性对比/ }).click()
    await pickTabFile(page, 'correlation', RECOMMENDED.analysis)

    const layout = page.locator('.analysis-tab-layout:visible')
    await expect(layout).toBeVisible({ timeout: 10_000 })

    // 选 X/Y 触发自动 correlation 请求（无「分析相关性」按钮）
    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/analysis/correlation/') && r.request().method() === 'POST' && r.status() < 500,
      { timeout: 25_000 },
    )
    await pickOption(page, '选择 X 轴参数', 'KELVIN_VIN', layout)
    // X 下拉关闭动画与 Y 下拉打开重叠会导致选项瞬时不稳定，间隔后再选 Y
    await page.waitForTimeout(600)
    await pickOption(page, '选择 Y 轴参数', 'KELVIN_SW', layout)
    const resp = await respPromise
    expect(resp.status()).toBe(200)

    // 旧文件结果已展示（同屏改造后指标在散点卡头一行）
    await expect(layout.locator('.head-metric').first()).toBeVisible({ timeout: 15_000 })
    await expect(layout.locator('.scatter-chart-inner')).toBeVisible()

    // 切到另一个文件：等新文件自己的参数列表请求（fast-path 携带筛选开关，
    // 不带 params 键——waitForNextHistogramCompute 匹配的是计算请求，这里用不上）
    const listP = page.waitForResponse(
      (r) => r.url().includes('/analysis/histogram/') &&
        r.request().method() === 'POST' &&
        (r.request().postData() || '').includes('"ignore_no_limit"'),
      { timeout: 20_000 },
    )
    await pickTabFile(page, 'correlation', SEEDED_FILES.GAGE_S1)
    await listP

    // 指标与散点清空，回到空态提示
    await expect(layout.locator('.head-metric')).toHaveCount(0)
    await expect(layout.locator('.scatter-chart-inner')).toHaveCount(0)
    await expect(
      layout.locator('.el-empty').filter({ hasText: '选择 X/Y 轴参数或点击矩阵格以分析相关性' }),
    ).toBeVisible()
    // X/Y 选择回到占位符（本地选择已被重置，不是滞留旧文件的参数名）
    await expect(layout.locator('.el-select').filter({ hasText: '选择 X 轴参数' })).toBeVisible()
    await expect(layout.locator('.el-select').filter({ hasText: '选择 Y 轴参数' })).toBeVisible()
  })
})
