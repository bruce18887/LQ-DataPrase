import { test, expect } from '@playwright/test'
import { uiLogin } from '../helpers/auth'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, selectParam } from '../helpers/params'

test.describe('Debug Outlier Handling', () => {
  test('capture outlier handling behavior @p0', async ({ page }) => {
    // Collect console logs
    const consoleLogs: string[] = []
    page.on('console', msg => {
      if (msg.type() === 'log' || msg.type() === 'error') {
        consoleLogs.push(`[${msg.type()}] ${msg.text()}`)
      }
    })

    // Intercept API responses
    const apiResponses: any[] = []
    page.on('response', async response => {
      const url = response.url()
      if (url.includes('/analysis/histogram/') && response.status() === 200) {
        try {
          const body = await response.json()
          const results = body.results || {}
          const firstParam = Object.keys(results)[0]
          if (firstParam && results[firstParam]) {
            const r = results[firstParam]
            apiResponses.push({
              param: firstParam,
              outlier_info: r.outlier_info,
              filtered_cpk: r.filtered_cpk,
              mean: r.mean,
              data_min: r.data_min,
              data_max: r.data_max,
            })
          }
        } catch {}
      }
    })

    await uiLogin(page)
    await gotoApp(page, 'analysis')

    // Select first file
    await selectAnalysisFile(page, 0)
    await page.waitForTimeout(2000)

    // Take screenshot of initial state
    await page.screenshot({ path: 'test/debug-outlier-01-initial.png', fullPage: true })

    // Check what the outlier handling dropdown shows
    const outlierDropdown = page.locator('.el-form-item').filter({ hasText: '异常值处理' })
    const dropdownExists = await outlierDropdown.count()
    console.log(`Outlier dropdown exists: ${dropdownExists > 0}`)

    if (dropdownExists > 0) {
      const dropdownText = await outlierDropdown.locator('.el-select__placeholder').textContent()
      console.log(`Current outlier handling value: "${dropdownText}"`)
    }

    // Check if OutlierHintBar exists
    const hintBar = page.locator('.outlier-hint-bar')
    const hintBarCount = await hintBar.count()
    console.log(`OutlierHintBar count: ${hintBarCount}`)
    if (hintBarCount > 0) {
      const hintText = await hintBar.first().textContent()
      console.log(`OutlierHintBar text: "${hintText}"`)
    }

    // Print API response info
    console.log(`\nAPI responses captured: ${apiResponses.length}`)
    for (const r of apiResponses) {
      console.log(`  Param: ${r.param}`)
      console.log(`  outlier_info: ${JSON.stringify(r.outlier_info)}`)
      console.log(`  filtered_cpk: ${r.filtered_cpk}`)
      console.log(`  mean: ${r.mean}, data_min: ${r.data_min}, data_max: ${r.data_max}`)
    }

    // Now switch outlier handling to 'clip'
    if (dropdownExists > 0) {
      await outlierDropdown.locator('.el-select').click()
      await page.waitForTimeout(500)
      await page.screenshot({ path: 'test/debug-outlier-02-dropdown-open.png', fullPage: true })

      // Select '裁剪范围' option
      const clipOption = page.locator('.el-select-dropdown__item').filter({ hasText: '裁剪范围' })
      if (await clipOption.count() > 0) {
        await clipOption.click()
        await page.waitForTimeout(2000)
        await page.screenshot({ path: 'test/debug-outlier-03-clip-selected.png', fullPage: true })

        // Check hint bar again
        const hintBarAfter = page.locator('.outlier-hint-bar')
        const hintBarAfterCount = await hintBarAfter.count()
        console.log(`\nAfter selecting 'clip':`)
        console.log(`  OutlierHintBar count: ${hintBarAfterCount}`)
        if (hintBarAfterCount > 0) {
          const hintTextAfter = await hintBarAfter.first().textContent()
          console.log(`  OutlierHintBar text: "${hintTextAfter}"`)
        }
      } else {
        console.log('Could not find clip option in dropdown')
      }
    }

    // Print all console logs
    if (consoleLogs.length > 0) {
      console.log('\n--- Console logs ---')
      for (const log of consoleLogs) {
        console.log(log)
      }
    }
  })
})
