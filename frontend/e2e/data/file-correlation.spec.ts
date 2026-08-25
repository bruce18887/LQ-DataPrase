import { test, expect } from '@playwright/test'
import { SEEDED_FILES } from '../fixtures/test-data'
import { gotoApp } from '../helpers/nav'
import { elSelectByPlaceholder, visibleSelectOptions } from '../helpers/elplus'

/**
 * 文件相关性对比（数据管理「文件对比」tab，2026-08-21 重构）。
 *
 * 功能覆盖：面板控件齐全（文件选择/误差阈值/Limit Diff 规则/序列上限/
 * ignore 勾选）、分析出模板风格表格 + 总结卡片、导出 Excel 下载。
 * （analysis 页的文件相关性已移除，旧 e2e 测试已迁移至此。）
 */

test.describe('@p2 文件对比（数据管理）', { tag: ['@p2', '@data'] }, () => {
  test('面板控件齐全：文件选择/阈值/规则/序列上限/ignore 勾选', async ({ page }) => {
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '文件对比' }).click()

    const section = page.locator('.file-corr-section')
    await expect(section).toBeVisible({ timeout: 10_000 })

    // 两个文件选择器
    await expect(elSelectByPlaceholder(section, '文件1 (ATE)')).toBeVisible()
    await expect(elSelectByPlaceholder(section, '文件2 (Bench)')).toBeVisible()

    // 误差阈值输入（默认 3，precision 1 → 显示 "3.0"）
    const threshold = section.locator('.fc-opt').filter({ hasText: '误差阈值' }).locator('.el-input-number input')
    await expect(threshold).toBeVisible()
    await expect(threshold).toHaveValue('3.0', { timeout: 5000 })

    // Limit Diff 规则单选：默认 A（Diff 必须为 0）
    const ruleGroup = section.locator('.el-radio-group')
    await expect(ruleGroup.locator('.el-radio-button').filter({ hasText: 'A：Diff 必须为 0' }))
      .toHaveClass(/is-active/)

    // 序列上限输入（默认 30）
    const maxSerials = section.locator('.fc-opt').filter({ hasText: '序列上限' }).locator('.el-input-number input')
    await expect(maxSerials).toBeVisible()
    await expect(maxSerials).toHaveValue('30', { timeout: 5000 })

    // ignore no limit / ignore no data 默认勾选
    await expect(section.locator('.el-checkbox').filter({ hasText: 'Ignore No Limit' })).toHaveClass(/is-checked/)
    await expect(section.locator('.el-checkbox').filter({ hasText: 'Ignore No Data' })).toHaveClass(/is-checked/)

    // 分析 / 导出按钮
    await expect(section.getByRole('button', { name: '分析', exact: true })).toBeVisible()
    await expect(section.getByRole('button', { name: '导出Excel' })).toBeVisible()
  })

  test('选择两个同产品文件 → 分析 → 总结卡片 + 模板风格表格', async ({ page }) => {
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '文件对比' }).click()

    const section = page.locator('.file-corr-section')
    await expect(section).toBeVisible({ timeout: 10_000 })

    // 选文件1 (ATE)：先等文件列表加载出选项再选
    await elSelectByPlaceholder(section, '文件1 (ATE)').click()
    await expect
      .poll(
        () => visibleSelectOptions(page).count(),
        { timeout: 15_000, message: '文件列表应加载出选项' },
      )
      .toBeGreaterThan(0)
    await visibleSelectOptions(page).filter({ hasText: SEEDED_FILES.BUYOFF_FT }).first().click()
    // 等上一个下拉的关闭动画结束，避免两个 dropdown 并存时 .first() 命中已隐藏选项
    await page.waitForTimeout(600)

    // 选文件2 (Bench)
    await elSelectByPlaceholder(section, '文件2 (Bench)').click()
    await visibleSelectOptions(page).filter({ hasText: SEEDED_FILES.BUYOFF_QA1 }).first().click()
    await page.waitForTimeout(600)

    await section.getByRole('button', { name: '分析', exact: true }).click()

    // 总结卡片（需求11）
    const summary = section.locator('.fc-summary')
    await expect(summary).toBeVisible({ timeout: 30_000 })
    await expect(summary.locator('.metric-card').first().locator('.metric-label')).toContainText('公共序列')
    // 公共序列数应为数字（≥0）
    await expect.poll(
      () => summary.locator('.metric-card').first().locator('.metric-value').textContent(),
      { timeout: 10_000 },
    ).toMatch(/\d+/)

    // 模板风格表格（Data A VS Data B 信息栏 + 固定 Limits 组 + 序列块）
    const table = section.locator('.fc-table')
    await expect(table).toBeVisible({ timeout: 20_000 })
    await expect(section.locator('.fc-table-info')).toContainText('Data A VS Data B')
    // 左侧固定组：Parameters / LSL A / USL Diff / 判定
    await expect(table.getByText('Parameters')).toBeVisible()
    await expect(table.getByText('LSL A')).toBeVisible()
    await expect(table.getByText('USL Diff')).toBeVisible()
    await expect(table.getByText('判定')).toBeVisible()
    // 至少一行测试项 + 每行有 PASS/FAIL 判定
    await expect(table.locator('.el-table__row').first()).toBeVisible({ timeout: 20_000 })
    await expect(table.locator('.el-table__row .verdict-badge').first()).toBeVisible()
  })

  test('导出 Excel 触发模板命名下载', async ({ page }) => {
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '文件对比' }).click()

    const section = page.locator('.file-corr-section')
    await expect(section).toBeVisible({ timeout: 10_000 })

    await elSelectByPlaceholder(section, '文件1 (ATE)').click()
    await expect
      .poll(
        () => visibleSelectOptions(page).count(),
        { timeout: 15_000, message: '文件列表应加载出选项' },
      )
      .toBeGreaterThan(0)
    await visibleSelectOptions(page).filter({ hasText: SEEDED_FILES.BUYOFF_FT }).first().click()
    await page.waitForTimeout(600)
    await elSelectByPlaceholder(section, '文件2 (Bench)').click()
    await visibleSelectOptions(page).filter({ hasText: SEEDED_FILES.BUYOFF_QA1 }).first().click()
    await page.waitForTimeout(600)

    const downloadPromise = page.waitForEvent('download')
    await section.getByRole('button', { name: '导出Excel' }).click()
    const download = await downloadPromise
    // 默认导出文件名模板：{file1}_vs_{file2}_correlation.xlsx
    expect(download.suggestedFilename()).toMatch(/BPD60320_FT_vs_BPD60320_QA1_correlation\.xlsx/)
  })
})
