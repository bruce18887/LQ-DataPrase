import { expect, type Page } from '@playwright/test'

/**
 * 表头筛选（ColumnHeaderFilter）e2e 交互：
 * 每个筛选组件常驻自己的 popper（未打开时 aria-hidden），定位必须用 :visible
 * 筛出已打开的，不能 .first()（DOM 顺序第一个恒是关着的 popper）。
 */

/** 打开某列表头的筛选 popover（testid: filename/product/format/program/tag） */
export async function openHeaderFilter(page: Page, testid: string) {
  await page.locator(`[data-testid="col-filter-btn-${testid}"]`).click()
  // 已打开的 popper 可见；任一 popper 打开即算成功
  await expect(page.locator('.col-filter-popper:visible').first()).toBeVisible({ timeout: 5_000 })
}

/** 在已打开的筛选 popover 的下拉中选择指定值（R4：点 wrapper → 可见选项） */
export async function selectHeaderFilterOption(page: Page, testid: string, value: string) {
  const select = page.locator(`.col-filter-popper:visible [data-testid="col-filter-select-${testid}"]`)
  await select.locator('.el-select__wrapper').waitFor({ state: 'visible', timeout: 5_000 })
  await select.locator('.el-select__wrapper').click()
  await page
    .locator('.el-select-dropdown__item:visible')
    .filter({ hasText: value })
    .first()
    .click()
}
