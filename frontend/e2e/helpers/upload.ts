import { expect, type Page } from '@playwright/test'

/**
 * 在「数据管理 → 上传文件」页通过隐藏的 <input type=file> 上传单个文件。
 * el-upload 的真实 input 被隐藏，直接用 setInputFiles 注入。
 */
export async function uploadFile(page: Page, filePath: string) {
  const input = page.locator('input[type="file"]')
  await expect(input).toHaveCount(1, { timeout: 10_000 })
  await input.setInputFiles(filePath)
}

/**
 * 上传多个文件（el-upload multiple 模式）
 */
export async function uploadMultipleFiles(page: Page, filePaths: string[]) {
  const input = page.locator('input[type="file"]')
  await expect(input).toHaveCount(1, { timeout: 10_000 })
  await input.setInputFiles(filePaths)
}

/** 等待上传成功提示（ElMessage toast） */
export async function expectUploadSuccess(page: Page, timeout = 60_000) {
  await expect(page.getByText(/上传成功|解析成功|成功/).first()).toBeVisible({ timeout })
}
