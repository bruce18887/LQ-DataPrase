import { test, expect } from '@playwright/test'
import path from 'node:path'
import fs from 'node:fs'
import { PROJECT_ROOT, PRIMARY_SAMPLE_FILE } from '../fixtures/test-data'
import { gotoApp } from '../helpers/nav'

/**
 * 批次阶段解析 UI（阶段胶囊过滤 + 树形汇总 + 短文件名回退）端到端用例。
 *
 * 组件依据（src/pages/dashboard/components/）：
 *  - Dashboard「📦 批次良率」tab（.batch-yield-tab）→ BatchYieldTab
 *  - StageFilterBar.vue：.stage-chip 胶囊（全部 + 各 stage：名/良率%/总数），点击全局过滤
 *  - PhaseSummaryTree.vue：.el-card「📋 阶段汇总」内 el-table 树形（stage 父行 → 版本子行）
 *  - CollapsibleSection.vue：.el-card__header 内 button（「展开 ▼/收起 ▲」），body v-if
 *  - 「📊 阶段明细表」卡：phases 表（阶段列 fixed → 主表体 td.el-table-fixed-column--left）
 *
 * API：
 *  - POST /api/v1/batch-dirs/import/ {dir_name} — 注册磁盘批次目录
 *  - GET /batch-report/batch_yield_data/?batch_name=...（阶段解析主入口）
 *  - DELETE /api/v1/batch-dirs/<dir_name>/ — 清理
 *
 * 数据流：fs 把可解析样例 CSV 复制到 media/data/admin/batch/<批次名>/，
 * 重命名带 _CP1_ / _UIS1.0_ / _FT1_ / _HW_ 标记 → import 注册 → reload 刷新批次列表 →
 * 选择批次并「加载批次报表」→ 断言胶囊/树/过滤/回退。
 * 批次名 000_ 开头使其在 list_batches（-batch_name 降序）中排末尾，不影响其它用例。
 */
const BATCH_BASE_DIR = path.join(PROJECT_ROOT, 'media', 'data', 'admin', 'batch')

