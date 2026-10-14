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
 *  - 参数选择器：ParamSelector 根 div.param-selector 内的 .el-select（filterable，
 *    popper-class 按实例隔离：单文件 dp-param-popper-single / 多文件 dp-param-popper-multi）
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

/** ParamSelector 的参数选择器（单文件 tab 实例；多文件 tab 用 dp-param-popper-multi） */
function paramSelect(page: Page) {
  return page.locator('.param-selector .el-select')
}

/**
 * 选择数据分析页的数据文件（不传则选第一项）。
 *
 * 等到新文件自己的计算请求发出后才返回：切换窗口内 UI 仍显示上一个文件的
 * 图表/范围表（遮罩不在，waitLoadingGone 拦不住），直接读值会拿到旧数据。
 * 注意：若调用前初始自动选中的文件尚未发出计算请求，这里等到的是它的
 * 计算请求 —— 需要绝对严谨的用例请先等初始加载完再选（见 custom-limit-cpk）。
 */
export async function selectAnalysisFile(page: Page, labelSubstring?: string) {
  await pickTabFileAndWaitCompute(page, 'single', labelSubstring)
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

/** 打开参数下拉后取全部选项文本（限定单文件 tab 自己的 popper 面板） */
export async function listParams(page: Page): Promise<string[]> {
  await openElSelect(paramSelect(page))
  const options = visibleOptions(page, 'dp-param-popper-single')
  await expect(options.first()).toBeVisible({ timeout: 15_000 })
  const texts = (await options.allInnerTexts()).map((t) => t.trim()).filter(Boolean)
  await page.keyboard.press('Escape')
  return texts
}

/**
 * 选中指定参数（利用 filterable 输入过滤后点击）
 */
export async function selectParam(page: Page, name: string) {
  const sel = paramSelect(page)
  await openElSelect(sel)
  // filterable：向内部 input 输入以过滤
  const input = sel.locator('input').first()
  await input.fill(name)
  const options = visibleOptions(page, 'dp-param-popper-single')
  await options.filter({ hasText: name }).first().click()
}

/**
 * 等待本 tab 的**下一次** histogram 计算请求（带 params 的 POST）完成。
 *
 * 为什么需要：切文件后 UI 在新文件的计算响应到达前仍显示上一个文件的图表/
 * 范围表（产品行为，非 bug），waitLoadingGone 只看遮罩，遮罩此刻根本不在。
 * 实测（2026-09-05 探针）：选中 DA35 后 Data Range 短暂显示残留文件 a.csv 的
 * 恒定列范围 1/1，凡在此窗口读数值/列表的用例都会拿到旧数据。
 *
 * 前提：调用前初始自动选中的文件已加载完（先 waitLoadingGone/expectChartRendered），
 * 否则可能等到的是初始文件的计算请求。配对用法：
 *   const computeP = waitForNextHistogramCompute(page)
 *   await selectAnalysisFile(page, NAME)
 *   await computeP
 *   await waitLoadingGone(...)
 */
export function waitForNextHistogramCompute(page: Page) {
  return page.waitForRequest((r) =>
    r.url().includes('/analysis/histogram/') &&
    r.method() === 'POST' &&
    (r.postData() || '').includes('"params":['),
  )
}

/**
 * 在指定 tab 选文件**并等到新文件自己的计算请求完成**。
 *
 * 目标文件已是当前选中项时直接返回（选已选中项不触发新请求，等会超时）。
 * 之后仍应跟一次 waitLoadingGone 让计算响应落图。多选 tab 不适用（多选
 * 勾选不逐个触发计算）。
 */
export async function pickTabFileAndWaitCompute(
  page: Page,
  scope: 'single' | 'wafer' | 'correlation',
  labelSubstring?: string,
) {
  const before = (await filePicker(page, scope).innerText()).trim()
  if (labelSubstring && before.includes(labelSubstring)) return
  const computeP = waitForNextHistogramCompute(page)
  await pickTabFile(page, scope, labelSubstring)
  await computeP
}

/**
 * 确定性关闭某 tab 的文件选择器下拉（multiple 模式选中后 EP 保持开启）。
 *
 * 为什么不能只按一次 Escape：Escape 依赖焦点仍在 select 上——焦点不在时
 * 按键落空，popper 残留开会用 dp-file-option__meta 子树挡住后续对筛选区
 * 复选框/控件的点击（2026-09-07/08 两次被归为「flake」的本体，实测拦截；
 * 2026-09-08 专项清理）。Escape → 仍未关 → 点 tab 标题（click-outside）→
 * 最终以 hidden 断言兜底。locator 必须限定外层 .el-popper：popper-class
 * 同时挂在外层 popper 与内层 .el-select-dropdown 上，裸类名会 strict violation。
 */
export async function closeFilePopper(page: Page, scope: 'single' | 'wafer' | 'correlation' | 'multi') {
  const popper = page.locator(`.el-popper.dp-file-picker-${scope}`)
  for (let i = 0; (await popper.count()) > 0 && (await popper.isVisible()) && i < 3; i++) {
    await page.keyboard.press('Escape')
    await page.waitForTimeout(150)
    if (await popper.isVisible()) {
      await page.locator('.el-tabs__item.is-active').click()
      await page.waitForTimeout(150)
    }
  }
  await expect(popper).toBeHidden({ timeout: 5_000 })
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
 * 推进靠**本轮响应到达**而不是定时睡眠：旧实现未命中时每个参数都要烧满 3s
 * （8 个系统列 = 24s 纯等待），命中与未命中的代价差了一个数量级。
 */
export async function selectParamWithSpecLimits(page: Page, maxTries = 20): Promise<string | null> {
  let found: string | null = null
  // handler 已完整考虑过的 histogram POST 响应数（含非 200）。
  let settled = 0
  const handler = async (response: import('@playwright/test').Response) => {
    if (!response.url().includes('/analysis/histogram/')) return
    if (response.request().method() !== 'POST') return
    try {
      if (!found && response.status() === 200) {
        const body = await response.json()
        for (const [param, data] of Object.entries((body?.results ?? {}) as Record<string, any>)) {
          if (data?.lower_limit != null && data?.upper_limit != null) {
            found = param
            break
          }
        }
      }
    } catch { /* 非 JSON / 已销毁的响应，忽略 */ }
    settled++
  }
  page.on('response', handler)
  try {
    const params = await listParams(page)
    for (const p of params.slice(0, maxTries)) {
      if (found) break
      const before = settled
      await selectParam(page, p)
      // 必须保持响应驱动：见 waitForNextHistogramCompute 的注释——UI 在新响应到达前
      // 显示的是上一个参数的图表，退化成纯计时会把那个坑放回来。上一轮的迟到响应
      // 可能让这里提前一格通过，代价只是多探一个参数；found 只由真响应置位，不会误判。
      await expect
        .poll(() => settled > before || found !== null, { timeout: 10_000 })
        .toBe(true)
        .catch(() => { /* 这一轮没发出请求（非数值列等）：按未命中继续 */ })
    }
  } finally {
    page.off('response', handler)
  }
  return found
}

/** 序列分布图容器（SingleParamTab 内） */
const SERIAL_CANVAS = '.single-param-tab .serial-chart-wrapper div[_echarts_instance_]'

/**
 * 单文件分析页的四个图表开关。标签是**固定文案**（不随勾选状态变），所以
 * `getByText('显示QQ图').click()` 是「翻」而不是「开」；而它们**账号级持久**
 * （`analysis_chart_memory` 默认 true，组件 watch 到变化就写回 `analysis_chart_state`），
 * 于是「上一条用例把它点开了」会让本条的点击变成关掉 → 不发请求 → `waitForResponse` 超时。
 * 2026-10-13 全量实测 5 条用例同一形状（analysis.spec 箱线图数条 / axis-label-precision
 * QQ+箱线 / dock-resize enterAll / chart-filter-switches 柱宽 slider），`retries=2` 下
 * 表现为「这次点成关掉、重试就过」的 flake，`retries=0` 下就是硬红。
 */
const CHART_TOGGLE_LABELS = {
  hist: '显示直方图',
  serial: '显示序列分布',
  qq: '显示QQ图',
  box: '显示箱线图',
} as const

export type ChartToggleKey = keyof typeof CHART_TOGGLE_LABELS

function chartToggle(page: Page, key: ChartToggleKey): Locator {
  return page
    .locator('.single-param-tab .chart-toggles .el-checkbox')
    .filter({ hasText: CHART_TOGGLE_LABELS[key] })
    .first()
}

function isChartToggled(page: Page, key: ChartToggleKey): Promise<boolean> {
  return chartToggle(page, key).evaluate((el) => el.classList.contains('is-checked'))
}

/**
 * 把指定的几个图表开关**收敛**到目标状态（已是目标态就不点），返回被翻动过的键。
 * 用例要什么图就自己声明，别继承上一条用例或上一轮留下的状态。
 */
export async function ensureChartToggles(
  page: Page,
  want: Partial<Record<ChartToggleKey, boolean>>,
): Promise<ChartToggleKey[]> {
  const flipped: ChartToggleKey[] = []
  for (const key of Object.keys(CHART_TOGGLE_LABELS) as ChartToggleKey[]) {
    const target = want[key]
    if (target === undefined) continue
    if ((await isChartToggled(page, key)) !== target) {
      await chartToggle(page, key).click()
      flipped.push(key)
    }
    await expect.poll(() => isChartToggled(page, key), { timeout: 10_000 }).toBe(target)
  }
  return flipped
}

/**
 * 让 *key* 对应的图表**真的重新发一次请求**，并把那次响应交给调用方。
 *
 * 顺序是刻意的：先收敛到「关」（否则后面那一次点击可能是关掉而不是打开），
 * 再按 R2④ 注册 `waitForResponse`，最后才点到「开」——这样无论进来时它是开是关，
 * 拿到的都是本次的响应。
 */
export async function enableChartAndWait(
  page: Page,
  key: ChartToggleKey,
  predicate: (r: import('@playwright/test').Response) => boolean,
  timeout = 25_000,
): Promise<import('@playwright/test').Response> {
  await ensureChartToggles(page, { [key]: false })
  const pending = page.waitForResponse(predicate, { timeout })
  await ensureChartToggles(page, { [key]: true })
  return pending
}

/**
 * 打开「显示序列分布」并返回**这一次**的 serial_distribution 响应与 canvas。
 * 走 `enableChartAndWait` 而不是直接点（见上面那段注释）——2026-10-13 实测
 * `serial-overlap.spec.ts` 「按 Site 拆分」在文件内排第 4 时必红 40.4s、
 * 单独作为第 1 条跑则 12.2s 绿。收尾状态与旧实现一致（开着），不给后面留新携带。
 */
export async function openSerialDistribution(page: Page) {
  const resp = await enableChartAndWait(
    page,
    'serial',
    (r) =>
      r.url().includes('/analysis/serial_distribution/') &&
      r.request().method() === 'POST' &&
      r.status() < 500,
    30_000,
  )
  const canvas = page.locator(SERIAL_CANVAS).first()
  await expect(canvas).toBeVisible({ timeout: 20_000 })
  return { canvas, resp }
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
