import { test, expect, type Page } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { PRIMARY_SAMPLE_FILE } from '../fixtures/test-data'
import { gotoApp } from '../helpers/nav'
import { uploadMultipleFiles, uploadFile, expectUploadSuccess } from '../helpers/upload'
import { cleanupQuiet } from '../helpers/cleanup'

/**
 * 组合功能（2026-08-29 需求 2 + 二轮增强）：
 * - 勾选多个单文件 → 组合为新批次（弹窗，非 prompt）
 * - 组合成功后：单文件列表消失、批次 Tab 表格化显示（行×列/大小/产品可见）
 * - 误组合的文件可「移出批次」→ 还原为单文件
 * - 追加语义：单文件可加入已有批次
 *
 * 注意：组合是物理移动（batch/<名称>/），删除批次 = 删除磁盘 + DB 记录，
 * 因此测试以「删除批次」收尾即完成清理。
 */

/** 上传 n 个唯一命名的单文件，返回临时文件路径列表 */
async function uploadSingles(page: Page, prefix: string, count: number): Promise<string[]> {
  const ts = Date.now()
  const paths: string[] = []
  for (let i = 0; i < count; i++) {
    const p = path.join(os.tmpdir(), `e2e_${prefix}_${ts}_${i}.csv`)
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, p)
    paths.push(p)
  }
  // 上传区已展开则不点按钮（按钮是 toggle，重复点击会关闭上传区）
  const uploadVisible = await page.locator('.content-section:visible .upload-section').isVisible().catch(() => false)
  if (!uploadVisible) {
    await page.locator('button').filter({ hasText: '上传文件' }).click()
  }
  await uploadMultipleFiles(page, paths)
  await expectUploadSuccess(page)
  return paths
}

/** 单文件列表行定位：必须限定在可见面板（批次 Tab 的隐藏表格行会污染全局 .el-table__row） */
function rowByName(page: Page, name: string) {
  return page
    .locator('.content-section:visible .el-table .el-table__row')
    .filter({ hasText: name })
}

