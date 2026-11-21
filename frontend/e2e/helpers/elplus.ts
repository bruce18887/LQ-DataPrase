import { type Locator, type Page } from '@playwright/test'

/**
 * Element Plus 通用交互助手。
 * EP 2.14 的 el-select 占位符是 <span class="el-select__placeholder">，不是 input[placeholder]，
 * 因此用占位文本过滤 .el-select 容器来定位（未选中时占位文本可见）。
 */

/** 按占位文本定位 el-select 容器（可限定 scope） */
export function elSelectByPlaceholder(scope: Page | Locator, placeholder: string): Locator {
  return scope.locator('.el-select').filter({ hasText: placeholder })
}

/**
 * `SerialSelector`（相关性页「对比序列」）的下拉面板**实例级** class。
 *
 * 它是组件上 `popper-class` 的字面值（产品侧事实，见
 * `src/pages/data/components/correlation/SerialSelector.vue`），两边必须同步改。
 * 与 `helpers/params.ts` 的 `PARAM_POPPER_SINGLE` 同族：身份串不内联进用例。
 */
export const SERIAL_POPPER = 'dp-serial-popper'

/**
 * `TestColumnSelector`（查看数据页「显示测试列」）下拉面板的**实例级** class。
 *
 * 与 `SERIAL_POPPER` 同族：它是组件上 `popper-class` 的字面值（产品侧事实，见
 * `src/pages/data/components/browser/TestColumnSelector.vue`），两边必须同步改，
 * 用例里不内联身份串。查看数据页上共用 `.el-select-dropdown` 这套类名的实例共 6 个
 * （本控件 + `DataBrowserToolbar.vue` 那四个：Pass/Fail / Site / 列宽 三颗 `el-select`
 * 与「固定列」那颗 `el-select-v2`（下面的 `PIN_COL_POPPER`）+ 横幅的 FileSelect，
 * 见 `ActiveFileBanner.vue:12`），而 `e2e/data/view-data.spec.ts` 里
 * 「@p2 显示测试列：切换文件后选中集重置为全部显示」那条用例（锚点 `1574012`，本文件只按标题认它）
 * 在同一次交互里先开「显示测试列」再开横幅下拉：收起那 ~150ms 的 leave 过渡帧里
 * `:visible` 与 `[aria-hidden="false"]` 一起脏（机理见下面 `visibleSelectOptions`），
 * 所以本控件的选项与 footer 一律按实例取，不赌「这次没有别的面板正在退场」。
 */
export const COL_POPPER = 'dp-col-popper'

/**
 * `ExportParamSelector`（导出工具「选择参数」）下拉面板的**实例级** class。
 *
 * 与 `SERIAL_POPPER` / `COL_POPPER` 同族：它是组件上 `popper-class` 的字面值（产品侧事实，见
 * `src/pages/data/components/export/ExportParamSelector.vue`），两边必须同步改，用例里不内联身份串。
 * 导出工具 tab 自己就有 3 个落进 `.el-select-dropdown` 这套类名的实例（本控件 +
 * `ExportActions.vue:11` 的 Sigma 下拉 + 文件横幅的 FileSelect，见 `ActiveFileBanner.vue:5-13`），
 * 而「批量导出」那条用例在同一次交互里先开横幅选文件、再开本控件
 * （`e2e/exports/exports.spec.ts` 的横幅点击与参数下拉点击）：收起那 ~150ms 的 leave 过渡里
 * `:visible` 与 `[aria-hidden="false"]` 一起脏（机理见上面 `visibleSelectOptions`），
 * 所以本控件的选项与 footer 从 Task 8 起一律按实例取，不赌「这次没有别的面板正在退场」。
 */
export const EXPORT_PARAM_POPPER = 'dp-export-param-popper'

/**
 * `DataBrowserToolbar` 的「固定列」下拉面板的**实例级** class（2026-11-13 批1 Task 9C）。
 *
 * 与上面三个同族、同理由：它是组件上 `popper-class` 的字面值（产品侧事实，见
 * `src/pages/data/components/browser/DataBrowserToolbar.vue`），两边必须同步改，用例里不内联
 * 身份串。本控件是查看数据页那 6 个共用 `.el-select-dropdown` 类名的实例之一（清单见
 * `COL_POPPER` 的注释），而它自己那两条用例都在「开固定列下拉 → 点选项 → 看表格」上，
 * 全局 `:visible` 在收起的 leave 过渡帧里会挑中正在退出的上一个面板。
 */
export const PIN_COL_POPPER = 'dp-pin-col-popper'

/** 相关性 X/Y 下拉面板的实例级 class（`CorrelationToolsTab.vue` 的 `popper-class` 字面值）。 */
export const CORR_X_POPPER = 'dp-corr-x-popper'
export const CORR_Y_POPPER = 'dp-corr-y-popper'

