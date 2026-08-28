import { test, expect } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { gotoApp } from '../helpers/nav'
import { uploadFile } from '../helpers/upload'
import { makeZip } from '../helpers/zip'
import { cleanupQuiet } from '../helpers/cleanup'

/** 最小可解析 CTA8290D CSV（marker + 表头/单位/下限/上限 + 数据行） */
const MIN_CSV = [
  '[GENERAL],',
  'Tester_Type,CTA8290DPlus,',
  '[Data]',
  'col1,col2',
  'u1,u2',
  'min1,min2',
  'max1,max2',
  '1,2',
  '3,4',
  '',
].join('\n')

/** 批次区已从文件列表 Tab 独立为「批次数据」Tab */
async function gotoBatchTab(page: import('@playwright/test').Page) {
  const batchTab = page.locator('.tabs-nav .tab-btn').filter({ hasText: '批次数据' })
  await batchTab.click()
  await expect(page.locator('.tab-btn.active')).toContainText('批次数据')
}

test.describe('ZIP 压缩包上传：自动解析为批次数据', { tag: ['@p2', '@data'] }, () => {
  test('ZIP 上传成功 → 提示导入数量 → 批次区出现对应批次', async ({ page }) => {
    await gotoApp(page, '/data')

    const zipBase = `e2e_zip_ok_${Date.now()}`
    const zipPath = path.join(os.tmpdir(), `${zipBase}.zip`)
    makeZip(zipPath, [
      { name: 'root.csv', content: MIN_CSV },
      { name: 'sub/below.csv', content: MIN_CSV },
      { name: 'readme.txt', content: 'ignored' },
    ])

    try {
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadFile(page, zipPath)

      // 成功 toast 显示 zip 导入的文件数（2 个 csv，txt 被忽略）
      await expect(page.getByText(/导入 2 个文件/)).toBeVisible({ timeout: 60_000 })

      await gotoBatchTab(page)

      // 批次区出现该批次，header 显示文件数
      const header = page.locator(`[data-testid="batch-header-${zipBase}"]`)
      await expect(header).toBeVisible({ timeout: 15_000 })
      await expect(header.locator('.batch-count')).toHaveText('2 个文件')

      // 展开批次 → 2 个文件（表格行；含子批次列）
      await header.click()
      const files = page.locator(`[data-testid="batch-files-${zipBase}"] .batch-file-row`)
      await expect(files).toHaveCount(2, { timeout: 10_000 })
      await expect(files.filter({ hasText: 'below.csv' })).toBeVisible()
      await expect(files.filter({ hasText: 'root.csv' })).toBeVisible()
    } finally {
      cleanupQuiet(zipPath)
    }
  })

  test('ZIP 内无 CSV → 后端 400，错误提示可见', async ({ page }) => {
    await gotoApp(page, '/data')

    const zipPath = path.join(os.tmpdir(), `e2e_zip_empty_${Date.now()}.zip`)
    makeZip(zipPath, [{ name: 'readme.txt', content: 'no csv here' }])

    try {
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadFile(page, zipPath)

      await expect(page.getByText(/未找到 CSV/)).toBeVisible({ timeout: 60_000 })
    } finally {
      cleanupQuiet(zipPath)
    }
  })

  test('同名 ZIP 重复上传 → 批次文件数不重复注册', async ({ page }) => {
    await gotoApp(page, '/data')

    const zipBase = `e2e_zip_dup_${Date.now()}`
    const zipPath = path.join(os.tmpdir(), `${zipBase}.zip`)
    makeZip(zipPath, [
      { name: 'a.csv', content: MIN_CSV },
      { name: 'b.csv', content: MIN_CSV },
    ])

    try {
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadFile(page, zipPath)
      await expect(page.getByText(/导入 2 个文件/)).toBeVisible({ timeout: 60_000 })

      // 再次上传同名 zip：不新增注册（toast 不带导入数）
      await uploadFile(page, zipPath)
      await expect(page.getByText(/e2e_zip_dup.*上传成功$/).last()).toBeVisible({ timeout: 60_000 })

      await gotoBatchTab(page)

      const header = page.locator(`[data-testid="batch-header-${zipBase}"]`)
      await expect(header).toBeVisible({ timeout: 15_000 })
      await expect(header.locator('.batch-count')).toHaveText('2 个文件')
    } finally {
      cleanupQuiet(zipPath)
    }
  })

  test('非 CSV/ZIP 扩展名（.7z）被前端拒绝', async ({ page }) => {
    await gotoApp(page, '/data')

    const tmpPath = path.join(os.tmpdir(), `e2e_bad_ext_${Date.now()}.7z`)
    fs.writeFileSync(tmpPath, 'fake 7z content')

    try {
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadFile(page, tmpPath)

      await expect(page.getByText(/不是 CSV 或 ZIP/)).toBeVisible({ timeout: 10_000 })
    } finally {
      cleanupQuiet(tmpPath)
    }
  })
})
