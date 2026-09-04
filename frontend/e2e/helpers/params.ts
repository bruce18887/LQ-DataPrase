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
 * 选中第一个「有真实规格限」的参数，返回其名字（找不到返回 null）。
 *
 * 为什么需要：CTA8280F 等格式里 Index_No / SW_Bin / X_COORD / Test_Time 这类
 * 系统列的限值字段是字面 'Min'/'Max'，语义是「无规格限」。后端曾把它们
 * 解析成**数据自身极值**当 LSL/USL，前端于是画出一条幻影限值线（且使
 * Cpk 数学上必然 ≤ 0.5 → 永远判红）；修正后这些列返回 null 且不画线。
 * 因此凡是要断言 LSL/USL 线的用例，都不能再依赖「默认选中的第一列」，
 * 必须显式选一个真有限值的参数。
 *
 * 实现：监听 histogram 响应，按 listParams 顺序逐个试，读到 lower_limit 与
 * upper_limit 都非 null 即停（实测 CTA8280F 在第 9 个参数 Kelvin_VIN 命中）。
 * 等待用条件轮询而非固定长睡眠，命中即返回。
 */
export async function selectParamWithSpecLimits(page: Page, maxTries = 20): Promise<string | null> {
  let found: string | null = null
  const handler = async (response: import('@playwright/test').Response) => {
    if (found || !response.url().includes('/analysis/histogram/')) return
    if (response.request().method() !== 'POST' || response.status() !== 200) return
    try {
      const body = await response.json()
      for (const [param, data] of Object.entries((body?.results ?? {}) as Record<string, any>)) {
        if (data?.lower_limit != null && data?.upper_limit != null) {
          found = param
          return
        }
      }
    } catch { /* 非 JSON / 已销毁的响应，忽略 */ }
  }
  page.on('response', handler)
  try {
    const params = await listParams(page)
    for (const p of params.slice(0, maxTries)) {
      if (found) break
      await selectParam(page, p)
      // 条件轮询：最多等 3s，命中立即继续（不用固定 waitForTimeout）
      for (let i = 0; i < 30 && !found; i++) await page.waitForTimeout(100)
    }
  } finally {
    page.off('response', handler)
  }
  return found
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
