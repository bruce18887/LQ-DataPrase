import { test, expect, type Page } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { PRIMARY_SAMPLE_FILE } from '../fixtures/test-data'
import { gotoApp } from '../helpers/nav'
import { uploadMultipleFiles, expectUploadSuccess } from '../helpers/upload'
import { cleanupQuiet, deleteFilesByNameQuiet } from '../helpers/cleanup'
import { loginAs } from '../helpers/auth'

/**
 * FIX-1：列表刷新不得吞掉刚勾选的行。
 * 旧实现整份替换 files[] 会清空 EP 内建 selection，工具栏 selectedCount 随之归零。
 * 判据不靠时序：等两行都可见后再勾，刷新完成后直接读按钮上的计数。
 */
const PREFIX = 'e2e_fix1_sel_'
let seq = 0
let paths: string[] = []

async function uploadSingles(page: Page, count: number): Promise<string[]> {
  const stamp = `${Date.now()}_${seq++}`
  const out: string[] = []
  for (let i = 0; i < count; i++) {
    const p = path.join(os.tmpdir(), `${PREFIX}${stamp}_${i}.csv`)
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, p)
    out.push(p)
  }
  const uploadVisible = await page.locator('.content-section:visible .upload-section').isVisible().catch(() => false)
  if (!uploadVisible) {
    await page.locator('button').filter({ hasText: '上传文件' }).click()
  }
  await uploadMultipleFiles(page, out)
  await expectUploadSuccess(page)
  paths.push(...out)
  return out
}

function rowByName(page: Page, name: string) {
  return page
    .locator('.content-section:visible .el-table .el-table__row')
    .filter({ hasText: name })
}

function bulkDeleteButton(page: Page) {
  return page.locator('button').filter({ hasText: /批量删除/ })
}

test.describe('文件列表刷新保留勾选', { tag: ['@p2', '@data'] }, () => {
  // 两条用例共用 PREFIX 前缀清理（afterAll 按前缀删 DB 行与磁盘文件），串行保证互不干扰。
  test.describe.configure({ mode: 'serial' })

  test.afterAll(async ({ browser }) => {
    for (const p of paths) cleanupQuiet(p)
    const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } })
    const page = await ctx.newPage()
    await loginAs(page, 'admin')
    await deleteFilesByNameQuiet(page, PREFIX)
    await ctx.close()
  })

  test('勾选 2 行后触发列表刷新，selectedCount 仍为 2', async ({ page }) => {
    test.skip(!fs.existsSync(PRIMARY_SAMPLE_FILE), '样例数据缺失，跳过')
    await gotoApp(page, '/data')
    const first = await uploadSingles(page, 2)
    for (const p of first) {
      await expect(rowByName(page, path.basename(p))).toBeVisible({ timeout: 15_000 })
    }
    for (const p of first) {
      await rowByName(page, path.basename(p)).locator('.el-checkbox').first().click()
    }
    await expect(bulkDeleteButton(page)).toContainText('批量删除 (2)')

    // 触发一次列表刷新：再上传 1 个文件 → filesVersion → loadFiles 整份替换。
    const extra = await uploadSingles(page, 1)
    await expect(rowByName(page, path.basename(extra[0]))).toBeVisible({ timeout: 15_000 })

    // FIX-1 正判据：刷新后 selectedCount 仍是 2（旧实现会回到「批量删除」无计数）。
    await expect(bulkDeleteButton(page)).toContainText('批量删除 (2)')
    // 用户可见的另一半：EP 内建的勾选框也真的还是勾上的（计数与画面不许各说各话）。
    await expect(page.locator('.content-section:visible .el-table .el-table__row .el-checkbox.is-checked')).toHaveCount(2)
  })

  test('搜索改变列表时清空勾选，避免批量删除看不见的行', async ({ page }) => {
    test.skip(!fs.existsSync(PRIMARY_SAMPLE_FILE), '样例数据缺失，跳过')
    await gotoApp(page, '/data')
    const uploaded = await uploadSingles(page, 2)
    for (const p of uploaded) {
      await expect(rowByName(page, path.basename(p))).toBeVisible({ timeout: 15_000 })
    }
    for (const p of uploaded) {
      await rowByName(page, path.basename(p)).locator('.el-checkbox').first().click()
    }
    await expect(bulkDeleteButton(page)).toContainText('批量删除 (2)')

    // 用户驱动的列表变化（搜索）必须清空勾选；只有 filesVersion 写后刷新才保留。
    await page.getByPlaceholder('按文件名/程序名/标签搜索').fill(path.basename(uploaded[0]))
    await expect(rowByName(page, path.basename(uploaded[1]))).toHaveCount(0, { timeout: 15_000 })
    await expect(bulkDeleteButton(page)).toBeDisabled()
    await expect(bulkDeleteButton(page)).not.toContainText('批量删除 (2)')
  })

  test('刷新失败时清空勾选，避免空表上仍可批量删除', async ({ page }) => {
    test.skip(!fs.existsSync(PRIMARY_SAMPLE_FILE), '样例数据缺失，跳过')
    await gotoApp(page, '/data')
    const uploaded = await uploadSingles(page, 2)
    for (const p of uploaded) {
      await expect(rowByName(page, path.basename(p))).toBeVisible({ timeout: 15_000 })
    }
    for (const p of uploaded) {
      await rowByName(page, path.basename(p)).locator('.el-checkbox').first().click()
    }
    await expect(bulkDeleteButton(page)).toContainText('批量删除 (2)')

    await page.route(/\/api\/v1\/files\/\?(.*&)?file_type=single/, (route) => route.abort())
    await uploadSingles(page, 1)
    await expect(bulkDeleteButton(page)).toBeDisabled({ timeout: 15_000 })
    await expect(page.locator('.content-section:visible .el-table .el-table__row')).toHaveCount(0, { timeout: 15_000 })
  })
})
