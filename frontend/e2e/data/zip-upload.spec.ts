import { test, expect, type Page } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { gotoApp } from '../helpers/nav'
import { uploadFile } from '../helpers/upload'
import { makeZip } from '../helpers/zip'
import { cleanupQuiet, deleteBatchQuiet, deleteFilesByNameQuiet } from '../helpers/cleanup'

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

/** 批次区已从文件列表 Tab 独立为「组合数据」Tab */
async function gotoBatchTab(page: Page) {
  const batchTab = page.locator('.tabs-nav .tab-btn').filter({ hasText: '组合数据' })
  await batchTab.click()
  await expect(page.locator('.tab-btn.active')).toContainText('组合数据')
  const collapseHeader = page.getByTestId('batch-directory-section').locator('.el-collapse-item__header')
  if ((await collapseHeader.getAttribute('aria-expanded')) !== 'true') {
    await collapseHeader.click()
  }
  await expect(collapseHeader).toHaveAttribute('aria-expanded', 'true')
}

async function gotoCombinationTab(page: Page) {
  await page.locator('.tabs-nav .tab-btn').filter({ hasText: '组合数据' }).click()
  await expect(page.locator('.tab-btn.active')).toContainText('组合数据')
  await expect(page.getByTestId('combination-upload').getByTestId('file-upload-area')).toBeVisible()
}

async function createCombination(page: Page, name: string): Promise<number> {
  return page.evaluate(async (comboName) => {
    const token = localStorage.getItem('access_token')
    const response = await fetch('/api/v1/combinations/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ name: comboName }),
    })
    if (!response.ok) throw new Error(`创建组合失败：${response.status} ${await response.text()}`)
    return (await response.json()).id as number
  }, name)
}

async function deleteCombinationQuiet(page: Page, id: number | null) {
  if (id == null) return
  await page.evaluate(async (comboId) => {
    const token = localStorage.getItem('access_token')
    await fetch(`/api/v1/combinations/${comboId}/`, {
      method: 'DELETE',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
  }, id)
}

async function selectCombination(page: Page, name: string) {
  await page.getByTestId('combination-select').click()
  await page.locator('.dp-combination-select-popper .el-select-dropdown__item')
    .filter({ hasText: name }).click()
  await expect(page.getByTestId('combination-current-name')).toHaveText(name)
}

async function listUngroupedIds(page: Page): Promise<number[]> {
  return page.evaluate(async () => {
    const token = localStorage.getItem('access_token')
    const response = await fetch('/api/v1/files/?page_size=10000&include_hidden=1', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!response.ok) throw new Error(`读取未分组文件失败：${response.status}`)
    const body = await response.json()
    const rows: Array<{ id: number; combination_id: number | null }> = Array.isArray(body)
      ? body
      : body.results
    return rows.filter((row) => row.combination_id == null).map((row) => row.id)
  })
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
      // 必须同时清掉上传产生的批次：只删临时 zip 会把 root.csv/below.csv
      // 的 DataFile 行留在共享 DB 里（它们只有 col1/col2、无 Site 列），
      // 按 -created_at 排到最前后会被分析页自动选中，污染按文件推进的断言。
      // 详见 helpers/cleanup.deleteBatchQuiet。
      await deleteBatchQuiet(page, zipBase)
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
      // 同上：a.csv/b.csv 也是 2行×2列无 Site 列，不清就会污染后续套件
      await deleteBatchQuiet(page, zipBase)
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

  test('ZIP 导入到组合后显示组合与批次标签', async ({ page }) => {
    await gotoApp(page, '/data')
    const name = `e2e_combo_zip_${Date.now()}`
    const zipBase = `e2e_combo_zip_${Date.now()}`
    const zipPath = path.join(os.tmpdir(), `${zipBase}.zip`)
    const batchNo = 'BE01-2608130015'
    let combinationId: number | null = null

    try {
      combinationId = await createCombination(page, name)
      makeZip(zipPath, [{ name: 'root.csv', content: MIN_CSV }])
      await gotoCombinationTab(page)
      await selectCombination(page, name)
      await expect(page.getByTestId('combination-upload')).toBeVisible()
      await page.getByTestId('import-batch-no').fill(batchNo)
      await page.getByTestId('combination-upload').locator('input[type=file]').setInputFiles(zipPath)

      const files = page.getByTestId('combination-files')
      await expect(files).toContainText('root.csv', { timeout: 60_000 })
      const row = files.locator('.el-table__row').filter({ hasText: 'root.csv' })
      await expect(row.getByTestId('managed-tag')).toHaveText([
        name,
        `${name} / ${batchNo}`,
      ])
    } finally {
      await deleteBatchQuiet(page, zipBase)
      cleanupQuiet(zipPath)
      await deleteCombinationQuiet(page, combinationId)
    }
  })

  test('存量归组省略空批次号并将未分组文件加入组合', async ({ page }) => {
    await gotoApp(page, '/data')
    const prefix = `e2e_combo_existing_${Date.now()}`
    const comboName = `${prefix}_combo`
    const filename = `${prefix}.csv`
    const csvPath = path.join(os.tmpdir(), filename)
    let combinationId: number | null = null
    fs.writeFileSync(csvPath, MIN_CSV)

    try {
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadFile(page, csvPath)
      await expect(page.getByText(`${filename} 上传成功`, { exact: true }))
        .toBeVisible({ timeout: 60_000 })

      combinationId = await createCombination(page, comboName)
      await gotoCombinationTab(page)
      const ungroupedIds = await listUngroupedIds(page)
      expect(ungroupedIds.length).toBeGreaterThan(0)
      const existingButton = page.getByTestId('combination-existing')
      await expect(existingButton).toContainText(`存量归组（${ungroupedIds.length}）`)
      await existingButton.click()

      const dialog = page.locator('.el-dialog')
      await expect(dialog).toBeVisible()
      await expect(dialog).toContainText(`将选中的 ${ungroupedIds.length} 个文件归入组合`)
      await dialog.getByTestId('import-combination').click()
      await page.getByRole('option', { name: comboName, exact: true }).click()
      await expect(dialog.getByTestId('import-combination')).toContainText(comboName)

      const assignRequest = page.waitForRequest((request) =>
        request.method() === 'POST' && request.url().endsWith('/files/assign_combination/'),
      )
      await page.getByTestId('import-submit').click()
      const payload = (await assignRequest).postDataJSON()
      expect(payload).toEqual({
        file_ids: ungroupedIds,
        combination_id: combinationId,
      })
      expect(payload).not.toHaveProperty('batch_no')

      await expect(dialog).toBeHidden()
      await selectCombination(page, comboName)
      const files = page.getByTestId('combination-files')
      await expect(files).toContainText(filename)
      const row = files.locator('.el-table__row').filter({ hasText: filename })
      await expect(row.getByTestId('managed-tag')).toHaveText([comboName])
    } finally {
      await deleteFilesByNameQuiet(page, prefix)
      await deleteCombinationQuiet(page, combinationId)
      cleanupQuiet(csvPath)
    }
  })
})
