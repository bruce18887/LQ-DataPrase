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

/**
 * 读取 Bin × Site 交叉表「Total」行的 All Site 总数（fixed-right 克隆列）。
 * Total 行的 all_site 为原始数字（非 "n (pct%)" 格式化），取该行最后一个数字。
 */
async function readBinSiteTotalAll(page: import('@playwright/test').Page): Promise<number> {
  const fixedCols = page.locator('.bin-site-cross .el-table__fixed-right tbody tr').last()
  const row = (await fixedCols.count()) > 0
    ? fixedCols
    : page.locator('.bin-site-cross .el-table tbody tr').last()
  await expect(row).toBeVisible()
  const text = (await row.textContent()) || ''
  const nums = text.match(/\d+/g) || []
  expect(nums.length).toBeGreaterThan(0)
  return Number(nums[nums.length - 1])
}

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

      // ── 7.5 总览条（阶段汇总卡内紧凑 KPI）：随阶段过滤联动 ──
      const summaryCard = page.locator('.el-card').filter({ hasText: '📋 阶段汇总' }).first()
      const strip = summaryCard.locator('.summary-strip')
      await expect(strip).toBeVisible()
      // 阶段过滤态：标签切换为「良率」，值 = UIS 阶段良率（与胶囊 91.13% 一致）
      await expect(strip).toContainText('良率')
      await expect(strip).toContainText('91.13')
      // 4 个关键指标齐全：投入/Pass/Fail/良率
      await expect(strip.locator('.strip-item')).toHaveCount(4)

      // ── 7.6 QA 数量校验横幅：本批次无 QA 文件 → 横幅不渲染（v-if 门控）──
      await expect(page.locator('.qa-banner')).toHaveCount(0)

      // ── 7.7 Bin 分布卡：Site 良率 GAP pills / Bin×Site / UPH 均按「所选单阶段」显示 ──
      const binHeader = page.locator('.el-card__header', { hasText: '📋 Bin 分布' }).first()
      const binToggle = binHeader.locator('button')
      if ((await binToggle.textContent())?.includes('展开')) {
        await binToggle.click()
      }
      // 阶段过滤为 UIS（1 个文件，选择器必选 UIS1.0）：记录 Bin×Site 单文件 Total
      const uisTotal = await readBinSiteTotalAll(page)
      // compact 后 GAP 以 3 个 pills 展示（最高/最低/差异）
      // 注意：单文件 pane 也有 .uph-card（v-show 隐藏），必须限定 .batch-yield-tab 作用域
      const batchRoot = page.locator('.batch-yield-tab')
      await expect(batchRoot.locator('.yield-pill')).toHaveCount(3)
      await expect(batchRoot.locator('.yield-pill').first()).toContainText('%')
      // UPH 卡片（当前所选单阶段口径）
      await expect(batchRoot.locator('.uph-card').first()).toBeVisible()
      // 分区标题带当前所选阶段标识（重设计后为 bin-sub-title 小标题）
      await expect(
        batchRoot.locator('.bin-sub-title').filter({ hasText: 'Bin × Site' }).first(),
      ).toContainText('UIS1.0')

      // ── 8) 再次点击 UIS 胶囊取消过滤 → 恢复全部 ──
      await page.locator('.stage-chip').filter({ hasText: 'UIS' }).first().click()
      await expect(phaseRows).toHaveCount(4)
      await expect(
        phaseTable.locator('td.el-table-fixed-column--left').filter({ hasText: hwShortName }),
      ).toBeVisible()
      // 单阶段口径：UIS1.0 仍在可选列表中 → 选择器保持所选，Bin×Site 仍是该单文件合计
      const allTotal = await readBinSiteTotalAll(page)
      expect(allTotal, 'Bin×Site 为单阶段口径：恢复全部后仍显示 UIS1.0 单文件合计').toBe(uisTotal)

      // 切换阶段选择器到另一单阶段（CP1）：分区标题随之更新，Bin×Site 按 CP1 单文件重绘
      const phaseSelect = page.locator('.bin-selector .el-select')
      await phaseSelect.click()
      await page
        .locator('.el-select-dropdown:visible').last()
        .locator('.el-select-dropdown__item')
        .filter({ hasText: 'CP1' })
        .first()
        .click()
      await expect(
        batchRoot.locator('.bin-sub-title').filter({ hasText: 'Bin × Site' }).first(),
      ).toContainText('CP1')
      const cpTotal = await readBinSiteTotalAll(page)
      // 4 个文件是同一份样例的复制 → 任意单阶段合计都等于 UIS 单文件合计
      expect(cpTotal, '切换到 CP1 后 Bin×Site 仍为单文件口径（4 文件为同一份样例复制）').toBe(uisTotal)
      // 总览条回到批次整体值
      await expect(strip).toContainText('整体良率')

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