/**
 * 当前可见下拉选项。
 *
 * ⚠ 这是**全局**查询，同名 popper 有多份实例时不保险（隐藏 tab / 同页其它下拉）：
 * 收起那 ~150ms 的 leave 过渡帧里 `:visible` 与 `[aria-hidden="false"]` **一起脏**，
 * 会挑中正在退出的上一个面板，reference 零尺寸还会让 popper 逐帧重定位、`.first()`
 * 点到别家的选项（2026-11-13 Task 4/5 实测，采样表见 `helpers/params.ts:28-49`）。
 * **唯一有效的隔离是实例级 popper-class** —— 新用例别用本函数查跨控件的选项，
 * 用下面的 `popperOf(page, <实例级类名>)`（那条谓词只在那一处写，别再内联第三份）。
 *
 * 消费者口径（2026-11-21 `grep -rn visibleSelectOptions e2e src test` 现数）：
 * 直接调用是 `e2e/data/file-correlation.spec.ts` 6 处 + 本文件的 `pickOption` 1 处 /
 * `pickOptionByKeyword` 1 处；`e2e/analysis/{analysis,axis-label-precision,correlation-file-switch-reset}.spec.ts`
 * 已改经 `pickOptionByKeyword` 间接使用，不再各自直调。
 */
export function visibleSelectOptions(page: Page): Locator {
  return page.locator('.el-select-dropdown__item:visible')
}

/**
 * **本控件自己的**下拉面板（`.el-popper.<实例级 class>[aria-hidden="false"]`）。
 *
 * `visibleSelectOptions` 那条全局查询的唯一解药就是这里传的 `popperClass`，它必须来自
 * 组件模板上的 `popper-class`（`COL_POPPER` / `SERIAL_POPPER` / `EXPORT_PARAM_POPPER` /
 * `PIN_COL_POPPER` / `PARAM_POPPER_SINGLE`（在 `helpers/params.ts`）/ `CORR_X_POPPER` /
 * `CORR_Y_POPPER` 就是这些身份串，产品侧改类名时用例侧只改这里）。谓词只用 `[aria-hidden="false"]`
 * 一种写法（2026-11-13 订正第 4 条）：写成 `:not([aria-hidden="true"])` 的话，EP 换了
 * 绑定方式只会红一半，根因看不出来。
 *
 * ⚠ `popper-class` 在 v2 里**不只挂下拉那一份 popper**：`select-v2/src/select.mjs:117` 把它同样给
 * `collapse-tags` 的溢出标签 tooltip（`tagTooltip?.popperClass ?? popperClass`）。五颗里**四颗**命中
 * （现跑 `grep -rn "^[[:space:]]*collapse-tags$" frontend/src` = Serial / TestColumn / Export /
 * DataBrowserToolbar 固定列，只有单选的 ParamSelector 没有）⇒ 这四个 class 都可能同时存在于两份
 * `.el-popper` 上，眼下靠同文件 `:108` 的 `disabled: dropdownMenuVisible` 让两者不同时可见。哪天这条
 * 报 strict violation，**别改成 `.first()`**（那是把身份判据降级成位置判据），给 tooltip 传
 * `:tag-tooltip.popper-class`。另两颗带 `:collapse-tags` 动态绑定的（`FileSelect.vue:7`、
 * `AnalysisFilePicker.vue:9`）是 v1 且**没有实例级 popperClass**，不在本谓词的管辖面内。
 */
export function popperOf(page: Page, popperClass: string): Locator {
  return page.locator(`.el-popper.${popperClass}[aria-hidden="false"]`)
}

/** 打开某占位文本的 select 并选择含指定文本的选项 */
export async function pickOption(
  page: Page,
  selectPlaceholder: string,
  optionText: string,
  scope: Page | Locator = page,
) {
  await elSelectByPlaceholder(scope, selectPlaceholder).first().click()
  await visibleSelectOptions(page).filter({ hasText: optionText }).first().click()
}

/** 打开下拉 → 在过滤 input 输入关键词 → 点命中项；popperClass 给实例级面板时按实例取选项。 */
export async function pickOptionByKeyword(
  page: Page,
  selectPlaceholder: string,
  keyword: string,
  scope: Page | Locator = page,
  popperClass?: string,
) {
  const select = elSelectByPlaceholder(scope, selectPlaceholder).first()
  await select.click()
  await select.locator('input').first().fill(keyword)
  const options = popperClass
    ? popperOf(page, popperClass).locator('.el-select-dropdown__item')
    : visibleSelectOptions(page)
  await options.filter({ hasText: keyword }).first().click()
}

/** 点击 ElMessageBox 确认框的主按钮（兼容“确定/OK/删除”等不同文案） */
export async function confirmMessageBox(page: Page) {
  const box = page.locator('.el-message-box')
  await box.locator('.el-message-box__btns .el-button--primary').click()
}
