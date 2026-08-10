import { test, expect, type Page } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { gotoApp } from '../helpers/nav'
import { uploadFile } from '../helpers/upload'
import { cleanupQuiet } from '../helpers/cleanup'

/**
 * 首行 fail（空数据）的 CSV：第一行 SW_Bin=2（fail）且 col1 为空 → browse 序列化为 null。
 * 回归：旧代码用 rowData[0] 判断列是否数值，首行空值导致右键永不弹分布图。
 * 数据行：首行空，随后 3 行有效数值 + 1 个纯文本列（Serial，不弹窗反例）。
 */
const FIRST_ROW_FAIL_CSV = [
  '[GENERAL],',
  'Tester_Type,CTA8290DPlus,',
  '[Data]',
  'SW_Bin,col1,Serial',
  'u,u,-',
  '1,0,-',
  '1,10,-',
  '2,,ABC',
  '1,5.5,ABC2',
  '1,6.0,ABC3',
  '1,6.5,ABC4',
  '',
].join('\n')

/** 进入查看数据 tab：文件列表搜索定位目标文件 → 点「查看」 */
async function openViewTab(page: Page, filename: string) {
  await gotoApp(page, '/data')
  const searchInput = page.locator('input[placeholder="按文件名/程序名/标签搜索"]')
  await searchInput.fill(filename.slice(0, 15))
  const row = page.locator('.el-table .el-table__row').filter({ hasText: filename.slice(0, 12) }).first()
  await expect(row).toBeVisible({ timeout: 30_000 })
  await row.locator('button').filter({ hasText: '查看' }).click()
  await expect(page.locator('.tab-btn.active')).toContainText('查看数据')
  await expect(page.locator('.ag-root').first()).toBeVisible({ timeout: 30_000 })
}

test.describe('右键列头分布图：首行 fail 空数据 + 弹窗尺寸', { tag: ['@p2', '@data'] }, () => {
  let filename = ''
  let csvPath = ''

  test.beforeAll(() => {
    filename = `e2e_first_row_${Date.now()}.csv`
    csvPath = path.join(os.tmpdir(), filename)
    fs.writeFileSync(csvPath, FIRST_ROW_FAIL_CSV, 'utf-8')
  })

  test.afterAll(() => {
    cleanupQuiet(csvPath)
  })

  test('首行空数据的数值列右键仍弹出分布图（回归）+ 弹窗尺寸加大', async ({ page }) => {
    await gotoApp(page, '/data')
    await page.locator('button').filter({ hasText: '上传文件' }).click()
    await uploadFile(page, csvPath)
    await expect(page.getByText(/上传成功/).first()).toBeVisible({ timeout: 60_000 })

    await openViewTab(page, filename)

    // 右键 col1 表头（首行该列为空）→ 分布图必须弹出
    const colHeader = page.locator('.ag-header-cell[col-id="col1"]')
    await expect(colHeader).toBeVisible({ timeout: 15_000 })
    await colHeader.click({ button: 'right' })

    const dialog = page.locator('.el-dialog')
    await expect(dialog).toBeVisible({ timeout: 10_000 })
    await expect(dialog).toContainText('col1')
    await expect(dialog.locator('.stats-summary')).toBeVisible({ timeout: 20_000 })
    await expect(dialog).toContainText('CPK', { timeout: 20_000 })
    await expect(dialog.locator('.chart-container')).toBeVisible({ timeout: 10_000 })

    // 弹窗尺寸（原 720px 宽 / 380px 高，现已加大）：默认视口 1280×720 下应为 960×504
    const box = await dialog.boundingBox()
    expect(box).not.toBeNull()
    expect(box!.width).toBeGreaterThan(900)
    const body = dialog.locator('.hist-body')
    const bodyBox = await body.boundingBox()
    expect(bodyBox).not.toBeNull()
    expect(bodyBox!.height).toBeGreaterThanOrEqual(480)

    // 关闭
    await dialog.locator('.el-dialog__headerbtn').click()
    await expect(dialog).not.toBeVisible({ timeout: 5_000 })
  })

  test('首行是数值的列（SW_Bin=2）右键照常弹出', async ({ page }) => {
    await gotoApp(page, '/data')
    await openViewTab(page, filename)

    const binHeader = page.locator('.ag-header-cell[col-id="SW_Bin"]')
    await expect(binHeader).toBeVisible({ timeout: 15_000 })
    await binHeader.click({ button: 'right' })

    const dialog = page.locator('.el-dialog')
    await expect(dialog).toBeVisible({ timeout: 10_000 })
    await expect(dialog).toContainText('SW_Bin')
    await dialog.locator('.el-dialog__headerbtn').click()
  })

  test('纯文本列（Serial）右键不弹出分布图', async ({ page }) => {
    await gotoApp(page, '/data')
    await openViewTab(page, filename)

    const serialHeader = page.locator('.ag-header-cell[col-id="Serial"]')
    await expect(serialHeader).toBeVisible({ timeout: 15_000 })
    await serialHeader.click({ button: 'right' })
    await page.waitForTimeout(800)
    await expect(page.locator('.el-dialog')).not.toBeVisible({ timeout: 3_000 })
  })
})
