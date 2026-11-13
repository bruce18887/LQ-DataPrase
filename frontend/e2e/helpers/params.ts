import { expect, type Locator, type Page, type Response } from '@playwright/test'
import { capturedParamList, explainParamListCapture, type ParamListScope } from './paramList'

// 跨 tab 用例声明当前 scope 用（判据与分桶都在 paramList.ts，这里只把入口摆在用例常引的文件上）
export { setActiveAnalysisTab } from './paramList'
export type { ParamListScope } from './paramList'

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

/**
 * 当前**开着的那个**下拉里的选项。
 *
 * ⚠ popperClass 是**必填**的：2026-11-13 在真 /analysis 页 Escape 关参数下拉后逐帧采样，
 * `aria-hidden` 与 `display` 是**同一拍**翻转的（EP 源码里 ariaHidden 只在 onAfterLeave
 * 才翻回 true：`element-plus/es/components/tooltip/src/content.vue_vue_type_script_setup_true_lang.mjs:46-50,108`）：
 *   Escape+0ms   aria-hidden=false  display=block  ariaFalsePoppers=2  items=87
 *   Escape+30ms  aria-hidden=false  display=block  ariaFalsePoppers=2  items=267
 *   Escape+80ms  aria-hidden=false  display=block  ariaFalsePoppers=2  items=267
 *   Escape+160ms aria-hidden=true   display=none   ariaFalsePoppers=0  items=0
 * ⇒ 那个约 150ms 的 `el-zoom-in-top-leave-*` 窗口里，`:visible` 与 `[aria-hidden="false"]`
 * **一起脏**（两个判据数到的都是上一个下拉的 267 项），换判据本身并不更安全。
 * 真正起作用的是 `.el-popper.<popperClass>` 这层**每实例限定**：它让查询只能命中本控件
 * 自己的 popper，正在退出的别人家的 popper 根本不进候选。
 * 所以别把 `aria-hidden` 当「哪一个下拉开着」的判据抄走 —— 去掉 popperClass 就是原 bug。
 * 仓内旁证（窗口量级）：`frontend/e2e/data/file-correlation.spec.ts:31` 早就用
 * `page.waitForTimeout(600)` 睡眠躲同一个坑。
 * popper-class 挂在**外层 .el-popper** 上（`el-select-v2` 也只挂这一层：它的内层
 * `.el-select-dropdown` 不再复制 popperClass，见 `select-v2/src/select-dropdown.mjs:155`
 * 的 class 绑定里没有它 —— v1 的 `select/src/select-dropdown.mjs:10` 才有那一份）。
 * 所以限定必须落在外层 `.el-popper`，两条路都只有一处可落；裸类名会 strict violation。
 */
function visibleOptions(page: Page, popperClass: string) {
  return page.locator(`.el-popper.${popperClass}[aria-hidden="false"] .el-select-dropdown__item`)
}

/**
 * ParamSelector 单文件实例的 popper 身份串 —— e2e 侧只有这一份。
 *
 * 它是 `ParamSelector.vue` 里 `popperClass` 的默认值（产品侧的事实）。以前 helper 的
 * `selectParam` 与直接查虚拟窗口的用例各内联一份，产品改默认值时两处静默失配 ——
 * 红法会从「定位不到」变成「匹配到隐藏面板」那种看不出根因的。多文件 tab 是另一个
 * 实例（`dp-param-popper-multi`），不归本常量管。
 */
export const PARAM_POPPER_SINGLE = 'dp-param-popper-single'

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
  const options = page.locator(
    `.el-popper.dp-file-picker-${scope}[aria-hidden="false"] .el-select-dropdown__item`,
  )
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
  await page.locator(
    `.el-popper.dp-outlier-popper-${scope}[aria-hidden="false"] .el-select-dropdown__item`,
  ).filter({ hasText: mode }).first().click()
}

/** 选敏感度档位（如「宽松 (3.0x IQR)」） */
export async function pickSensitivity(page: Page, label: string, scope = 'single') {
  await openElSelect(filterControl(page, 'iqr-multiplier'))
  await page.locator(
    `.el-popper.dp-iqr-popper-${scope}[aria-hidden="false"] .el-select-dropdown__item`,
  ).filter({ hasText: label }).first().click()
}

/**
 * 分析页指定 tab（scope）当前这一发已结算的**全部参数名**（后端返回顺序）。
 *
 * 旧实现是「打开下拉 → 数 DOM 选项 → Escape」，在 `el-select` 时代等于全集（因为渲染被
 * 截断到 300，而测试文件都少于 300 项）；迁 `el-select-v2` 后 DOM 只有虚拟窗口那约 8 行，
 * 数 DOM 就不再是「列表有多少项」的判据。改成读产品取全集用的同一次响应（见 paramList.ts）。
 *
 * 轮询的条件不是「长度 > 0」而是「**这一发已结算**」（2026-11-13 复审 C-1/C-2）：
 * 旧条件在两种真实形状下都立刻通过 —— ① 同文件换口径（勾选开关 → `useTabFileParams.ts:131-133`
 * 的 250ms 防抖重发，file_id 不变 seq 变）时它当场返回上一个口径的列表，把调用方的
 * 「列表收缩了」断言变成恒真；② 当前口径真返回 0 项时它死等 15s，然后把上一份列表当现值给出去。
 * 超时消息现在由 `paramListCore.explainCapture` 打全四个量（captured.seq / lastFast.seq /
 * 两侧 fileId / keys 数），四个成因（没选文件、监听装晚了、换口径未落地、真·空集）分得开。
 *
 * **空数组是合法结果**（当前口径 0 项）：要非空的用例自己断 `length`；反过来，断言
 * 「列表收缩 / 保持不变」的用例必须先等到新口径那一发**已结算**再读，否则读到的还是
 * 上一个口径。仓内范式：chart-filter-switches 的「仅显示Fail测试项 / 仅显示低CPK项」
 * 与「全 Pass 文件（Gage）」两条，都在勾选**之前**注册不带 params 的快路径
 * waitForResponse（该文件 :88-103 的形状），然后才 listParams。
 *
 * scope 缺省 'single'（首屏唯一非 lazy 的 pane）。跨 tab 用例必须**在点 tab 之前**调
 * `setActiveAnalysisTab` —— 单文件与相关性两个 tab 的快路径请求体键集逐字相同、产品没在
 * 请求里留 tab 身份，helper 无法自己分辨那两者（见 paramList.ts 顶部）。
 *
 * **导出工具 tab 不走这里**，那页的取法见 `paramKeysFromHistogram`：它发的是 `{file_id, params: []}`，
 * 被 `paramListCore.ts:67` 判成「算某个参数」而不是「拉全集」，原理上就进不了这台捕获器（别硬套）。
 */
