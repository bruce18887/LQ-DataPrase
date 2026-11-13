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
 * 当前可见下拉选项。
 *
 * 传 `popperClass` 时限定在该控件**自己的** popper 内（谓词与 `helpers/params.ts` 的
 * `visibleOptions` 逐字相同：`.el-popper.<cls>[aria-hidden="false"]`）——同名 popper
 * 有多份实例时（隐藏 tab / 本页其它下拉），收起那 ~150ms leave 过渡帧里
 * `:visible` 与 `[aria-hidden="false"]` **一起脏**，会挑中正在退出的上一个面板，
 * reference 零尺寸还会让 popper 逐帧重定位、`.first()` 点到别家的选项。
 * **唯一有效的隔离是实例级 popper-class**（2026-11-13 Task 4/5 实测，详见
 * `helpers/params.ts:28-49` 的采样表）。
 *
 * 不传时保持旧的全局 `:visible` 行为：现有 6 个消费者文件仍按旧形状跑，
 * 给它们逐个补类名是本批收口的专项，不在本次改动面内。
 */
export function visibleSelectOptions(page: Page, popperClass?: string): Locator {
  if (popperClass) {
    return page.locator(
      `.el-popper.${popperClass}[aria-hidden="false"] .el-select-dropdown__item`,
    )
  }
  return page.locator('.el-select-dropdown__item:visible')
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

/** 点击 ElMessageBox 确认框的主按钮（兼容“确定/OK/删除”等不同文案） */
export async function confirmMessageBox(page: Page) {
  const box = page.locator('.el-message-box')
  await box.locator('.el-message-box__btns .el-button--primary').click()
}
