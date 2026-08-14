import { test, expect, type Locator, type Page } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile } from '../helpers/params'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * [FileSelect] 通用文件选择组件（components/common/FileSelect.vue）：
 *  1. 输入匹配过滤（filename/program/batch，大小写不敏感）+ 空态「无匹配文件」
 *  2. 匹配段 <mark> 高亮
 *  3. 前缀优先排序（前缀匹配 > 包含匹配）
 *  4. 多选已选置顶（按选中顺序）
 *  5. 富信息行（program · format · 行数，MultiFileTab 启用 show-meta）
 *
 * 种子数据：BPD60320 前缀 4 个文件（1 长名 CTA8290D + 3 buyoff）、gage_m_S 4 个。
 * 各测试上传均用唯一命名（e2e_* 前缀），不污染这些计数。
 */

const TAB = '.multi-file-tab'

/** 分析页顶部「数据文件」选择器（页面上第一个 el-select） */
function fileSelect(page: Page): Locator {
  return page.locator('.el-select').first()
}

/** 打开分析页文件下拉，返回可见下拉面板 */
async function openFileDropdown(page: Page): Promise<Locator> {
  const sel = fileSelect(page)
  await expect(sel).toBeVisible({ timeout: 15_000 })
  await sel.click()
  const dropdown = page.locator('.el-select-dropdown:visible').last()
  await expect(dropdown).toBeVisible({ timeout: 10_000 })
  return dropdown
}

/** 可见下拉选项 */
function visibleItems(dropdown: Locator): Locator {
  return dropdown.locator('.el-select-dropdown__item:visible')
}