/** 通过 API 删除批次（用例末尾清理：批次内剩余文件一并清除） */
async function deleteBatchViaApi(page: Page, batchName: string) {
  await page.evaluate(async (n) => {
    const token = localStorage.getItem('access_token')
    await fetch(`/api/v1/batch-dirs/${encodeURIComponent(n)}/`, {
      method: 'DELETE',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
  }, batchName).catch(() => {})
}

test.describe('数据管理 → 组合为批次 / 批次文件管理', { tag: ['@p2', '@data'] }, () => {
  test('组合为新批次 → 批次表格显示信息 → 移出还原单文件', async ({ page }) => {
    test.skip(!fs.existsSync(PRIMARY_SAMPLE_FILE), '样例数据缺失，跳过')

    await gotoApp(page, '/data')
    const paths = await uploadSingles(page, 'cmb_FT1', 2)
    const names = paths.map((p) => path.basename(p))
    const batchName = `E2E_CMB_${Date.now()}`

    try {
      // 勾选两行 → 打开组合弹窗（新建模式）→ 输入名称提交
      for (const n of names) {
        await rowByName(page, n).locator('.el-checkbox').first().click()
      }
      const combineBtn = page.locator('button').filter({ hasText: '组合为批次' })
      await expect(combineBtn).toBeEnabled({ timeout: 5_000 })
      await combineBtn.click()
      await page.locator('[data-testid="combine-new-name"]').fill(batchName)
      await page.locator('[data-testid="combine-submit"]').click()

      await expect(page.getByText(`已组合 2 个文件为批次 "${batchName}"`).first())
        .toBeVisible({ timeout: 20_000 })
      for (const n of names) {
        await expect(rowByName(page, n)).toHaveCount(0, { timeout: 15_000 })
      }

      // 批次 Tab：表格化展示（行数 = 2，含行列/大小信息）
      await page.locator('.tabs-nav .tab-btn').filter({ hasText: '批次数据' }).click()
      await expect(page.locator('.tab-btn.active')).toContainText('批次数据')
      const header = page.locator(`[data-testid="batch-header-${batchName}"]`)
      await expect(header).toBeVisible({ timeout: 15_000 })
      await expect(header.locator('.batch-count')).toHaveText('2 个文件')
      await header.click()
      const rows = page.locator(`[data-testid="batch-files-${batchName}"] .batch-file-row`)
      await expect(rows).toHaveCount(2, { timeout: 10_000 })
      await expect(rows.first()).toContainText('×')  // 行列
      await expect(rows.first()).toContainText(/KB|MB|B/)  // 大小
      await expect(rows.first()).toContainText('FT1')  // 阶段（文件名解析）
      await expect(rows.first()).toContainText('BPD60320')  // 测试程序
      await expect(rows.first().locator('.batch-filename-wrap')).toBeVisible()  // 文件名换行（设置默认开）

      // 移出 1 个文件 → 还原为单文件
      await rows.first().locator('.el-checkbox').click()
      const moveBtn = page.locator(`[data-testid="batch-files-${batchName}"] .batch-selection-bar button`)
      await expect(moveBtn).toContainText('移出选中的 1 个')
      await moveBtn.click()
      const confirmBtn = page.locator('.el-message-box').getByRole('button', { name: '移出', exact: true })
      await expect(confirmBtn).toBeVisible({ timeout: 10_000 })
      await confirmBtn.click()
      await expect(page.getByText(/已将 1 个文件移出批次/).first()).toBeVisible({ timeout: 15_000 })
      await expect(rows).toHaveCount(1, { timeout: 10_000 })

      // 单文件列表恰好恢复 1 个文件（不假设表格排序）
      await page.locator('.tabs-nav .tab-btn').filter({ hasText: '文件列表' }).click()
      await expect.poll(
        async () => (await rowByName(page, names[0]).count()) + (await rowByName(page, names[1]).count()),
        { timeout: 15_000 },
      ).toBe(1)
    } finally {
      await deleteBatchViaApi(page, batchName)
      for (const p of paths) cleanupQuiet(p)
    }
  })

  test('追加到已有批次：单文件加入批次后文件数 +1', async ({ page }) => {
    test.skip(!fs.existsSync(PRIMARY_SAMPLE_FILE), '样例数据缺失，跳过')

    await gotoApp(page, '/data')
    const batchName = `E2E_CMB_APP_${Date.now()}`
    const paths1 = await uploadSingles(page, 'cmba', 2)
    const names1 = paths1.map((p) => path.basename(p))
    let paths2: string[] = []

    try {
      // 组合 2 个文件为新批次
      for (const n of names1) {
        await rowByName(page, n).locator('.el-checkbox').first().click()
      }
      await page.locator('button').filter({ hasText: '组合为批次' }).click()
      await page.locator('[data-testid="combine-new-name"]').fill(batchName)
      await page.locator('[data-testid="combine-submit"]').click()
      await expect(page.getByText(`已组合 2 个文件为批次`).first()).toBeVisible({ timeout: 20_000 })

      // 再上传 1 个文件，追加到已有批次
      paths2 = await uploadSingles(page, 'cmbb', 1)
      const name2 = path.basename(paths2[0])
      await expect(rowByName(page, name2)).toBeVisible({ timeout: 15_000 })
      await rowByName(page, name2).locator('.el-checkbox').first().click()
      await page.locator('button').filter({ hasText: '组合为批次' }).click()
      // 弹窗切到「追加到已有批次」并选择目标
      await page.locator('.el-radio').filter({ hasText: '追加到已有批次' }).click()
      await page.locator('[data-testid="combine-existing-select"]').click()
      await page.locator('.el-select-dropdown__item:visible').filter({ hasText: batchName }).first().click()
      await page.locator('[data-testid="combine-submit"]').click()
      await expect(page.getByText(`已组合 1 个文件为批次 "${batchName}"`).first())
        .toBeVisible({ timeout: 20_000 })

      // 批次 Tab 文件数 = 3
      await page.locator('.tabs-nav .tab-btn').filter({ hasText: '批次数据' }).click()
      const header = page.locator(`[data-testid="batch-header-${batchName}"]`)
      await expect(header).toBeVisible({ timeout: 15_000 })
      await expect(header.locator('.batch-count')).toHaveText('3 个文件', { timeout: 10_000 })

      // 批次搜索：无关关键字 → 批次隐藏；批次名关键字 → 恢复可见
      const search = page.locator('[data-testid="batch-search"]')
      await search.fill('NO-SUCH-BATCH-NAME')
      await expect(page.locator(`[data-testid="batch-group-${batchName}"]`)).toBeHidden({ timeout: 5_000 })
      await search.fill(batchName)
      await expect(page.locator(`[data-testid="batch-group-${batchName}"]`)).toBeVisible({ timeout: 5_000 })
    } finally {
      await deleteBatchViaApi(page, batchName)
      for (const p of [...paths1, ...paths2]) cleanupQuiet(p)
    }
  })
})
