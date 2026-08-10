import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { expectChartRendered, waitLoadingGone } from '../helpers/charts'
import { selectAnalysisFile } from '../helpers/params'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 「KDE曲线」显示开关（单参数分析页）。
 *
 * KDE 核密度曲线是后端 `kde_curve` 字段驱动的非参数密度叠加：对双峰/偏态
 * 数据比正态曲线更贴合。需求（plan: crystalline-inventing-badger.md）：
 *   - 默认勾选并渲染（默认 chartConfig 含 'kde'）；
 *   - 取消勾选 → 图例与曲线消失；重新勾选 → 恢复；
 *   - 回归：正态分布开关不受影响。
 *
 * 独立 Y 轴（2026-08-08 追加需求）：KDE 曲线使用独立紫色「KDE密度」轴
 * （放最左），正态曲线保留右侧橙色「概率密度」轴；两个轴都只在对应曲线
 * 勾选时出现。本 spec 同时断言轴名的存在/消失。
 *
 * 竞态防护：图例断言作用域限定在 `.chart-wrapper text`（SVG），避免把
 * 复选框 HTML 文案误判为图例；状态变化用 expect.poll 轮询而非固定等待。
 */

const SINGLE = '.single-param-tab'

/** 读取直方图 SVG 内全部文本（图例/标题），用于断言曲线项是否渲染 */
async function legendText(page: import('@playwright/test').Page): Promise<string> {
  const texts = await page.locator(`${SINGLE} .chart-wrapper text`).allTextContents()
  return texts.join(' | ')
}

function kdeCheckbox(page: import('@playwright/test').Page) {
  return page.locator(`${SINGLE} .config-checkboxes .el-checkbox`).filter({ hasText: 'KDE曲线' })
}

function kdeFullCheckbox(page: import('@playwright/test').Page) {
  return page.locator(`${SINGLE} .config-checkboxes .el-checkbox`).filter({ hasText: 'KDE含超限' })
}

function normalCheckbox(page: import('@playwright/test').Page) {
  return page.locator(`${SINGLE} .config-checkboxes .el-checkbox`).filter({ hasText: '正态分布' })
}

test.describe('@p1 KDE曲线显示开关', { tag: ['@p1', '@analysis'] }, () => {
  test('默认勾选且图例渲染 KDE曲线；取消/恢复切换生效', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)

    // 默认状态：KDE曲线 勾选 + 图例渲染 + 独立紫色「KDE密度」轴出现
    // （正态未勾选 → 右侧「概率密度」轴不应出现）
    await expect(kdeCheckbox(page), 'KDE曲线应默认勾选').toHaveClass(/is-checked/)
    await expect
      .poll(async () => legendText(page), { timeout: 8_000 })
      .toContain('KDE曲线')
    await expect
      .poll(async () => legendText(page), { timeout: 8_000 })
      .toContain('KDE密度')
    await expect
      .poll(async () => legendText(page), { timeout: 8_000 })
      .not.toContain('概率密度')

    // 取消勾选 → 图例与 KDE 轴都消失
    await kdeCheckbox(page).click()
    await expect(kdeCheckbox(page), '取消后应为未选中态').not.toHaveClass(/is-checked/)
    await expect
      .poll(async () => legendText(page), { timeout: 8_000 })
      .not.toContain('KDE曲线')
    await expect
      .poll(async () => legendText(page), { timeout: 8_000 })
      .not.toContain('KDE密度')

    // 重新勾选 → 图例与轴都恢复
    await kdeCheckbox(page).click()
    await expect(kdeCheckbox(page), '重新勾选后应为选中态').toHaveClass(/is-checked/)
    await expect
      .poll(async () => legendText(page), { timeout: 8_000 })
      .toContain('KDE曲线')
    await expect
      .poll(async () => legendText(page), { timeout: 8_000 })
      .toContain('KDE密度')
  })

  test('「KDE含超限」开关默认关闭，可勾选切换且不影响 KDE 曲线显示', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)

    // 默认状态：未勾选（保持剔除口径主峰保真）
    await expect(kdeFullCheckbox(page), 'KDE含超限应默认未勾选').not.toHaveClass(/is-checked/)

    // 勾选 → 选中态，图例 KDE曲线 仍在（曲线数据源切换，形状变化由后端单测覆盖）
    await kdeFullCheckbox(page).click()
    await expect(kdeFullCheckbox(page), '勾选后应为选中态').toHaveClass(/is-checked/)
    await expect
      .poll(async () => legendText(page), { timeout: 8_000 })
      .toContain('KDE曲线')

    // 取消 → 恢复未选中
    await kdeFullCheckbox(page).click()
    await expect(kdeFullCheckbox(page), '取消后应为未选中态').not.toHaveClass(/is-checked/)
    await expect
      .poll(async () => legendText(page), { timeout: 8_000 })
      .toContain('KDE曲线')
  })

  test('回归：正态分布开关仍可独立控制', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)

    // 正态分布默认不勾选（与 KDE 默认勾选互不影响）→ 右侧「概率密度」轴不出现
    await expect(normalCheckbox(page)).not.toHaveClass(/is-checked/)
    await expect
      .poll(async () => legendText(page), { timeout: 8_000 })
      .not.toContain('正态分布')
    await expect
      .poll(async () => legendText(page), { timeout: 8_000 })
      .not.toContain('概率密度')

    // 勾选 → 图例出现 + 右侧「概率密度」轴出现；KDE曲线 与 KDE 轴仍在
    await normalCheckbox(page).click()
    await expect(normalCheckbox(page)).toHaveClass(/is-checked/)
    await expect
      .poll(async () => legendText(page), { timeout: 8_000 })
      .toContain('正态分布')
    const withBoth = await legendText(page)
    expect(withBoth, '正态分布与 KDE曲线 应并存').toContain('KDE曲线')
    expect(withBoth, '两个密度轴应并存（KDE密度 在左、概率密度 在右）')
      .toContain('KDE密度')
    expect(withBoth, '勾选正态后「概率密度」轴出现').toContain('概率密度')

    // 取消 → 图例消失 + 「概率密度」轴消失；KDE 轴不受影响
    await normalCheckbox(page).click()
    await expect(normalCheckbox(page)).not.toHaveClass(/is-checked/)
    await expect
      .poll(async () => legendText(page), { timeout: 8_000 })
      .not.toContain('正态分布')
    await expect
      .poll(async () => legendText(page), { timeout: 8_000 })
      .not.toContain('概率密度')
    await expect
      .poll(async () => legendText(page), { timeout: 8_000 })
      .toContain('KDE密度')
  })
})
