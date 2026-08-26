import { test, expect } from '@playwright/test'
import { SEEDED_FILES } from '../fixtures/test-data'
import { gotoApp } from '../helpers/nav'
import { elSelectByPlaceholder, visibleSelectOptions } from '../helpers/elplus'

/**
 * 文件相关性对比（数据管理「文件对比」tab，2026-08-21 重构 / 2026-08-28 优化）。
 *
 * 覆盖（2026-08-28 优化后）：
 * 1. 序列选择改为「搜索序列号」输入框勾选（默认前 10 颗，交互与查看数据
 *    搜索测试项一致）；
 * 2. Limit 对比与测试值对比拆分为两个视图（默认测试值对比，Limit 列不再
 *    占固定列宽）；
 * 3. 切走 tab 再切回结果仍在（重型表格 v-if 卸载/重挂的回归）；
 * 4. 导出 Excel 下载（双 Sheet 内容由后端测试覆盖，e2e 保持轻量）。
 */

/** 选择两个种子文件（BPD60320_FT vs BPD60320_QA1） */
async function pickFilePair(
  section: import('@playwright/test').Locator,
  page: import('@playwright/test').Page,
) {
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

  await elSelectByPlaceholder(section, '文件2 (Bench)').click()
  await visibleSelectOptions(page).filter({ hasText: SEEDED_FILES.BUYOFF_QA1 }).first().click()
  await page.waitForTimeout(600)
}