test.describe('批次阶段解析 UI（胶囊过滤/树形汇总/回退）', { tag: ['@p2', '@batch'] }, () => {
  test('@p2 阶段胶囊过滤 + 树形汇总 + 短文件名回退', async ({ page }) => {
    const ts = Date.now()
    const batchName = `000_E2E_UIS_${ts}`
    const batchDir = path.join(BATCH_BASE_DIR, batchName)
    const hwShortName = `E2E_${ts}_HW_data`

    // ── 1) 造批次数据：4 个可解析样例，文件名带阶段标记 ──
    fs.mkdirSync(batchDir, { recursive: true })
    for (const name of [
      `E2E_${ts}_CP1_20260726.csv`,
      `E2E_${ts}_UIS1.0_20260726.csv`,
      `E2E_${ts}_FT1_20260726.csv`,
      `${hwShortName}.csv`,
    ]) {
      fs.copyFileSync(PRIMARY_SAMPLE_FILE, path.join(batchDir, name))
    }

    try {
      await gotoApp(page, '/dashboard')

      // ── 2) 注册批次目录 ──
      const importStatus = await page.evaluate(async (dirName) => {
        const token = localStorage.getItem('access_token')
        const res = await fetch('/api/v1/batch-dirs/import/', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ dir_name: dirName }),
        })
        return res.status
      }, batchName)
      expect(importStatus, `batch-dirs/import 应返回 201，实际 ${importStatus}`).toBe(201)

      // list_batches 随页面加载已触发（当时不含新批次），刷新后下拉才有该批次
      await page.reload()

      // ── 3) 批次良率 tab → 选择批次 → 加载报表 ──
      await page.locator('.el-tabs__item').filter({ hasText: '批次良率' }).click()
      const batchSelect = page.locator('.batch-selector .el-select').first()
      await expect(batchSelect).toBeVisible()
      await batchSelect.click()
      const option = page
        .locator('.el-select-dropdown:visible').last()
        .locator('.el-select-dropdown__item')
        .filter({ hasText: batchName })
        .first()
      await expect(option).toBeVisible({ timeout: 10_000 })
      await option.click()

      const loadBtn = page.getByRole('button', { name: /加载批次报表/ })
      await expect(loadBtn).toBeEnabled()
      const yieldResp = page.waitForResponse(
        (r) => r.url().includes('/batch-report/batch_yield_data/'),
        { timeout: 30_000 },
      )
      await loadBtn.click()
      expect((await yieldResp).status()).toBe(200)

      // ── 4) 阶段胶囊条：全部 + CP/UIS/FT/其他（含良率%）──
      for (const stage of ['全部', 'CP', 'UIS', 'FT', '其他']) {
        await expect(
          page.locator('.stage-chip').filter({ hasText: stage }).first(),
          `胶囊「${stage}」应可见`,
        ).toBeVisible({ timeout: 15_000 })
      }
      await expect(page.locator('.stage-chip').filter({ hasText: 'UIS' }).first())
        .toContainText('%')

      // ── 5) 阶段汇总树：父行 CP/UIS/FT/其他，展开 UIS 见版本子行 ──
      const summaryTable = page
        .locator('.el-card')
        .filter({ hasText: '📋 阶段汇总' })
        .locator('.el-table')
      await expect(summaryTable).toBeVisible({ timeout: 15_000 })
      // 注意：EP 树形表的隐藏子行仍在 DOM（display:none），统计可见行需 :visible
      const summaryRows = summaryTable.locator('tbody tr')
      await expect(summaryTable.locator('tbody tr:visible')).toHaveCount(4)
      await expect(summaryRows.filter({ hasText: 'UIS' }).first()).toContainText('91.13%')

      await summaryRows.filter({ hasText: 'UIS' }).first().locator('.el-table__expand-icon').click()
      // getByText 会同时命中 td 与内部 span → 用 exact + first 避免 strict 冲突
      await expect(summaryTable.getByText('UIS1.0', { exact: true }).first()).toBeVisible({ timeout: 5_000 })
      await expect(summaryTable.getByText('CP1', { exact: true }).first()).not.toBeVisible()

      // ── 6) 阶段明细表（默认展开，若被收起则先展开）：CP1 → UIS1.0 → FT1 顺序 + HW 短文件名回退 ──
      const detailBtn = page
        .locator('.el-card__header', { hasText: '📊 阶段明细表' })
        .first()
        .locator('button')
      if ((await detailBtn.textContent())?.includes('展开')) {
        await detailBtn.click()
      }
      const phaseTable = page
        .locator('.el-card')
        .filter({ hasText: '📊 阶段明细表' })
        .locator('.el-table')
      await expect(phaseTable).toBeVisible({ timeout: 15_000 })
      const phaseRows = phaseTable.locator('tbody tr')
      await expect(phaseRows.nth(0).locator('td.el-table-fixed-column--left').first()).toHaveText('CP1')
      await expect(phaseRows.nth(1).locator('td.el-table-fixed-column--left').first()).toHaveText('UIS1.0')
      await expect(phaseRows.nth(2).locator('td.el-table-fixed-column--left').first()).toHaveText('FT1')
      // 无法识别阶段 → 直接显示去扩展名的短文件名（不再 UNKNOWN）
      await expect(
        phaseTable.locator('td.el-table-fixed-column--left').filter({ hasText: hwShortName }),
      ).toBeVisible()

      // ── 7) 点击 UIS 胶囊 → 全局过滤：明细表只剩 UIS1.0，汇总树只含 UIS 行 ──
      await page.locator('.stage-chip').filter({ hasText: 'UIS' }).first().click()
      await expect(phaseRows).toHaveCount(1)
      await expect(phaseRows.first().locator('td.el-table-fixed-column--left').first()).toHaveText('UIS1.0')
      await expect(phaseTable.getByText('CP1')).not.toBeVisible()
      await expect(
        phaseTable.locator('td.el-table-fixed-column--left').filter({ hasText: hwShortName }),
      ).not.toBeVisible()
      // 汇总树：UIS 行存在（EP 可能保留展开状态，不断言行数），CP/FT/其他 行消失
      await expect(summaryRows.filter({ hasText: 'UIS' }).first()).toBeVisible()
      await expect(summaryRows.filter({ hasText: '其他' })).toHaveCount(0)
      await expect(summaryTable.getByText('FT', { exact: true }).first()).not.toBeVisible()
      await expect(page.locator('.stage-chip.is-active').filter({ hasText: 'UIS' })).toHaveCount(1)

      // ── 8) 再次点击 UIS 胶囊取消过滤 → 恢复全部 ──
      await page.locator('.stage-chip').filter({ hasText: 'UIS' }).first().click()
      await expect(phaseRows).toHaveCount(4)
      await expect(
        phaseTable.locator('td.el-table-fixed-column--left').filter({ hasText: hwShortName }),
      ).toBeVisible()

      console.log(`[batch-phase] ${batchName} 胶囊过滤/树形汇总/回退断言通过`)
    } finally {
      // ── 9) 清理：先删 DB 记录+磁盘目录，再兜底删磁盘（Windows EPERM 需重试）──
      await page
        .evaluate(async (dirName) => {
          const token = localStorage.getItem('access_token')
          await fetch(`/api/v1/batch-dirs/${dirName}/`, {
            method: 'DELETE',
            headers: token ? { Authorization: `Bearer ${token}` } : {},
          }).catch(() => null)
        }, batchName)
        .catch(() => null)
      try {
        fs.rmSync(batchDir, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 })
      } catch {
        // 目录可能已被 API DELETE 移除或仍被进程占用 —— 尽力而为，不使清理失败影响断言
      }
    }
  })
})
