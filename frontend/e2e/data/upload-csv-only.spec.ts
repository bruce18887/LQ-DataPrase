import { test, expect } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { gotoApp } from '../helpers/nav'
import { uploadFile } from '../helpers/upload'

test.describe('上传限制：仅 CSV', { tag: ['@p2', '@data'] }, () => {
  test('非 CSV 文件会被前端拒绝并给出提示', async ({ page }) => {
    await gotoApp(page, '/data')

    const tmpPath = path.join(os.tmpdir(), `e2e_non_csv_${Date.now()}.xlsx`)
    fs.writeFileSync(tmpPath, 'fake xlsx content')

    try {
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadFile(page, tmpPath)

      // The upload should be rejected by the before-upload hook.
      await expect(page.getByText(/不是 CSV 文件/)).toBeVisible({ timeout: 10_000 })
    } finally {
      fs.rmSync(tmpPath, { force: true })
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
      await expect(page.getByText(/不是 CSV 文件/)).not.toBeVisible({ timeout: 5_000 })
    } finally {
      fs.rmSync(tmpPath, { force: true })
    }
  })
})
