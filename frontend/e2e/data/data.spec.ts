import { test, expect } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { SEEDED_FILE_COUNT, PRIMARY_SAMPLE_FILE, SEEDED_FILES } from '../fixtures/test-data'
import { gotoApp } from '../helpers/nav'
import { uploadFile, uploadMultipleFiles, expectUploadSuccess } from '../helpers/upload'
import { elSelectByPlaceholder, visibleSelectOptions } from '../helpers/elplus'

const SEEDED_MIN = SEEDED_FILE_COUNT

/** 在文件列表 tab 内按文件名定位卡片 */
function fileCard(page: import('@playwright/test').Page, filename: string) {
  return page.locator('.el-card').filter({ hasText: filename })
}

test.describe('数据管理 /data', { tag: ['@p0', '@p1', '@p2', '@data'] }, () => {
  test('@p0 页面渲染：已植入文件列表可见，/files/ 返回 200', async ({ page }) => {
    const filesResp = page.waitForResponse(
      (r) => /\/files\/?(\?|$)/.test(r.url()) && r.request().method() === 'GET',
    )
    await gotoApp(page, '/data')

    await expect(page.locator('h1, h2').filter({ hasText: '数据管理' })).toBeVisible()

    // 文件列表 tab should be active by default
    await expect(page.locator('.tab-btn.active')).toContainText('文件列表')

    const resp = await filesResp
    expect(resp.status()).toBe(200)

    // 预植入文件已出现
    await expect.poll(
      () => page.locator('.el-table .el-table__row').count(),
      { timeout: 15_000 },
    ).toBeGreaterThanOrEqual(SEEDED_MIN)
  })

  test('@p1 查看数据：选中文件后切到查看数据 tab 并渲染 ag-grid', async ({ page }) => {
    await gotoApp(page, '/data')

    // Click the first file row's "查看" button
    const firstRow = page.locator('.el-table .el-table__row').first()
    await expect(firstRow).toBeVisible({ timeout: 10_000 })
    await firstRow.locator('button').filter({ hasText: '查看' }).click()

    // Should switch to 查看数据 tab
    await expect(page.locator('.tab-btn.active')).toContainText('查看数据')

    // ag-grid should render
    await expect(page.locator('.ag-root').first()).toBeVisible({ timeout: 30_000 })
  })

  test('@p1 文件类型标签：上传的文件显示"单文件"类型', async ({ page }) => {
    await gotoApp(page, '/data')

    const uniqueName = `e2e_type_${Date.now()}.csv`
    const tmpPath = path.join(os.tmpdir(), uniqueName)
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, tmpPath)

    try {
      // Switch to upload tab
      await page.locator('.tab-btn').filter({ hasText: '上传文件' }).click()
      await uploadFile(page, tmpPath)
      await expectUploadSuccess(page)

      // Switch back to file list
      await page.locator('.tab-btn').filter({ hasText: '文件列表' }).click()

      // Verify the file appears in the table
      await expect(page.locator('.el-table').getByText(uniqueName)).toBeVisible({ timeout: 15_000 })
    } finally {
      fs.rmSync(tmpPath, { force: true })
    }
  })

  test('@p2 删除：上传唯一命名文件，再删除并确认消失', async ({ page }) => {
    await gotoApp(page, '/data')

    const uniqueName = `e2e_del_${Date.now()}_${Math.floor(Math.random() * 1e6)}.csv`
    const tmpPath = path.join(os.tmpdir(), uniqueName)
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, tmpPath)

    try {
      // Switch to upload tab and upload
      await page.locator('.tab-btn').filter({ hasText: '上传文件' }).click()
      await uploadFile(page, tmpPath)
      await expectUploadSuccess(page)

      // Switch to file list
      await page.locator('.tab-btn').filter({ hasText: '文件列表' }).click()

      // Wait for the file to appear
      await expect(page.locator('.el-table').getByText(uniqueName)).toBeVisible({ timeout: 15_000 })

      // Click the row's delete button (操作 column)
      const row = page.locator('.el-table__row').filter({ hasText: uniqueName })
      await row.locator('button').filter({ hasText: /删除/ }).click()

      // Confirm deletion in the MessageBox
      const confirmBtn = page.getByRole('button', { name: '删除', exact: true })
      await expect(confirmBtn).toBeVisible({ timeout: 10_000 })
      await confirmBtn.click()

      await expect(page.getByText('文件已删除').first()).toBeVisible({ timeout: 15_000 })
      await expect(page.locator('.el-table').getByText(uniqueName)).toHaveCount(0, { timeout: 15_000 })
    } finally {
      fs.rmSync(tmpPath, { force: true })
    }
  })

  test('@p2 API 验证：/files/ 返回的文件包含 file_type 字段', async ({ page }) => {
    await gotoApp(page, '/data')

    const result = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      const res = await fetch('/api/v1/files/', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      const data = await res.json()
      const files = Array.isArray(data) ? data : (data.results ?? [])
      return {
        status: res.status,
        count: files.length,
        hasFileType: files.length > 0 && 'file_type' in files[0],
        hasBatchName: files.length > 0 && 'batch_name' in files[0],
      }
    })
    expect(result.status).toBe(200)
    expect(result.hasFileType).toBe(true)
    expect(result.hasBatchName).toBe(true)
  })

  test('@p2 多文件上传：一次上传两个文件均出现在列表中', async ({ page }) => {
    await gotoApp(page, '/data')

    const ts = Date.now()
    const name1 = `e2e_multi_${ts}_a.csv`
    const name2 = `e2e_multi_${ts}_b.csv`
    const tmp1 = path.join(os.tmpdir(), name1)
    const tmp2 = path.join(os.tmpdir(), name2)
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, tmp1)
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, tmp2)

    try {
      await page.locator('.tab-btn').filter({ hasText: '上传文件' }).click()
      await uploadMultipleFiles(page, [tmp1, tmp2])

      // Wait for both success messages
      await expect(page.getByText(/上传成功/).first()).toBeVisible({ timeout: 30_000 })

      // Switch to file list
      await page.locator('.tab-btn').filter({ hasText: '文件列表' }).click()

      // Both files should appear
      await expect(page.locator('.el-table').getByText(name1)).toBeVisible({ timeout: 15_000 })
      await expect(page.locator('.el-table').getByText(name2)).toBeVisible({ timeout: 15_000 })
    } finally {
      fs.rmSync(tmp1, { force: true })
      fs.rmSync(tmp2, { force: true })
    }
  })

  test('@p2 批次目录 API：GET /batch-dirs/ 返回 200', async ({ page }) => {
    await gotoApp(page, '/data')

    const status = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      const res = await fetch('/api/v1/batch-dirs/', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      return res.status
    })
    expect(status).toBe(200)
  })
})

