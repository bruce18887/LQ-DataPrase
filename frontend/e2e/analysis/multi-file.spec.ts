import { test, expect, type Page } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile } from '../helpers/params'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * [多文件分析] tab（quest.txt 改造）：
 *  1. 由「多Lot对比」拆分为独立顶层 tab，良率对比已移除。
 *  2. 选 ≥2 文件 → 提取共有测试项（列名相同）→ 渲染柱状图。
 *  3. 不拆 SITE，每文件一个图例；每文件 limit 线独立图例。
 *  4. 文件可自定义图例名。
 *
 * 数据：RECOMMENDED.buyoff 是同产品 3 个测试阶段（FT/QA1/QA2），共有测试项丰富。
 */

const TAB = '.multi-file-tab'

async function enterMultiFile(page: Page) {
  await gotoApp(page, '/analysis')
  // 顶部先选一个「与多文件清单不重叠」的文件，tabs 才出现；
  // 用 CTA8280F（非 buyoff）避免其 is-selected 选项干扰下方多选定位。
  await selectAnalysisFile(page, RECOMMENDED.analysis)
  await page.getByRole('tab', { name: /多文件分析/ }).click()
  await expect(page.locator(TAB)).toBeVisible({ timeout: 20_000 })
}

/** 在多文件 tab 左栏的「数据文件」多选里勾选若干文件名（filterable：开一次下拉，逐个过滤点选） */
async function pickFiles(page: Page, names: string[]) {
  const select = page.locator(`${TAB} .left-panel .el-select`).first()
  const input = select.locator('input').first()
  await select.click()
  const dropdown = page.locator('.el-select-dropdown:visible').last()
  await expect(dropdown).toBeVisible({ timeout: 10_000 })
  for (const name of names) {
    await input.fill(name)
    const option = dropdown.locator('.el-select-dropdown__item').filter({ hasText: name }).first()
    await expect(option).toBeVisible({ timeout: 10_000 })
    await option.click()
    await input.fill('') // 清空过滤，便于下一个文件匹配
  }
  await page.keyboard.press('Escape')
}

test.describe('@p1 多文件分析', { tag: ['@p1', '@analysis'] }, () => {
  test('选 2+ 文件 → 共有测试项非空 → 柱状图渲染（含 per-file limit 图例）', async ({ page }) => {
    test.slow()
    await enterMultiFile(page)

    // 选两个同产品文件 → 触发 common params + distribution
    const distResp = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/multi_lot/') &&
        r.request().method() === 'POST' &&
        (r.request().postData() || '').includes('"param"') &&
        r.status() < 500,
      { timeout: 25_000 },
    )
    await pickFiles(page, [RECOMMENDED.buyoff[0], RECOMMENDED.buyoff[1]])
    await distResp

    // 共有测试项数量提示
    await expect(page.locator(`${TAB} .common-hint`)).toContainText(/共有测试项/)

    // 参数选择器存在且有值
    await expect(page.locator(`${TAB} .param-selector .el-select`)).toBeVisible()

    // 柱状图 SVG 渲染且有尺寸
    const chart = page.locator(`${TAB} .chart-wrapper svg`)
    await expect(chart).toBeVisible({ timeout: 15_000 })
    const box = await chart.boundingBox()
    expect(box!.width).toBeGreaterThan(0)
    expect(box!.height).toBeGreaterThan(0)

    // 图例：每文件一项 + 每文件 Limit 独立项
    const legend = (await page.locator(`${TAB} text`).allTextContents()).join(' | ')
    expect(legend, '图例应出现独立的 Limit 项').toMatch(/Limit/)
    // 不应再出现良率对比（已移除）
    expect(legend).not.toMatch(/良率对比/)
  })

  test('自定义图例名 → 图表图例随之更新', async ({ page }) => {
    test.slow()
    await enterMultiFile(page)
    await pickFiles(page, [RECOMMENDED.buyoff[0], RECOMMENDED.buyoff[1]])
    await page.waitForResponse(
      (r) => r.url().includes('/analysis/multi_lot/') && r.status() < 500,
      { timeout: 25_000 },
    )
    await expect(page.locator(`${TAB} .chart-wrapper svg`)).toBeVisible({ timeout: 15_000 })

    // 改第一个文件的自定义名
    const firstNameInput = page.locator(`${TAB} .custom-names .name-row input`).first()
    await firstNameInput.fill('对照组A')
    await page.waitForTimeout(600)

    const legend = (await page.locator(`${TAB} text`).allTextContents()).join(' | ')
    expect(legend, '图例应反映自定义名「对照组A」').toMatch(/对照组A/)
  })

  test('忽略无Limit 开关重新拉取共有测试项', async ({ page }) => {
    test.slow()
    await enterMultiFile(page)
    await pickFiles(page, [RECOMMENDED.buyoff[0], RECOMMENDED.buyoff[1]])
    await page.waitForResponse(
      (r) => r.url().includes('/analysis/multi_lot/') && r.status() < 500,
      { timeout: 25_000 },
    )

    // 勾选「忽略无Limit」应触发一次带 ignore_no_limit 的无 param 请求
    const paramsResp = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/multi_lot/') &&
        (r.request().postData() || '').includes('ignore_no_limit') &&
        r.status() < 500,
      { timeout: 20_000 },
    )
    const checkbox = page.locator(TAB).locator('.el-checkbox').filter({ hasText: '忽略无Limit' })
    await checkbox.scrollIntoViewIfNeeded()
    await checkbox.getByText('忽略无Limit').click()
    await expect(checkbox, '点击后应变为选中态').toHaveClass(/is-checked/, { timeout: 5_000 })
    const resp = await paramsResp
    expect(resp.status()).toBeLessThan(400)
  })
})