export async function listParams(page: Page, scope: ParamListScope = 'single'): Promise<string[]> {
  await expect
    .poll(() => explainParamListCapture(page, scope), {
      timeout: 15_000,
      message:
        `参数全集这一发未结算（scope=${scope}）。Received 行是诊断：未发出 / 未处理 / 未结算 ` +
        '三态 + captured.seq / lastFast.seq / 两侧 fileId / keys 数；判据见 paramList.ts 与 paramListCore.ts',
    })
    .toMatch(/^settled/)
  const keys = capturedParamList(page, scope)
  if (keys === null) {
    // 唯一走到这里的方式：轮询刚通过、读之前又发出了一发新口径。宁可喊，不吐旧口径。
    throw new Error(
      `listParams：轮询刚过、读时又未结算（scope=${scope}）—— 期间又有新口径发出。` +
        `诊断：${explainParamListCapture(page, scope)}`,
    )
  }
  return keys
}

/**
 * 参数全集 = **调用方自己注册的那发 histogram 响应**的 `results` 键。
 *
 * 给「不归 `paramList.ts` 那台捕获器管」的页面用（目前只有导出工具 tab，见
 * `e2e/exports/exports.spec.ts` 的 Export Tools 两条用例）：捕获器把**带 `params` 的请求**判成
 * 「算某个参数」而不是「拉全集」（`paramListCore.ts:67`），而导出页发的正是
 * `{file_id, params: []}`（`ExportToolsTab.vue:77`）⇒ 永远进不了那个桶，且它的 scope
 * 只覆盖分析页的三个 tab。
 *
 * 口径与产品逐字一致：`ExportToolsTab.vue:78` 就是 `Object.keys(data.results || {})`，
 * **不做 trim 过滤** —— 导出页页头那句 `共 M 个` 数的正是这个长度，加过滤就对不上；
 * 分析页相反，它自己先按 `useTabFileParams.ts:87` 的 `p.trim() !== ''` 洗过，所以那边走 `listParams`。
 */
export async function paramKeysFromHistogram(resp: Promise<Response | null>): Promise<string[]> {
  const r = await resp
  if (!r) {
    // 和 listParams 同一条纪律（宁可红也不吐空值）：`[]` 只留给「响应真的 200 且 results 为空」。
    // 这里 null 的唯一来源是调用方那发 waitForResponse 超时/注册晚了 ⇒ 用例接线坏了，
    // 伪装成「这个文件没有参数」会让上层 test.skip 把判据静默删掉。
    throw new Error(
      'paramKeysFromHistogram：没拿到 histogram 响应 ⇒ 用例接线坏了（waitForResponse 超时或注册晚于点击），' +
        '不是「这个文件没有参数」。见 R2④：注册必须先于触发点击。',
    )
  }
  const body = (await r.json()) as Record<string, unknown>
  return Object.keys((body?.results ?? {}) as Record<string, unknown>)
}

/**
 * 从参数全集造一个**匹配数 ∈ [2, cap]** 的关键词，供「输入关键词 → Enter 全选」选中一小撮参数。
 *
 * 前缀越短匹配越多（单调），所以从短往长试，第一个落进区间的就是答案；只试前 12 个名字，
 * 不在上千项的全集上做全量扫描。参数名与匹配数全部来自**响应**而不是 DOM —— 迁 `el-select-v2`
 * 之后 DOM 里只有虚拟窗口那约 11 行，「数选项条数」与「按位置点第 i 行」都不再是合法判据形状
 * （2026-11-13 批1 Task 8）。匹配规则这里是本地一行 `includes`，**没有**复用 src 的
 * `filterByKeyword`：判据要与实现异源，否则产品把过滤写坏时这条跟着一起绿。
 */
export function pickBoundedKeyword(all: string[], cap: number): { kw: string; count: number } | null {
  for (const name of all.slice(0, 12)) {
    for (let len = 1; len <= name.length; len++) {
      const kw = name.slice(0, len).toLowerCase()
      const count = all.filter((p) => p.toLowerCase().includes(kw)).length
      if (count >= 2 && count <= cap) return { kw, count }
      if (count < 2) break
    }
  }
  return null
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
  const options = visibleOptions(page, PARAM_POPPER_SINGLE)
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
 * 单文件分析页的五个图表开关。标签是**固定文案**（不随勾选状态变），所以
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
  site3d: '显示3D柱状图',
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
