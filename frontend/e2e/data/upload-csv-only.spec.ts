import { test, expect } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { gotoApp } from '../helpers/nav'
import { uploadFile } from '../helpers/upload'
import { makeZip } from '../helpers/zip'
import { cleanupQuiet, deleteBatchQuiet, deleteFilesByNameQuiet } from '../helpers/cleanup'

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
      // 只删临时 csv 会把 `col1,col2` 那一行 DataFile 留在共享 DB 里：它没有
      // Site 列，按 -created_at 排到最前后会被分析页自动选中，污染按文件推进的
      // 断言（R2③ 自建/自清）。
      await deleteFilesByNameQuiet(page, 'e2e_csv_only_')
      cleanupQuiet(tmpPath)
    }
  })

  test('ZIP 文件可以进入上传流程（不被拒绝）', async ({ page }) => {
    await gotoApp(page, '/data')

    const zipBase = `e2e_zip_ok_${Date.now()}`
    const zipPath = path.join(os.tmpdir(), `${zipBase}.zip`)
    makeZip(zipPath, [{ name: 'a.csv', content: '[GENERAL],\nTester_Type,CTA8290DPlus,\n[Data]\ncol1\nu1\nmin1\nmax1\n1\n' }])

    try {
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadFile(page, zipPath)

      // Should not show the rejection toast; zip upload proceeds normally.
      await expect(page.getByText(/不是 CSV 或 ZIP/)).not.toBeVisible({ timeout: 5_000 })
      await expect(page.getByText(/导入 1 个文件/)).toBeVisible({ timeout: 60_000 })
    } finally {
      // 同 zip-upload.spec.ts：`a.csv` 只有 col1、无 Site 列，留在库里就顶到
      // files[0] 被分析页自动选中，P0 冒烟随之挂。批次名 = zip 基础名。
      await deleteBatchQuiet(page, zipBase)
      cleanupQuiet(zipPath)
    }
  })
})