test.describe('@p2 文件对比（数据管理）', { tag: ['@p2', '@data'] }, () => {
  test('面板控件齐全：文件选择/阈值/规则/序列勾选器/ignore 勾选', async ({ page }) => {
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
    const ruleGroup = section.locator('.el-radio-group').first()
    await expect(ruleGroup.locator('.el-radio-button').filter({ hasText: 'A：Diff 必须为 0' }))
      .toHaveClass(/is-active/)

    // 序列选择器（替换原「序列上限」输入框）：未选文件时提示仅对比 Limit
    await expect(elSelectByPlaceholder(section, '搜索序列号')).toBeVisible()
    await expect(section.locator('.fc-serial-hint')).toContainText('无公共序列，仅对比 Limit')

    // ignore no limit / ignore no data 默认勾选
    await expect(section.locator('.el-checkbox').filter({ hasText: 'Ignore No Limit' })).toHaveClass(/is-checked/)
    await expect(section.locator('.el-checkbox').filter({ hasText: 'Ignore No Data' })).toHaveClass(/is-checked/)

    // 分析 / 导出按钮
    await expect(section.getByRole('button', { name: '分析', exact: true })).toBeVisible()
    await expect(section.getByRole('button', { name: '导出Excel' })).toBeVisible()
  })

  test('选两文件 → 默认前10颗 → 分析 → 测试值表格 → 切 Limit 视图', async ({ page }) => {
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '文件对比' }).click()

    const section = page.locator('.file-corr-section')
    await expect(section).toBeVisible({ timeout: 10_000 })

    await pickFilePair(section, page)

    // 公共序列加载完成 → 默认勾选前 10 颗
    const hint = section.locator('.fc-serial-hint')
    await expect(hint).toContainText(/已选 10 \/ 共 \d+ 颗/, { timeout: 15_000 })

    await section.getByRole('button', { name: '分析', exact: true }).click()

    // 总结卡片
    const summary = section.locator('.fc-summary')
    await expect(summary).toBeVisible({ timeout: 30_000 })
    await expect(summary.locator('.metric-card').first().locator('.metric-label')).toContainText('公共序列')
    await expect
      .poll(
        () => summary.locator('.metric-card').first().locator('.metric-value').textContent(),
        { timeout: 10_000 },
      )
      .toMatch(/\d+/)

    // 默认视图 = 测试值对比：Parameters + Data A 的 Limit/单位 + 判定 + 每序列块；
    // B 侧 Limit（LSL B/USL Diff）不在本视图
    const table = section.locator('.fc-table')
    await expect(table).toBeVisible({ timeout: 20_000 })
    await expect(section.locator('.fc-table-info')).toContainText('Data A VS Data B')
    await expect(table.getByText('Parameters', { exact: true })).toBeVisible()
    await expect(table.getByText('LSL A', { exact: true })).toBeVisible()
    await expect(table.getByText('USL A', { exact: true })).toBeVisible()
    await expect(table.getByText('Unit', { exact: true })).toBeVisible()
    await expect(table.getByText('判定', { exact: true })).toBeVisible()
    await expect(table.getByText('ATE', { exact: true }).first()).toBeVisible()
    await expect(table.getByText('LSL B', { exact: true })).toHaveCount(0)
    await expect(table.getByText('USL Diff', { exact: true })).toHaveCount(0)
    // ag-grid 行 + 判定单元格（虚拟化后 DOM 仍渲染首屏行）
    await expect(table.locator('.ag-row').first()).toBeVisible({ timeout: 20_000 })
    await expect(table.locator('.fc-verdict-cell').first()).toBeVisible()

    // 切换 Limit 对比视图：Limit 列齐全、无序列块
    await section.locator('.el-radio-button').filter({ hasText: 'Limit 对比' }).click()
    await expect(table.getByText('LSL A', { exact: true })).toBeVisible()
    await expect(table.getByText('USL Diff', { exact: true })).toBeVisible()
    await expect(table.getByText('LSL B', { exact: true })).toBeVisible()
    await expect(table.getByText('USL B', { exact: true })).toBeVisible()
    await expect(table.getByText('ATE', { exact: true })).toHaveCount(0)
    await expect(table.getByText('% Diff', { exact: true })).toHaveCount(0)

    // 切回测试值对比
    await section.locator('.el-radio-button').filter({ hasText: '测试值对比' }).click()
    await expect(table.getByText('ATE', { exact: true }).first()).toBeVisible()
    await expect(table.getByText('LSL B', { exact: true })).toHaveCount(0)
    await expect(table.getByText('LSL A', { exact: true })).toBeVisible()
  })

  test('切走其它 tab 再切回：结果保留（重型表格 v-if 卸载/重挂回归）', async ({ page }) => {
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '文件对比' }).click()

    const section = page.locator('.file-corr-section')
    await expect(section).toBeVisible({ timeout: 10_000 })
    await pickFilePair(section, page)
    await expect(section.locator('.fc-serial-hint')).toContainText(/已选 10 \/ 共 \d+ 颗/, { timeout: 15_000 })
    await section.getByRole('button', { name: '分析', exact: true }).click()
    await expect(section.locator('.fc-table')).toBeVisible({ timeout: 20_000 })

    // 切到「文件列表」再切回：表格（v-if）重新挂载且结果仍在
    await page.locator('.tab-btn').filter({ hasText: '文件列表' }).click()
    await expect(page.locator('.tab-btn').filter({ hasText: '文件列表' })).toHaveClass(/active/)
    await page.locator('.tab-btn').filter({ hasText: '文件对比' }).click()
    await expect(section.locator('.fc-summary')).toBeVisible({ timeout: 20_000 })
    await expect(section.locator('.fc-table')).toBeVisible({ timeout: 20_000 })
    await expect(section.locator('.fc-serial-hint')).toContainText(/已选 10 \/ 共 \d+ 颗/)
  })

  test('序列勾选：搜索 Enter 全选匹配 / 清空 → 仅对比 Limit', async ({ page }) => {
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '文件对比' }).click()

    const section = page.locator('.file-corr-section')
    await expect(section).toBeVisible({ timeout: 10_000 })
    await pickFilePair(section, page)
    await expect(section.locator('.fc-serial-hint')).toContainText(/已选 10 \/ 共 \d+ 颗/, { timeout: 15_000 })

    // 打开序列下拉 → 过滤 '1' → Enter 全选匹配（与搜索测试项一致的交互）。
    // 注意：已选序列后占位文本消失，不能再用占位符定位 → 用容器 class；
    // 下拉 teleport 到 body，footer 提示需从可见 dropdown 中取。
    const serialSel = section.locator('.fc-serial-sel .el-select')
    await serialSel.click()
    await page.keyboard.type('1')
    await expect(page.locator('.el-select-dropdown:visible .match-hint')).toContainText('按 Enter 全选', { timeout: 5000 })
    await page.keyboard.press('Enter')
    // Enter 全选匹配（含 '1' 的序列）→ 已选数应大于默认 10
    await expect
      .poll(() => section.locator('.fc-serial-hint').textContent())
      .toMatch(/已选 (\d+) \/ 共 \d+ 颗/)
    await page.keyboard.press('Escape')

    // 全选按钮 → 触达上限 200（el-table 无列虚拟化的安全上限；
    // 已选数上限 < 总数时提示「已选 200 / 共 N 颗（最多 200）」）
    await section.getByRole('button', { name: '全选' }).click()
    await expect
      .poll(() => section.locator('.fc-serial-hint').textContent())
      .toMatch(/已选 200 \/ 共 \d+ 颗（最多 200）/)

    // 清空 → 未选择提示
    await section.getByRole('button', { name: '清空' }).click()
    await expect(section.locator('.fc-serial-hint')).toContainText('未选择')

    // 空选 → 分析 → limits_only 防呆提示
    await section.getByRole('button', { name: '分析', exact: true }).click()
    await expect(section.locator('.fc-alert')).toContainText('没有可对比的序列', { timeout: 15_000 })
    await expect(section.locator('.fc-table')).toBeVisible({ timeout: 15_000 })
  })

  test('导出 Excel 触发模板命名下载', async ({ page }) => {
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '文件对比' }).click()

    const section = page.locator('.file-corr-section')
    await expect(section).toBeVisible({ timeout: 10_000 })
    await pickFilePair(section, page)

    const downloadPromise = page.waitForEvent('download')
    await section.getByRole('button', { name: '导出Excel' }).click()
    const download = await downloadPromise
    // 默认导出文件名模板：{file1}_vs_{file2}_correlation.xlsx
    expect(download.suggestedFilename()).toMatch(/BPD60320_FT_vs_BPD60320_QA1_correlation\.xlsx/)
  })
})
