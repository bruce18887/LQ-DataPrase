import { expect, type Locator, type Page } from '@playwright/test'

/**
 * Element Plus el-select 交互助手 + 分析页参数抽样。
 *
 * 注意：Element Plus 2.14 的 el-select 不再用 input[placeholder]，
 * 占位符是 <span class="el-select__placeholder">，故不能用 getByPlaceholder 定位 select。
 * 定位一律走组件上显式挂的稳定契约属性（不依赖顺序与文案，见
 * docs/specs/2026-09-02 §7.1 选择器契约）：
 *  - 文件选择器：`[data-file-picker="single|wafer|correlation|multi"]`
 *  - 数据控件：`[data-filter="outlier-handling|iqr-multiplier|ignore-no-limit|…"]`
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

/** 分析页某 tab 的数据文件选择器（scope = 契约属性值，页内唯一） */
export function filePicker(page: Page, scope: 'single' | 'wafer' | 'correlation' | 'multi' = 'single') {
  return page.locator(`[data-file-picker="${scope}"]`)
}

/**
 * 按 data-filter 契约定位分析页数据控件。
 *
 * 必须限定在**可见 tab pane** 内：异常值处理/敏感度与 5 个开关现在每个
 * tab 一份，访问过两个 tab 后同名属性会有多份实例，严格模式会报「matched 2 elements」。
 */
export function filterControl(
  page: Page,
  name: 'outlier-handling' | 'iqr-multiplier' | 'ignore-no-limit' | 'ignore-no-test-value'
    | 'data-only-bin1' | 'only-fail-test-item' | 'only-low-cpk',
) {
  return page.locator(`.el-tab-pane:visible [data-filter="${name}"]`)
}

/** ParamSelector 的参数选择器 */
function paramSelect(page: Page) {
  return page.locator('.param-selector .el-select')
}

/** 选择数据分析页的数据文件（不传则选第一个） */
export async function selectAnalysisFile(page: Page, labelSubstring?: string) {
  await pickTabFile(page, 'single', labelSubstring)
}

/**
 * 在指定 tab 的文件选择器里选文件（不传 substring 选第一项）。
 * 调用前必须先切到该 tab（lazy pane 未挂载时选择器不在 DOM 里）。
 * 单选语义；多文件 tab 的多选勾选仍由各 spec 自己驱动。
 */
export async function pickTabFile(
  page: Page,
  scope: 'single' | 'wafer' | 'correlation',
  labelSubstring?: string,
) {
  const sel = filePicker(page, scope)
  await openElSelect(sel)
  // 选项必须限定在**本 picker 自己的 popper** 里：四个 tab 的下拉面板都被
  // teleport 到 body，隐藏 pane 的那一份仍会被全局 `:visible` 命中（它的
  // reference 尺寸为零 → popper 逐帧重定位→“element is not stable”，
  // 而且 `.first()` 会点到另一个 tab 的文件上）
  const options = page.locator(`.dp-file-picker-${scope}:visible .el-select-dropdown__item`)
  await expect(options.first()).toBeVisible({ timeout: 15_000 })
  const target = labelSubstring
    ? options.filter({ hasText: labelSubstring }).first()
    : options.first()
  await target.click()
}

/**
 * 选异常值处理模式（「裁剪范围」/「不处理」）。
 * scope = 控件所在 tab（默认单文件）；同样要限定在本 tab 的 popper 内。
 */
export async function pickOutlierMode(page: Page, mode: string, scope = 'single') {
  await openElSelect(filterControl(page, 'outlier-handling'))
  await page.locator(`.dp-outlier-popper-${scope}:visible .el-select-dropdown__item`)
    .filter({ hasText: mode }).first().click()
}

/** 选敏感度档位（如「宽松 (3.0x IQR)」） */
export async function pickSensitivity(page: Page, label: string, scope = 'single') {
  await openElSelect(filterControl(page, 'iqr-multiplier'))
  await page.locator(`.dp-iqr-popper-${scope}:visible .el-select-dropdown__item`)
    .filter({ hasText: label }).first().click()
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
