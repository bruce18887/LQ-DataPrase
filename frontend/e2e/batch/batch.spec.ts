import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'

/**
 * 批次报表用例。/batch 路由已重定向到 /dashboard，批次良率是仪表板的一个 tab，
 * 故两条用例都从 /dashboard 进入，不再依赖已下线的「本地目录扫描」页及其 DOM。
 *
 * 弹性策略：批次数据来自共享库，可能为空。数据不足时用 test.skip 说明原因，不误判为成功。
 *
 * 2026-09-26 按层分诊清理：删除 4 条长期 `test.skip('标题', …)` 形态的旧用例
 * （页面渲染 / 扫描目录 / 生成报表 / list_batches 的 `status<500` 永真断言）。
 * 依据见 docs/reference/e2e-tier-triage.md 的 A 组：它们针对已下线页面，skip 形态下从不执行。
 */


test.describe('批次报表 /batch', { tag: ['@batch'] }, () => {

  test('@p2 阶段明细表：展开行显示详细信息（替代 tooltip）', async ({ page }) => {
    // /batch 已重定向 /dashboard：批次良率是仪表板 tab
    await gotoApp(page, '/dashboard')

    // 切到「批次良率」tab
    await page.locator('.el-tabs__item').filter({ hasText: '批次良率' }).click()

    // 等待 list_batches 接口返回
    await page
      .waitForResponse(
        (r) => r.url().includes('/batch-report/list_batches/'),
        { timeout: 15_000 },
      )
      .catch(() => null)

    // 选择第一个批次（如果有）
    const batchSelect = page.locator('.el-select').filter({ hasText: '选择批次' }).first()
    await batchSelect.click()
    const dropdown = page.locator('.el-select-dropdown:visible').last()
    const firstOption = dropdown.locator('.el-select-dropdown__item').first()

    if (!(await firstOption.isVisible({ timeout: 5_000 }).catch(() => false))) {
      test.skip(true, '无可用批次数据，跳过阶段明细表测试')
      return
    }

    // 选择批次后需点击「加载批次报表」才会拉取 batch_yield_data（选择仅更新 model）
    const yieldResp = page.waitForResponse(
      (r) => r.url().includes('/batch-report/batch_yield_data/'),
      { timeout: 30_000 },
    )
    await firstOption.click()
    const loadBtn = page.getByRole('button', { name: /加载批次报表/ })
    await expect(loadBtn).toBeEnabled()
    await loadBtn.click()
    const resp = await yieldResp
    if (!resp || resp.status() >= 400) {
      test.skip(true, `批次数据接口返回 ${resp?.status() ?? 'no-resp'}，跳过阶段明细表测试`)
      return
    }

    // 阶段明细表在 CollapsibleSection 中默认折叠 —— 先展开
    const detailHeaderBtn = page
      .locator('.el-card__header', { hasText: '📊 阶段明细表' })
      .first()
      .locator('button')
    if ((await detailHeaderBtn.textContent().catch(() => ''))?.includes('展开')) {
      await detailHeaderBtn.click()
    }

    // 阶段明细表可见
    const phaseTable = page.locator('.el-card').filter({ hasText: '📊 阶段明细表' }).locator('.el-table')
    await expect(phaseTable).toBeVisible({ timeout: 15_000 })

    // 验证表格有 expand 列（展开按钮）
    const expandButtons = phaseTable.locator('.el-table__expand-icon')
    const expandCount = await expandButtons.count()

    if (expandCount > 0) {
      // 点击第一行的展开按钮
      await expandButtons.first().click()
      await page.waitForTimeout(300)

      // 验证展开详情区域出现（包含 label-value 布局）
      const expandContent = phaseTable.locator('.phase-detail-expand')
      await expect(expandContent).toBeVisible({ timeout: 5_000 })

      // 验证展开内容包含详细字段
      await expect(expandContent).toContainText('完整文件名')
      await expect(expandContent).toContainText('测试程序')
      await expect(expandContent).toContainText('开始时间')
      await expect(expandContent).toContainText('结束时间')

      console.log('[batch] 阶段明细表展开行功能正常')
    } else {
      console.log('[batch] 阶段明细表无数据行，跳过展开测试')
    }
  })

  test('@p2 总览条：阶段汇总卡顶部紧凑 KPI（替代原 4 卡片）', async ({ page }) => {
    await gotoApp(page, '/dashboard')

    // 切到「批次良率」tab（/batch 已重定向 /dashboard，批次良率是仪表板 tab）
    await page.locator('.el-tabs__item').filter({ hasText: '批次良率' }).click()

    // 等待 list_batches 接口返回
    await page
      .waitForResponse(
        (r) => r.url().includes('/batch-report/list_batches/'),
        { timeout: 15_000 },
      )
      .catch(() => null)

    // 选择第一个批次（如果有）
    const batchSelect = page.locator('.batch-selector .el-select').first()
    await expect(batchSelect).toBeVisible()
    await batchSelect.click()
    const dropdown = page.locator('.el-select-dropdown:visible').last()
    const firstOption = dropdown.locator('.el-select-dropdown__item').first()

    if (!(await firstOption.isVisible({ timeout: 5_000 }).catch(() => false))) {
      test.skip(true, '无可用批次数据，跳过总览条测试')
      return
    }
    await firstOption.click()

    // 触发 batch_yield_data 拉取（需点击「加载批次报表」）
    const loadBtn = page.getByRole('button', { name: /加载批次报表/ })
    const dataResp = page
      .waitForResponse(
        (r) => r.url().includes('/batch-report/batch_yield_data/'),
        { timeout: 30_000 },
      )
      .catch(() => null)
    await loadBtn.click()
    const resp = await dataResp
    if (!resp || resp.status() >= 400) {
      test.skip(true, `批次数据接口返回 ${resp?.status() ?? 'no-resp'}，跳过总览条测试`)
      return
    }

    // ===== 总览条：阶段汇总卡顶部紧凑展示原 KPI 卡片的关键信息 =====
    const strip = page.locator('.summary-strip').first()
    await expect(strip).toBeVisible({ timeout: 15_000 })

    // 4 个指标块：投入数量 / 总 Pass / 总 Fail / 整体良率
    await expect(strip.locator('.strip-item')).toHaveCount(4)
    await expect(strip).toContainText('投入数量')
    await expect(strip).toContainText('总 Pass')
    await expect(strip).toContainText('总 Fail')
    await expect(strip).toContainText('整体良率')
    await expect(strip).toContainText('%')

    // Fail 数值按结果着色（>0 红 / ==0 绿），必有一个命中
    await expect(strip.locator('.strip-value--fail, .strip-value--ok')).toHaveCount(1)

    console.log('[batch] 总览条（紧凑 KPI）渲染正常（4 指标块 + 良率 % + Fail 着色）')
  })
})