test.describe('FileSelect 通用文件选择组件', { tag: ['@p1', '@analysis'] }, () => {
  test.beforeEach(async ({ page }) => {
    await gotoApp(page, '/analysis')
    await expect(fileSelect(page)).toBeVisible({ timeout: 15_000 })
  })

  test('搜索匹配过滤：大小写不敏感 + 无匹配空态', async ({ page }) => {
    const dropdown = await openFileDropdown(page)
    const input = fileSelect(page).locator('input').first()
    const items = visibleItems(dropdown)

    // 精确命中单个文件
    await input.fill('BPD60320_QA1')
    await expect(items.first()).toBeVisible({ timeout: 5_000 })
    expect(await items.count()).toBe(1)
    await expect(items.first()).toContainText('BPD60320_QA1')

    // 批量前缀：全部可见项均含关键字（数量 ≥3 抗 DB 累积干扰）
    await input.fill('gage_m_S')
    await expect(items.first()).toBeVisible({ timeout: 5_000 })
    const texts = (await items.allTextContents()).map((t) => t.trim()).filter(Boolean)
    expect(texts.length).toBeGreaterThanOrEqual(3)
    for (const t of texts) expect(t).toContain('gage_m_S')

    // 无匹配 → 空态提示
    await input.fill('ZZZ_NOT_EXISTS_12345')
    await expect(dropdown.locator('.el-select-dropdown__empty')).toHaveText('无匹配文件', { timeout: 5_000 })
    await page.keyboard.press('Escape')
  })

  test('高亮：匹配段以 <mark> 渲染（小写输入验证大小写不敏感）', async ({ page }) => {
    const dropdown = await openFileDropdown(page)
    const input = fileSelect(page).locator('input').first()

    await input.fill('bpd')
    const marks = dropdown.locator('mark')
    await expect(marks.first()).toBeVisible({ timeout: 5_000 })
    expect(await marks.count()).toBeGreaterThan(0)
    expect((await marks.first().textContent())?.toLowerCase()).toBe('bpd')
    await page.keyboard.press('Escape')
  })

  test('前缀优先排序：首项为前缀匹配', async ({ page }) => {
    const dropdown = await openFileDropdown(page)
    const input = fileSelect(page).locator('input').first()

    await input.fill('BPD')
    await expect(visibleItems(dropdown).first()).toBeVisible({ timeout: 5_000 })
    const firstText = (await visibleItems(dropdown).first().textContent()) ?? ''
    expect(firstText.trim().startsWith('BPD')).toBe(true)

    await input.fill('gage')
    await expect(visibleItems(dropdown).first()).toBeVisible({ timeout: 5_000 })
    const secondText = (await visibleItems(dropdown).first().textContent()) ?? ''
    expect(secondText.trim().startsWith('gage')).toBe(true)
    await page.keyboard.press('Escape')
  })

  test('多选过滤 + 已选置顶（按选中顺序）', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await page.getByRole('tab', { name: /多文件分析/ }).click()
    const select = page.locator(`${TAB} .left-panel .el-select`).first()
    await expect(select).toBeVisible({ timeout: 20_000 })

    const input = select.locator('input').first()
    await select.click()
    const dropdown = page.locator('.el-select-dropdown:visible').last()
    await expect(dropdown).toBeVisible({ timeout: 10_000 })

    // 选 QA1 → 清空过滤 → 已选置顶为首项
    await input.fill('BPD60320_QA1')
    const qa1 = dropdown.locator('.el-select-dropdown__item').filter({ hasText: 'BPD60320_QA1' }).first()
    await expect(qa1).toBeVisible({ timeout: 5_000 })
    await qa1.click()
    await input.fill('')
    await expect(visibleItems(dropdown).first()).toContainText('BPD60320_QA1', { timeout: 5_000 })

    // 再选 QA2 → 前两项顺序 [QA1, QA2]（置顶按选中顺序而非文件顺序）
    await input.fill('BPD60320_QA2')
    const qa2 = dropdown.locator('.el-select-dropdown__item').filter({ hasText: 'BPD60320_QA2' }).first()
    await expect(qa2).toBeVisible({ timeout: 5_000 })
    await qa2.click()
    await input.fill('')
    const items = visibleItems(dropdown)
    await expect(items.first()).toContainText('BPD60320_QA1', { timeout: 5_000 })
    await expect(items.nth(1)).toContainText('BPD60320_QA2')
    await page.keyboard.press('Escape')
  })

  test('富信息行：显示 program · format · 行数（show-meta）', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await page.getByRole('tab', { name: /多文件分析/ }).click()
    const select = page.locator(`${TAB} .left-panel .el-select`).first()
    await expect(select).toBeVisible({ timeout: 20_000 })

    await select.click()
    const dropdown = page.locator('.el-select-dropdown:visible').last()
    const meta = dropdown.locator('.dp-file-option__meta')
    await expect(meta.first()).toBeVisible({ timeout: 10_000 })
    const text = (await meta.first().textContent()) ?? ''
    expect(text).toMatch(/\S+ · \S+ · \d+ 行/)

    // 无裁剪回归（2026-08-13）：EP 默认 .el-select-dropdown__item height:34px
    // + overflow:hidden 会纵向裁掉第二行 meta——修复后 height:auto，
    // meta 行底边必须完整落在 item 内，且双行 item 高度 ≥ 36px（旧代码 34px 必失败）。
    // 结构：item > .dp-file-option > .dp-file-option__meta，锚定 meta 自己的祖先 item
    //（下拉含置顶/分组时首个 item 未必带 meta）
    const metaEl = meta.first()
    await expect(metaEl).toBeVisible({ timeout: 10_000 })
    const item = metaEl.locator('..').locator('..')
    // 下拉开启动画期间高度未稳定（过渡态会短暂坍缩成单行），轮询等双行高度稳定
    await expect
      .poll(async () => (await item.boundingBox())?.height ?? 0, { timeout: 5_000 })
      .toBeGreaterThanOrEqual(36)
    const itemBox = await item.boundingBox()
    const metaBox = await metaEl.boundingBox()
    expect(itemBox, '下拉项应有尺寸').not.toBeNull()
    expect(metaBox, 'meta 行应有尺寸').not.toBeNull()
    // 容差 1px：getBoundingClientRect 为亚像素小数值，双行 item 有 padding/行高
    // 四舍五入差（实测最大偏差 ~0.55px）；被 34px 固定高度裁剪时偏差 >5px 必失败
    expect(metaBox!.y + metaBox!.height, 'meta 行底边不应超出下拉项（被 height:34px 裁剪）')
      .toBeLessThanOrEqual(itemBox!.y + itemBox!.height + 1)
    await page.keyboard.press('Escape')
  })
})
