import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { captureDownload } from '../helpers/download'
import { SEEDED_FILES } from '../fixtures/test-data'

/**
 * 导出文件名模板（系统设置 → 📄 导出文件名）。
 *
 * 注意：admin storageState 共享 + 设置持久化，任何修改模板的用例必须
 * 在 finally 中恢复默认模板，避免污染后续用例。
 */

const TEMPLATE_KEYS = [
  'to_excel', 'to_csv', 'sigma_limit', 'html_report',
  'batch_charts', 'batch_report', 'buyoff', 'gage',
]

async function restoreTemplates(page: import('@playwright/test').Page) {
  await page.evaluate(async () => {
    const resp = await fetch('/api/v1/auth/settings/', {
      method: 'GET',
      headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` },
    })
    const data = await resp.json()
    const defaults: Record<string, string> = {
      to_excel: '{filename}_analysis',
      to_csv: '{filename}_data',
      sigma_limit: '{filename}_{sigma}sigma_Limit',
      html_report: '{filename}_report',
      batch_charts: '{filename}_batch_charts',
      batch_report: 'Batch_Report_{datetime}',
      buyoff: 'Buyoff_Form_{datetime}',
      gage: 'Gage_Summary_{datetime}',
    }
    await fetch('/api/v1/auth/settings/', {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('access_token')}`,
      },
      body: JSON.stringify({ export_filename_templates: defaults }),
    })
  })
}

test.describe('@p1 导出文件名模板', { tag: ['@p1', '@settings'] }, () => {
  test('渲染：卡片 + 8 行模板输入 + 插入变量/恢复默认可见', async ({ page }) => {
    await gotoApp(page, '/settings')
    await expect(page.getByText('📄 导出文件名')).toBeVisible()

    for (const key of TEMPLATE_KEYS) {
      await expect(page.getByTestId(`template-input-${key}`)).toBeVisible()
    }
    await expect(page.getByTestId('template-insert-to_excel')).toBeVisible()
    await expect(page.getByTestId('template-reset-to_excel')).toBeVisible()
    // 默认值回填
    await expect(page.getByTestId('template-input-to_excel')).toHaveValue('{filename}_analysis')
    await expect(page.getByTestId('template-input-gage')).toHaveValue('Gage_Summary_{datetime}')
  })

  test('保存并持久化：修改 to_excel 模板 → 保存 → reload 保留', async ({ page }) => {
    await gotoApp(page, '/settings')
    const input = page.getByTestId('template-input-to_excel')
    await input.fill('{filename}_{datetime}')

    const [response] = await Promise.all([
      page.waitForResponse(
        (resp) => /\/auth\/settings\//.test(resp.url()) && resp.request().method() === 'PUT',
      ),
      page.getByRole('button', { name: '💾 保存设置' }).click(),
    ])
    expect(response.status()).toBe(200)
    await expect(page.locator('.el-message').filter({ hasText: /保存|成功/ })).toBeVisible()

    await page.reload()
    await expect(page.getByTestId('template-input-to_excel')).toHaveValue('{filename}_{datetime}')

    await restoreTemplates(page)
  })
})

test.describe('@p2 导出文件名模板交互', { tag: ['@p2', '@settings'] }, () => {
  test('插入变量：选择 datetime → 追加到模板末尾 + 预览含时间戳', async ({ page }) => {
    await gotoApp(page, '/settings')
    const input = page.getByTestId('template-input-to_csv')
    await input.fill('{filename}')

    // 打开插入变量下拉并选择 datetime（popper 动画打开后选项才可见）
    await page.getByTestId('template-insert-to_csv').click()
    const datetimeOption = page
      .locator('.el-select-dropdown__item', { hasText: '{datetime}' })
      .filter({ visible: true })
      .first()
    await expect(datetimeOption).toBeVisible()
    await datetimeOption.click()

    await expect(input).toHaveValue('{filename}{datetime}')
    const preview = await page.getByTestId('template-preview-to_csv').textContent()
    expect(preview).toContain('预览')
    // filename 样例 DA35_20260804 + datetime 样例 20260804_123456 紧贴拼接
    expect(preview).toContain('20260804_123456')
    expect(preview).toContain('.csv')
  })

  test('逐行恢复默认：修改 sigma_limit 后点该行恢复默认', async ({ page }) => {
    await gotoApp(page, '/settings')
    const input = page.getByTestId('template-input-sigma_limit')
    await input.fill('{sigma}custom')
    await page.getByTestId('template-reset-sigma_limit').click()
    await expect(input).toHaveValue('{filename}_{sigma}sigma_Limit')
  })

  test('非法字符清洗：模板含 * ? 预览显示 _ 替换', async ({ page }) => {
    await gotoApp(page, '/settings')
    const input = page.getByTestId('template-input-to_excel')
    await input.fill('{filename}*bad?')
    const preview = await page.getByTestId('template-preview-to_excel').textContent()
    expect(preview).toContain('DA35_20260804_bad_.xlsx')
  })

  test('端到端下载名：设置 {filename}_{datetime} → 导出 Excel → 下载名匹配', async ({ page }) => {
    try {
      await gotoApp(page, '/settings')
      const input = page.getByTestId('template-input-to_excel')
      await input.fill('{filename}_{datetime}')
      await page.getByRole('button', { name: '💾 保存设置' }).click()
      await expect(page.locator('.el-message').filter({ hasText: /保存|成功/ })).toBeVisible()

      // 数据页导出
      await gotoApp(page, '/data')
      const searchInput = page.locator('input[placeholder="按文件名/程序名/标签搜索"]')
      await searchInput.fill(SEEDED_FILES.GAGE_S1.slice(0, 15))
      const row = page.locator('.el-table .el-table__row')
        .filter({ hasText: SEEDED_FILES.GAGE_S1.slice(0, 12) }).first()
      await expect(row).toBeVisible({ timeout: 30_000 })
      await row.locator('button').filter({ hasText: '查看' }).click()
      await expect(page.locator('.tab-btn.active')).toContainText('查看数据')
      await expect(page.locator('.ag-root').first()).toBeVisible({ timeout: 30_000 })

      const download = await captureDownload(
        page,
        async () => {
          await page.locator('.content-section:visible').first()
            .locator('button').filter({ hasText: '导出 Excel' }).click()
        },
        'export-templates',
        180_000,
      )
      expect(download.suggestedName).toMatch(/^gage_m_S1_\d{8}_\d{6}\.xlsx$/)
    } finally {
      await restoreTemplates(page)
    }
  })
})
