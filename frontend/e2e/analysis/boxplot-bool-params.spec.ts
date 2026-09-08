/**
 * Regression test for the "compute_boxplot_stats crashes on bool/string columns"
 * bug.
 *
 * Root cause: when a boolean Series (e.g. ``Dut_Pass`` / ``PASSFG``) is fed into
 * ``compute_boxplot_stats``:
 *   - ``pd.to_numeric`` on bool returns the SAME bool Series (no dtype change);
 *   - ``.quantile(0.25)`` returns ``np.bool_`` and the ``q3 - q1`` step raises
 *     "numpy boolean subtract, the `-` operator, is not supported".
 *
 * For object/string Series, the old ``abs(x) < inf`` filter raised
 * "bad operand type for abs(): 'str'".
 *
 * Fix: ``compute_boxplot_stats`` now coerces to float up-front via
 * ``pd.to_numeric(..., errors='coerce').astype(float)`` and filters inf with
 * ``np.isfinite``. These cases now return a valid (degenerate) box-plot result
 * instead of 500.
 *
 * This e2e hits the boxplot endpoint directly with the boolean ``Dut_Pass``
 * column on a file that contains it (``gage_m_S4``). The frontend's histogram
 * param-selector filters out bool/string columns, so this attack surface is
 * only reachable via direct API calls or future code paths — we lock the
 * backend behavior so a regression here can't crash the API.
 */
import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { SEEDED_FILES } from '../fixtures/test-data'

test.describe('@regression boxplot API on non-numeric columns', () => {
  test('POST /statistics/boxplot/ on Dut_Pass (bool) returns 400 no_valid_params（契约升级）', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await page.waitForTimeout(500)

    // Look up the file_id of gage_m_S4 by querying the /files/ endpoint
    // (the same endpoint AnalysisPage.vue uses to populate the file selector).
    // ⚠️ 后端是 JWT-only 认证（base.py DEFAULT_AUTHENTICATION_CLASSES 无
    // SessionAuthentication）：裸 fetch 不带 Authorization 必 401 → fileId 恒 null。
    const fileId = await page.evaluate(async (filename: string) => {
      const r = await fetch(`/api/v1/files/?search=${encodeURIComponent(filename)}`, {
        headers: {
          Accept: 'application/json',
          Authorization: `Bearer ${localStorage.getItem('access_token')}`,
        },
      })
      if (!r.ok) return null
      const body = await r.json()
      const list = Array.isArray(body) ? body : body.results || []
      const found = list.find((f: any) => f.filename === filename || f.original_filename === filename)
      return found?.id ?? null
    }, SEEDED_FILES.GAGE_S4)

    expect(fileId, `must resolve file_id for ${SEEDED_FILES.GAGE_S4}`).toBeTruthy()

    // Direct API call: /statistics/boxplot/?file_id=<id>&params=Dut_Pass
    // Pre-fix: 500 (TypeError: numpy boolean subtract...)
    // Post-fix: 200 with overall.min=0, overall.max=1, overall.count=100
    const result = await page.evaluate(async (fid: number) => {
      const r = await fetch(
        `/api/v1/statistics/boxplot/?file_id=${fid}&params=${encodeURIComponent('Dut_Pass')}`,
        {
          headers: {
            Accept: 'application/json',
            Authorization: `Bearer ${localStorage.getItem('access_token')}`,
          },
        },
      )
      let body: any = null
      try {
        body = await r.json()
      } catch {
        body = await r.text()
      }
      return { status: r.status, body }
    }, fileId as number)

    console.log(`[boxplot Dut_Pass] status=${result.status}`)
    console.log(`[boxplot Dut_Pass] body=${JSON.stringify(result.body).slice(0, 500)}`)

    // 契约（2026-09-08 与后端对齐）：bool 列在视图层 _sanitize_numeric_params
    // 被有意排除（_helpers.py:132 —— pass/fail 标志不是可测参数，画箱线图无意义，
    // 且历史 500 已由 service 层 ensure_numeric astype(float) 双层把守，见
    // tests_param_guards.py test_boolean_series_does_not_crash）。
    // 本用例从「锁 200 退化箱线」升级为「锁 400 no_valid_params」。
    expect(result.status, 'boxplot on boolean column should be 400 (view-level filter)').toBe(400)
    expect(result.body?.error).toBe('no_valid_params')
    expect(result.body?.requested).toEqual(['Dut_Pass'])
  })

  test('POST /statistics/boxplot/ on Site # (str metadata col) returns 400 no_valid_params', async ({
    page,
  }) => {
    // String columns ARE filtered by `_sanitize_numeric_params` at the view
    // level, so the expected response is a 400 "no_valid_params" — not a
    // 500. This test locks down the *error type* so a regression that
    // reintroduces a crash on string columns is caught immediately.
    await gotoApp(page, '/analysis')
    await page.waitForTimeout(500)

    const fileId = await page.evaluate(async (filename: string) => {
      const r = await fetch(`/api/v1/files/?search=${encodeURIComponent(filename)}`, {
        headers: {
          Accept: 'application/json',
          Authorization: `Bearer ${localStorage.getItem('access_token')}`,
        },
      })
      if (!r.ok) return null
      const body = await r.json()
      const list = Array.isArray(body) ? body : body.results || []
      const found = list.find((f: any) => f.filename === filename || f.original_filename === filename)
      return found?.id ?? null
    }, SEEDED_FILES.GAGE_S4)

    expect(fileId).toBeTruthy()

    const result = await page.evaluate(async (fid: number) => {
      const r = await fetch(
        `/api/v1/statistics/boxplot/?file_id=${fid}&params=${encodeURIComponent('Site #')}`,
        {
          headers: {
            Accept: 'application/json',
            Authorization: `Bearer ${localStorage.getItem('access_token')}`,
          },
        },
      )
      let body: any = null
      try {
        body = await r.json()
      } catch {
        body = await r.text()
      }
      return { status: r.status, body }
    }, fileId as number)

    console.log(`[boxplot Site #] status=${result.status}`)
    expect(result.status, 'string col should be filtered to 400, not crash to 500').toBe(400)
    expect(result.body?.error).toBe('no_valid_params')
  })
})
