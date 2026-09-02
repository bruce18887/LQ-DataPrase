import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, selectParam, listParams } from '../helpers/params'
import { waitLoadingGone } from '../helpers/charts'
import { RECOMMENDED } from '../fixtures/test-data'

const SINGLE = '.single-param-tab'

/**
 * 「敏感度 (IQR 倍数)」是页头控件，值存在 analysisStore.iqrMultiplier。
 * 单参数直方图按此倍数向后端请求异常值边界，所以页头改档位后必须重发。
 *
 * 断言只认「单参数直方图」请求：body.params === [选中参数]。
 * 页面级 /analysis/histogram/（拉参数列表）不带 params 字段，且它直接读
 * store、本来就是对的 —— 若只按 iqr_multiplier 匹配就会误判成已修复。
 */
function watchParamHistogram(page: import('@playwright/test').Page, param: string) {
  const multipliers: number[] = []
  page.on('request', (req) => {
    if (!req.url().includes('/analysis/histogram/') || req.method() !== 'POST') return
    let body: any
    try {
      body = JSON.parse(req.postData() || '{}')
    } catch {
      return
    }
    if (!Array.isArray(body.params) || body.params.length !== 1 || body.params[0] !== param) return
    multipliers.push(body.iqr_multiplier)
  })
  return multipliers
}

function outlierSelect(page: import('@playwright/test').Page) {
  return page.locator('.el-form-item').filter({ hasText: '异常值处理' }).locator('.el-select').first()
}

// 敏感度只在 异常值处理 !== 'off' 时渲染
function sensitivitySelect(page: import('@playwright/test').Page) {
  return page.locator('.el-form-item').filter({ hasText: '敏感度' }).locator('.el-select').first()
}

test.describe('@p1 敏感度状态传播', { tag: ['@p1', '@analysis'] }, () => {
  test('页头切到「宽松 (3.0x IQR)」后单参数直方图应以 3.0 重发', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))

    const params = await listParams(page)
    expect(params.length).toBeGreaterThan(0)
    await selectParam(page, params[0])
    await waitLoadingGone(page.locator(SINGLE))

    await outlierSelect(page).click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: '裁剪范围' }).first().click()
    await expect(sensitivitySelect(page)).toBeVisible({ timeout: 10_000 })

    // 计数器装好之后再改敏感度，避免把前置请求计入
    const seen = watchParamHistogram(page, params[0])

    await sensitivitySelect(page).click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: '宽松' }).first().click()
    await waitLoadingGone(page.locator(SINGLE))
    // 给"修复前完全不发请求"留出观察窗口
    await page.waitForTimeout(1_000)

    expect(seen.length, '改敏感度应重发当前参数的直方图请求').toBeGreaterThan(0)
    expect(seen[seen.length - 1], '直方图请求应携带新的 IQR 倍数').toBe(3)
  })
})