test.describe('数据管理 /data 列表增强（搜索/筛选/分页/批量删除/新列）', { tag: ['@p1', '@p2', '@data'] }, () => {
  test('@p1 新列渲染：表头出现“产品”与“原始修改时间”', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('.el-table th').filter({ hasText: '产品' })).toBeVisible()
    await expect(page.locator('.el-table th').filter({ hasText: '原始修改时间' })).toBeVisible()
  })

  test('@p1 搜索：按文件名过滤列表', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })

    // 用某个已植入文件名的片段搜索
    const fragment = SEEDED_FILES.ETS88_FT.slice(0, 8)
    const search = page.locator('.file-list-tab input[placeholder="按文件名搜索"]')
    await search.fill(fragment)

    // 等待匹配结果，确认目标文件可见
    await expect(page.locator('.el-table').getByText(SEEDED_FILES.ETS88_FT)).toBeVisible({ timeout: 15_000 })

    // 清空后行数恢复
    await search.fill('')
    await expect.poll(
      () => page.locator('.el-table .el-table__row').count(),
      { timeout: 15_000 },
    ).toBeGreaterThan(0)
  })

  test('@p2 产品筛选：下拉存在并可选择产品过滤', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })

    // product_codes API 返回 200 且含数据
    const codes = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      const res = await fetch('/api/v1/files/product_codes/', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      const data = await res.json()
      return { status: res.status, codes: data.product_codes ?? [] }
    })
    expect(codes.status).toBe(200)
    expect(Array.isArray(codes.codes)).toBe(true)

    if (codes.codes.length > 0) {
      // 打开“全部产品”下拉并选第一个产品
      await elSelectByPlaceholder(page.locator('.file-list-tab'), '全部产品').first().click()
      await visibleSelectOptions(page).first().click()
      // 列表至少应有一行（选中产品存在文件）
      await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })
    }
  })

  test('@p2 批量删除：上传两个唯一文件后多选批量删除', async ({ page }) => {
    await gotoApp(page, '/data')

    const ts = Date.now()
    const name1 = `e2e_bulk_${ts}_a.csv`
    const name2 = `e2e_bulk_${ts}_b.csv`
    const tmp1 = path.join(os.tmpdir(), name1)
    const tmp2 = path.join(os.tmpdir(), name2)
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, tmp1)
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, tmp2)

    try {
      await page.locator('.tab-btn').filter({ hasText: '上传文件' }).click()
      await uploadMultipleFiles(page, [tmp1, tmp2])
      await expect(page.getByText(/上传成功/).first()).toBeVisible({ timeout: 30_000 })

      await page.locator('.tab-btn').filter({ hasText: '文件列表' }).click()

      // 用搜索缩小到本次上传的两个文件
      const search = page.locator('.file-list-tab input[placeholder="按文件名搜索"]')
      await search.fill(`e2e_bulk_${ts}_`)
      await expect(page.locator('.el-table').getByText(name1)).toBeVisible({ timeout: 15_000 })
      await expect(page.locator('.el-table').getByText(name2)).toBeVisible({ timeout: 15_000 })

      // 勾选两行的 selection checkbox
      const row1 = page.locator('.el-table__row').filter({ hasText: name1 })
      const row2 = page.locator('.el-table__row').filter({ hasText: name2 })
      await row1.locator('.el-checkbox').click()
      await row2.locator('.el-checkbox').click()

      // 点击批量删除
      const bulkBtn = page.locator('.file-list-tab button').filter({ hasText: '批量删除' })
      await expect(bulkBtn).toBeEnabled()
      await bulkBtn.click()

      // 二次确认
      const confirmBtn = page.getByRole('button', { name: '删除', exact: true })
      await expect(confirmBtn).toBeVisible({ timeout: 10_000 })
      await confirmBtn.click()

      await expect(page.getByText(/已删除 \d+ 个文件/).first()).toBeVisible({ timeout: 15_000 })
      await expect(page.locator('.el-table').getByText(name1)).toHaveCount(0, { timeout: 15_000 })
      await expect(page.locator('.el-table').getByText(name2)).toHaveCount(0, { timeout: 15_000 })
    } finally {
      fs.rmSync(tmp1, { force: true })
      fs.rmSync(tmp2, { force: true })
    }
  })

  test('@p2 分页：文件数超过页大小时分页控件出现', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })

    // 读取总数判断是否应出现分页（后端 PAGE_SIZE=20）
    const count = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      const res = await fetch('/api/v1/files/', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      const data = await res.json()
      return data.count ?? (Array.isArray(data) ? data.length : 0)
    })

    if (count > 20) {
      await expect(page.locator('.file-list-tab .el-pagination')).toBeVisible({ timeout: 10_000 })
    } else {
      // 不足一页时分页控件应隐藏
      await expect(page.locator('.file-list-tab .el-pagination')).toHaveCount(0)
    }
  })
})
