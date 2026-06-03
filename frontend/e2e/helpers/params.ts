import { expect, type Locator, type Page } from '@playwright/test'

/**
 * Element Plus el-select 交互助手 + 分析页参数抽样。
 *
 * 注意：Element Plus 2.14 的 el-select 不再用 input[placeholder]，
 * 占位符是 <span class="el-select__placeholder">，故不能用 getByPlaceholder 定位 select。
 * 改为按稳定容器定位：
 *  - 文件选择器：AnalysisPage 顶部第一个 .el-select
 *  - 参数选择器：ParamSelector 根 div.param-selector 内的 .el-select（filterable，popper-class=param-select-dropdown）
 *  - 选项：.el-select-dropdown__item
 */

/** 打开一个 el-select 下拉 */
async function openElSelect(sel: Locator) {
  await expect(sel).toBeVisible({ timeout: 15_000 })
  await sel.click()
}

/** 当前可见下拉中的选项 */
function visibleOptions(page: Page, popperClass?: string) {
  const scope = popperClass ? `.${popperClass} ` : ''
  return page.locator(`${scope}.el-select-dropdown__item:visible`)
}

/** 数据分析页顶部的“数据文件”选择器（页面上第一个 el-select） */
function fileSelect(page: Page) {
  return page.locator('.el-select').first()
}

/** ParamSelector 的参数选择器 */
function paramSelect(page: Page) {
  return page.locator('.param-selector .el-select')
}

/** 选择数据分析页的数据文件（不传则选第一个） */
export async function selectAnalysisFile(page: Page, labelSubstring?: string) {
  await openElSelect(fileSelect(page))
  const options = visibleOptions(page)
  await expect(options.first()).toBeVisible({ timeout: 15_000 })
  const target = labelSubstring
    ? options.filter({ hasText: labelSubstring }).first()
    : options.first()
  await target.click()
}

/** 读取参数下拉的全部选项文本 */
export async function listParams(page: Page): Promise<string[]> {
  await openElSelect(paramSelect(page))
  const options = visibleOptions(page, 'param-select-dropdown')
  await expect(options.first()).toBeVisible({ timeout: 15_000 })
  const texts = (await options.allInnerTexts()).map((t) => t.trim()).filter(Boolean)
  await page.keyboard.press('Escape')
  return texts
}

/** 选中指定参数（利用 filterable 输入过滤后点击） */
export async function selectParam(page: Page, name: string) {
  const sel = paramSelect(page)
  await openElSelect(sel)
  // filterable：向内部 input 输入以过滤
  const input = sel.locator('input').first()
  await input.fill(name)
  const options = visibleOptions(page, 'param-select-dropdown')
  await options.filter({ hasText: name }).first().click()
}

/**
 * 从参数列表中随机抽取 n 个（去重）。
 * 普通测试文件中允许使用 Math.random。
 */
export function sampleN<T>(items: T[], n: number): T[] {
  if (items.length <= n) return [...items]
  const pool = [...items]
  const out: T[] = []
  while (out.length < n && pool.length) {
    const i = Math.floor(Math.random() * pool.length)
    out.push(pool.splice(i, 1)[0])
  }
  return out
}
