/**
 * Focused repro for: "QQ图显示SW_Bin 测试项还是会报错"
 *
 * Hypothesis to validate:
 *   SW_Bin is a soft-bin column where all values are 1.0 in gage_m_S4.
 *   Backend returns observed_quantiles = [1.0] * 100 + r_squared = null.
 *   We assert whether selecting SW_Bin + showing QQ plot throws
 *   "emitsOptions null" or any other pageerror.
 */
import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, selectParam } from '../helpers/params'
import { SEEDED_FILES } from '../fixtures/test-data'

test.describe('@regression QQ plot for SW_Bin', () => {
  test('SW_Bin on gage_m_S4 should not throw emitsOptions', async ({ page }) => {
    const pageErrors: string[] = []
    page.on('pageerror', (err) => {
      pageErrors.push(`[pageerror] ${err.message}`)
    })
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        const t = msg.text()
        if (t.includes('emitsOptions') || t.includes('TypeError')) {
          pageErrors.push(`[console.error] ${t}`)
        }
      }
    })

    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, SEEDED_FILES.GAGE_S4)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await page.waitForTimeout(1500)

    // 1) Select SW_Bin first
    await selectParam(page, 'SW_Bin')
    await page.waitForTimeout(1500)

    // 2) Enable QQ plot
    await page.getByText('显示QQ图').click()
    await page.waitForTimeout(2500)

    console.log('========== Page errors ==========')
    pageErrors.forEach((e) => console.log(e))
    console.log('=================================')

    const emitsOptionsErrors = pageErrors.filter((e) => e.includes('emitsOptions'))
    expect(emitsOptionsErrors, `Should not throw "emitsOptions" errors, got:\n${pageErrors.join('\n')}`).toEqual([])
  })
})
