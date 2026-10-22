import type { Page } from '@playwright/test'
import { expect } from '@playwright/test'
import { gotoApp } from './nav'

/**
 * 进入查看数据 tab：文件列表服务端搜索定位目标文件 → 点「查看」。
 * 服务端 search 不受分页/下拉时序影响，比 banner 下拉更稳。
 *
 * 注意语义：**内含整页 gotoApp**，所以它会把「查看数据」的多文件标签列表重置回
 * 一个空白标签。要在同一个页面里再开第二个文件，用下面的 `openFileInViewTab`。
 */
export async function openViewTab(page: Page, filename: string) {
  await gotoApp(page, '/data')
  // 文件列表搜索（300ms debounce 后发请求）
  const searchInput = page.locator('input[placeholder="按文件名/程序名/标签搜索"]')
  await searchInput.fill(filename.slice(0, 15))
  // 注意：长文件名在行内 DOM 中被中间截断（如 BPD93204_FT1_ET…50_12252024.csv），
  // hasText 必须用前缀匹配而非完整文件名
  const row = page.locator('.el-table .el-table__row').filter({ hasText: filename.slice(0, 12) }).first()
  await expect(row).toBeVisible({ timeout: 30_000 })
  await row.locator('button').filter({ hasText: '查看' }).click()
  await expect(page.locator('.tab-btn.active')).toContainText('查看数据')
  await expect(page.locator('.ag-root').first()).toBeVisible({ timeout: 30_000 })
}

/**
 * 在**同一页面内**从文件列表再开一个文件到标签页。
 *
 * 不能用 gotoApp：整页重载会把标签列表重置回一个空白页，那就根本测不到多标签。
 *
 * 后端语义（`DataManagement.vue` 的 `viewFile`）：同一个 fileId 不会有两个标签，
 * 「+」开出的空白标签会被那次「查看」填上；所以第 2..N 个标签必须给**不同**的文件。
 */
export async function openFileInViewTab(page: Page, filename: string) {
  await page.locator('.tab-btn').filter({ hasText: '文件列表' }).first().click()
  const searchInput = page.locator('input[placeholder="按文件名/程序名/标签搜索"]')
  await searchInput.fill(filename.slice(0, 15))
  const row = page
    .locator('.el-table .el-table__row')
    .filter({ hasText: filename.slice(0, 12) })
    .first()
  await expect(row).toBeVisible({ timeout: 30_000 })
  await row.locator('button').filter({ hasText: '查看' }).click()
  await expect(page.locator('.tab-btn.active')).toContainText('查看数据')
}
