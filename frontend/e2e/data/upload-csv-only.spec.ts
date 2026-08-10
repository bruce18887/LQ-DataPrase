import { test, expect } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { gotoApp } from '../helpers/nav'
import { uploadFile } from '../helpers/upload'
import { makeZip } from '../helpers/zip'
import { cleanupQuiet } from '../helpers/cleanup'

test.describe('上传限制：仅 CSV 与 ZIP', { tag: ['@p2', '@data'] }, () => {
  test('非 CSV/ZIP 文件会被前端拒绝并给出提示', async ({ page }) => {
    await gotoApp(page, '/data')

    const tmpPath = path.join(os.tmpdir(), `e2e_non_csv_${Date.now()}.xlsx`)
    fs.writeFileSync(tmpPath, 'fake xlsx content')

    try {
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadFile(page, tmpPath)

      // The upload should be rejected by the before-upload hook.
      await expect(page.getByText(/不是 CSV 或 ZIP/)).toBeVisible({ timeout: 10_000 })
    } finally {
      // Edge 浏览器可能短暂持有文件句柄（Windows 文件锁），重试删除
      cleanupQuiet(tmpPath)
    }
  })

  test('CSV 文件可以正常进入上传流程', async ({ page }) => {
    await gotoApp(page, '/data')

    const uniqueName = `e2e_csv_only_${Date.now()}.csv`
    const tmpPath = path.join(os.tmpdir(), uniqueName)
    fs.writeFileSync(tmpPath, 'col1,col2\n1,2\n')

    try {
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadFile(page, tmpPath)

      // Should not show the CSV-only rejection toast.
      await expect(page.getByText(/不是 CSV 或 ZIP/)).not.toBeVisible({ timeout: 5_000 })
    } finally {
      cleanupQuiet(tmpPath)
    }
  })

  test('ZIP 文件可以进入上传流程（不被拒绝）', async ({ page }) => {
    await gotoApp(page, '/data')

    const zipPath = path.join(os.tmpdir(), `e2e_zip_ok_${Date.now()}.zip`)
    makeZip(zipPath, [{ name: 'a.csv', content: '[GENERAL],\nTester_Type,CTA8290DPlus,\n[Data]\ncol1\nu1\nmin1\nmax1\n1\n' }])

    try {
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadFile(page, zipPath)

      // Should not show the rejection toast; zip upload proceeds normally.
      await expect(page.getByText(/不是 CSV 或 ZIP/)).not.toBeVisible({ timeout: 5_000 })
      await expect(page.getByText(/导入 1 个文件/)).toBeVisible({ timeout: 60_000 })
    } finally {
      cleanupQuiet(zipPath)
    }
  })
})
