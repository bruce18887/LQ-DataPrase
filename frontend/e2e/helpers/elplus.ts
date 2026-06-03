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

/** 当前可见下拉选项 */
export function visibleSelectOptions(page: Page): Locator {
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
