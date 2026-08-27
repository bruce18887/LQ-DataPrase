import { test, expect, type Page } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { PRIMARY_SAMPLE_FILE } from '../fixtures/test-data'
import { gotoApp } from '../helpers/nav'
import { uploadMultipleFiles, expectUploadSuccess } from '../helpers/upload'
import { cleanupQuiet } from '../helpers/cleanup'

/**
 * 组合功能（2026-08-29 需求 2）：勾选多个单文件 → 组合为批次
 * → 文件从单文件列表消失、批次 Tab 出现 → 删除批次后数据清理。
 *
 * 注意：组合是物理移动（batch/<名称>/），删除批次 = 删除磁盘 + DB 记录，
 * 因此测试以「删除批次」收尾即完成清理。
 */

test.describe('数据管理 → 组合为批次', { tag: ['@p2', '@data'] }, () => {
  test('@p2 勾选两个单文件组合为批次 → 批次 Tab 可见 → 删除批次恢复', async ({ page }) => {
    test.skip(!fs.existsSync(PRIMARY_SAMPLE_FILE), '样例数据缺失，跳过')

    const ts = Date.now()
    const name1 = `e2e_cmb_${ts}_a.csv`
    const name2 = `e2e_cmb_${ts}_b.csv`
    const batchName = `E2E_CMB_${ts}`
    const tmp1 = path.join(os.tmpdir(), name1)
    const tmp2 = path.join(os.tmpdir(), name2)
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, tmp1)
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, tmp2)

    await gotoApp(page, '/data')

    try {
      // 上传两个单文件
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadMultipleFiles(page, [tmp1, tmp2])
      await expectUploadSuccess(page)

      for (const name of [name1, name2]) {
        await expect(
          page.locator('.el-table .el-table__row').filter({ hasText: name }),
        ).toBeVisible({ timeout: 15_000 })
      }

      // 勾选两行（selection 列 checkbox；R4：点容器元素）
      for (const name of [name1, name2]) {
        await page
          .locator('.el-table .el-table__row')
          .filter({ hasText: name })
          .locator('.el-checkbox')
          .first()
          .click()
      }

      // 点击「组合为批次」→ 录入批次名 → 确认
      const combineBtn = page.locator('button').filter({ hasText: '组合为批次' })
      await expect(combineBtn).toBeEnabled({ timeout: 5_000 })
      await combineBtn.click()
      const promptInput = page.locator('.el-message-box__input input')
      await expect(promptInput).toBeVisible({ timeout: 10_000 })
      await promptInput.fill(batchName)
      await page.locator('.el-message-box__btns button').filter({ hasText: '组合' }).click()

      // 成功提示 + 单文件列表不再包含这两个文件
      await expect(page.getByText(`已组合 2 个文件为批次 "${batchName}"`).first())
        .toBeVisible({ timeout: 20_000 })
      for (const name of [name1, name2]) {
        await expect(
          page.locator('.el-table .el-table__row').filter({ hasText: name }),
        ).toHaveCount(0, { timeout: 15_000 })
      }

      // 批次 Tab：批次出现且含 2 个文件
      await page.locator('.tabs-nav .tab-btn').filter({ hasText: '批次数据' }).click()
      await expect(page.locator('.tab-btn.active')).toContainText('批次数据')
      const header = page.locator(`[data-testid="batch-header-${batchName}"]`)
      await expect(header).toBeVisible({ timeout: 15_000 })
      await expect(header.locator('.batch-count')).toHaveText('2 个文件')
      await header.click()
      const tags = page.locator(`[data-testid="batch-files-${batchName}"] .batch-file-tag`)
      await expect(tags).toHaveCount(2, { timeout: 10_000 })

      // 删除批次（即清理本用例数据）
      await header.locator('button').filter({ hasText: '删除批次' }).click()
      const confirmBtn = page.locator('.el-message-box').getByRole('button', { name: '删除', exact: true })
      await expect(confirmBtn).toBeVisible({ timeout: 10_000 })
      await confirmBtn.click()
      await expect(page.getByText(`批次 "${batchName}" 已删除`).first()).toBeVisible({ timeout: 15_000 })
      await expect(header).toBeHidden({ timeout: 10_000 })
    } finally {
      cleanupQuiet(tmp1)
      cleanupQuiet(tmp2)
    }
  })
})
