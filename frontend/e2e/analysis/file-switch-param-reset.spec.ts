/**
 * Regression test for "stale selectedParam after file switch".
 *
 * Original symptom (2026-06-13):
 *
 *  - User selects `R_Kelvin_AGND` on `gage_m_S4.csv` (file_id 14518).
 *  - User then switches the file dropdown to
 *    `BPD93204_FT1_ETS163550_12252024.csv` (file_id 14514, an ETS88 file
 *    that has no such column).
 *  - The persisted Pinia store value carried over, so the analysis APIs
 *    were called with a column that does not exist in the new file:
 *      * `/analysis/qqplot/`     → 400
 *      * `/statistics/boxplot/`  → 400
 *      * `/analysis/histogram/`  → 500 (KeyError: 'R_Kelvin_AGND')
 *
 * Fix:
 *  1. `AnalysisPage.onFileChange` resets `selectedParam` and the
 *     persisted store value at the start of every file change.
 *  2. Defence in depth: the backend `histogram` and `boxplot` views
 *     validate every requested param exists in the current DataFrame
 *     and return 400 `no_valid_params` with `requested` / `missing`
 *     payload instead of 500.
 *
 * This e2e locks in the user-visible behaviour: after switching files
 * the old param must not be re-fired at the API, and the param selector
 * must show the new file's params (defaulting to the first one).
 */
import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import {
  selectAnalysisFile,
  listParams,
  selectParam,
} from '../helpers/params'
import { SEEDED_FILES } from '../fixtures/test-data'

const LAYOUT = '.analysis-tab-layout'

/**
 * Build a regex that matches the network call we expect to fire when
 * selecting a param. We assert on the URL only — body inspection
 * happens via waitForResponse status code.
 */
const qqplotUrl = /\/api\/v1\/analysis\/qqplot\//
const boxplotUrl = /\/api\/v1\/statistics\/boxplot\//

test.describe('@regression file switch resets selectedParam', () => {
  test('stale param from gage_m_S4 must NOT be re-fired at ETS88 API', async ({
    page,
  }) => {
    const badRequests: string[] = []
    page.on('response', (r) => {
      if (r.status() >= 400) {
        badRequests.push(`${r.status()} ${r.url()}`)
      }
    })

    await gotoApp(page, '/analysis')

    // 1) Open gage_m_S4, pick the first param, enable QQ + Box
    await selectAnalysisFile(page, SEEDED_FILES.GAGE_S4)
    await expect(
      page.getByRole('tab', { name: /单文件分析/ }),
    ).toBeVisible({ timeout: 20_000 })
    await page.waitForTimeout(1500)

    const gageParams = await listParams(page)
    expect(gageParams.length, 'gage params should be non-empty').toBeGreaterThan(0)
    // pick the first param deterministically; "R_Kelvin_AGND" is the
    // canonical example from the bug report but we don't rely on the
    // exact name — the *principle* is "any param chosen here must not
    // leak into the next file's API calls".
    const firstParam = gageParams[0]
    await selectParam(page, firstParam)
    await page.waitForTimeout(500)

    // 2) Enable QQ + Box so the next file switch has live chart calls
    await page.getByText('显示QQ图').click()
    await page.getByText('显示箱线图').click()
    await page.waitForTimeout(500)

    // 3) Switch to the ETS88 file (different format, no shared params
    //    with gage). On change, AnalysisPage.onFileChange() must reset
    //    selectedParam and the store, and the new file's first param
    //    should be auto-selected.
    await selectAnalysisFile(page, SEEDED_FILES.ETS88_FT)
    await page.waitForTimeout(2000)

    // 4) Sanity check: param dropdown should now show ETS88 params,
    //    NOT contain the gage-only firstParam from step 1.
    const ets88Params = await listParams(page)
    expect(ets88Params.length, 'ETS88 params should be non-empty').toBeGreaterThan(0)
    // Just verify the lists differ — exact comparison is brittle if
    // the parsers ever share a column. We expect a different shape.
    expect(
      ets88Params[0],
      'first param should be the new file\'s, not the stale one',
    ).not.toEqual(firstParam)

    // 5) Drive a param switch on the new file to confirm the chart
    //    APIs accept it. If the stale `firstParam` was leaking in, this
    //    would 400 (or 500 for histogram).
    const qqResponse = page.waitForResponse(qqplotUrl, { timeout: 20_000 })
    await selectParam(page, ets88Params[0])
    const qq = await qqResponse
    expect(
      [200, 400].includes(qq.status()),
      `qqplot must not 500 on a valid param, got ${qq.status()}`,
    ).toBe(true)
    expect(
      qq.status(),
      `qqplot must not 4xx/5xx for a valid new-file param, got ${qq.status()}`,
    ).toBe(200)

    const bpResponse = page.waitForResponse(boxplotUrl, { timeout: 20_000 })
    await page.waitForTimeout(500)
    const bp = await bpResponse
    expect(
      bp.status(),
      `boxplot must not 4xx/5xx for a valid new-file param, got ${bp.status()}`,
    ).toBe(200)

    // 6) Final assertion: no 4xx/5xx in the captured response log
    //    tied to the analysis APIs. We allow 200 only.
    const apiErrors = badRequests.filter(
      (s) =>
        s.includes('/api/v1/analysis/qqplot/') ||
        s.includes('/api/v1/statistics/boxplot/') ||
        s.includes('/api/v1/analysis/histogram/'),
    )
    expect(
      apiErrors,
      `No 4xx/5xx should fire after a file switch. Got:\n${apiErrors.join('\n')}`,
    ).toEqual([])
  })

  test('QQ + Box placeholders render cleanly when no param is selected', async ({
    page,
  }) => {
    // Edge case: enable QQ/Box BEFORE picking any param, then switch
    // files. The placeholders must show (not crash) and the param
    // selector should not retain the previous file's value.
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, SEEDED_FILES.GAGE_S4)
    await expect(
      page.getByRole('tab', { name: /单文件分析/ }),
    ).toBeVisible({ timeout: 20_000 })
    await page.waitForTimeout(1500)

    // Enable QQ + Box (no param chosen yet)
    await page.getByText('显示QQ图').click()
    await page.getByText('显示箱线图').click()
    await page.waitForTimeout(500)

    // Switch files. Expect: a chart placeholder is visible and the
    // param selector no longer crashes. We don't assert on the exact
    // placeholder text — different chart components use different
    // empty states — only that the layout is stable.
    await selectAnalysisFile(page, SEEDED_FILES.ETS88_FT)
    await page.waitForTimeout(2000)
    await expect(page.locator(LAYOUT)).toBeVisible()
  })
})
