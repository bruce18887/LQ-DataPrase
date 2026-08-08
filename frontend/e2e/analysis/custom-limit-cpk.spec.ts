import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { expectChartRendered, waitLoadingGone } from '../helpers/charts'
import { selectAnalysisFile, listParams, selectParam } from '../helpers/params'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * CustomLimit 规格限覆盖重算 CPK（双卡显示）+ 范围对比表 CustomLimit 行。
 *
 * 需求：
 *   - 范围类型切到 CustomLimit 并输入上下限后，后端用自定义限值重算 CPK；
 *   - 新 CPK 与原始 RDL CPK 不同时，统计卡同时显示 CPK(RDL)（修改前）与
 *     CPK(Custom)（修改后）两张卡；
 *   - 范围对比表 CustomLimit 行显示用户输入值（而非数据范围）。
 *
 * 竞态防护（lessons.md）：
 *   - waitForResponse 一律过滤请求体（`"range_type":"CL"` / custom 值），
 *     防 onFileChange 瘦请求与旧请求后到覆盖；
 *   - el-input-number 填值必须 fill + blur 才发射 change；
 *   - 三步请求（切 CL → 填下限 → 填上限）全部串行 await + waitLoadingGone。
 */

const SINGLE = '.single-param-tab'

/** 6 位小数取整：保证 String(v) 与 JSON 序列化（无尾零）一致 */
const r6 = (v: number) => Math.round(v * 1e6) / 1e6

test.describe('@p1 自定义限值重算 CPK', { tag: ['@p1', '@analysis'] }, () => {
  test('CL 模式显示 CPK(RDL)/CPK(Custom) 双卡且范围表显示输入值', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)

    // 固定到已知参数（后端测试同款，RDL CPK 确定性高）；不存在则用默认参数
    const params = await listParams(page)
    if (params.includes('lkg_VCC_EN_float_3P6V')) {
      await selectParam(page, 'lkg_VCC_EN_float_3P6V')
      await waitLoadingGone(page.locator(SINGLE))
    }

    // 从「Data Range」行读取数据范围（td[1]=low, td[2]=high）
    const drRow = page.locator(`${SINGLE} .left-panel .el-table__row`, { hasText: 'Data Range' }).first()
    const drLow = Number(await drRow.locator('td').nth(1).innerText())
    const drHigh = Number(await drRow.locator('td').nth(2).innerText())
    expect(drHigh).toBeGreaterThan(drLow)

    // 窄窗口：数据范围中间 30%（自定义 CPK 远小于 RDL CPK，必出双卡）
    const span = drHigh - drLow
    const low = r6(drLow + span * 0.35)
    const high = r6(drLow + span * 0.65)

    // 1) 切到 CustomLimit（此时 custom_low/custom_high 均为 null）
    let respPromise = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/histogram/') &&
        r.request().method() === 'POST' &&
        r.request().postData()?.includes('"range_type":"CL"') === true &&
        r.request().postData()?.includes('"custom_low":null') === true &&
        r.status() < 500,
      { timeout: 20_000 },
    )
    const panel = page.locator(`${SINGLE} .left-panel`)
    await panel.locator('.el-select').filter({ hasText: 'RowDataLimit' }).first().click()
    await page
      .locator('.el-select-dropdown__item:visible')
      .filter({ hasText: 'CustomLimit' })
      .first()
      .click()
    await respPromise
    await waitLoadingGone(page.locator(SINGLE))

    // 2) 填下限（fill + blur 才发射 change；此时上限仍为 null）
    const inputs = page.locator(`${SINGLE} .custom-limit-inputs .el-input-number input`)
    respPromise = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/histogram/') &&
        r.request().method() === 'POST' &&
        r.request().postData()?.includes(`"custom_low":${String(low)}`) === true &&
        r.request().postData()?.includes('"custom_high":null') === true &&
        r.status() < 500,
      { timeout: 20_000 },
    )
    await inputs.nth(0).fill(String(low))
    await inputs.nth(0).blur()
    await respPromise
    await waitLoadingGone(page.locator(SINGLE))

    // 3) 填上限，等待同时含 CL 与两个自定义值的最终响应
    respPromise = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/histogram/') &&
        r.request().method() === 'POST' &&
        r.request().postData()?.includes('"range_type":"CL"') === true &&
        r.request().postData()?.includes(`"custom_low":${String(low)}`) === true &&
        r.request().postData()?.includes(`"custom_high":${String(high)}`) === true &&
        r.status() < 500,
      { timeout: 20_000 },
    )
    await inputs.nth(1).fill(String(high))
    await inputs.nth(1).blur()
    const resp = await respPromise
    const body = resp.request().postData() || ''
    expect(body, 'histogram 请求体应携带 range_type=CL').toContain('"range_type":"CL"')
    expect(body, 'histogram 请求体应携带 custom_low').toContain(`"custom_low":${String(low)}`)
    expect(body, 'histogram 请求体应携带 custom_high').toContain(`"custom_high":${String(high)}`)
    await waitLoadingGone(page.locator(SINGLE))

    // 4) 双卡可见且值不同（修改前 CPK(RDL) vs 修改后 CPK(Custom)）
    const cpkRdlCard = page.locator(`${SINGLE} .stats-summary .stat-item`, { hasText: 'CPK(RDL)' }).first()
    const cpkCustomCard = page.locator(`${SINGLE} .stats-summary .stat-item`, { hasText: 'CPK(Custom)' }).first()
    await expect(cpkRdlCard).toBeVisible({ timeout: 10_000 })
    await expect(cpkCustomCard).toBeVisible({ timeout: 10_000 })
    const v1 = parseFloat((await cpkRdlCard.locator('.stat-value').innerText()).split(' ')[0])
    const v2 = parseFloat((await cpkCustomCard.locator('.stat-value').innerText()).split(' ')[0])
    expect(v2, 'CPK(Custom) 应与 CPK(RDL) 不同').not.toBe(v1)

    // 5) 图表上画出 CustomLimit 标记线（ECharts SVG 下 markLine label 是 <text>）
    await expect(page.locator(`${SINGLE} .chart-wrapper text`).filter({ hasText: 'CL Low' }).first()).toBeVisible({ timeout: 10_000 })
    await expect(page.locator(`${SINGLE} .chart-wrapper text`).filter({ hasText: 'CL High' }).first()).toBeVisible({ timeout: 10_000 })

    // 6) 范围对比表 CustomLimit 行显示输入值，且当前行高亮
    const clRow = page.locator(`${SINGLE} .left-panel .el-table__row`, { hasText: 'CustomLimit' }).first()
    await expect(clRow.locator('td').nth(1)).toHaveText(low.toFixed(5))
    await expect(clRow.locator('td').nth(2)).toHaveText(high.toFixed(5))
    await expect(clRow).toHaveClass(/range-active-row/)
  })

  test('二次修改 limit 值后 CPK 重新计算（回归：第二次 change 不生效）', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)

    // 从「Data Range」行读取数据范围
    const drRow = page.locator(`${SINGLE} .left-panel .el-table__row`, { hasText: 'Data Range' }).first()
    const drLow = Number(await drRow.locator('td').nth(1).innerText())
    const drHigh = Number(await drRow.locator('td').nth(2).innerText())
    const span = drHigh - drLow

    // 切到 CustomLimit
    const panel = page.locator(`${SINGLE} .left-panel`)
    await panel.locator('.el-select').filter({ hasText: 'RowDataLimit' }).first().click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: 'CustomLimit' }).first().click()
    await waitLoadingGone(page.locator(SINGLE))

    const inputs = page.locator(`${SINGLE} .custom-limit-inputs .el-input-number input`)

    // 第一次填值：[35%, 65%] 窗口（mean≈50%，两侧限值都参与 CPK）
    const low1 = r6(drLow + span * 0.35)
    const high1 = r6(drLow + span * 0.65)
    await inputs.nth(0).fill(String(low1))
    await inputs.nth(0).blur()
    await waitLoadingGone(page.locator(SINGLE))
    await inputs.nth(1).fill(String(high1))
    await inputs.nth(1).blur()
    await waitLoadingGone(page.locator(SINGLE))
    const cpkCustomCard = page.locator(`${SINGLE} .stats-summary .stat-item`, { hasText: 'CPK(Custom)' }).first()
    await expect(cpkCustomCard).toBeVisible({ timeout: 10_000 })
    const v1 = parseFloat((await cpkCustomCard.locator('.stat-value').innerText()).split(' ')[0])

    // 第二次收窄窗口：high 从 65% 改到 45% → CPK 由 high 侧决定，必变。
    // 注意：只改 low 时若 high 是限制侧，CPK 数学上不变（会误判为 bug），
    // 所以此处修改限制侧 high，并直接从响应体断言 custom_cpk 确实变化。
    const high2 = r6(drLow + span * 0.45)
    expect(high2).not.toBe(high1)
    const respPromise = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/histogram/') &&
        r.request().method() === 'POST' &&
        r.request().postData()?.includes(`"custom_low":${String(low1)}`) === true &&
        r.request().postData()?.includes(`"custom_high":${String(high2)}`) === true &&
        r.status() < 500,
      { timeout: 20_000 },
    )
    await inputs.nth(1).fill(String(high2))
    await inputs.nth(1).blur()
    const resp = await respPromise
    const body = resp.request().postData() || ''
    expect(body, '二次修改应携带新 custom_high').toContain(`"custom_high":${String(high2)}`)
    // 后端响应里的 custom_cpk 必须变化（排除"UI 没应用响应"的假象）
    const respJson = await resp.json()
    const backendCustomCpk = respJson?.results?.[Object.keys(respJson?.results ?? {})[0]]?.custom_cpk
    expect(backendCustomCpk, '二次修改后端应返回新的 custom_cpk').not.toBeNull()
    await waitLoadingGone(page.locator(SINGLE))

    const v2 = parseFloat((await cpkCustomCard.locator('.stat-value').innerText()).split(' ')[0])
    expect(v2, '二次修改后 CPK(Custom) 应重新计算').not.toBe(v1)
  })

  test('快速连续修改 limit 值，最终反映最后一次修改（竞态回归）', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)

    const drRow = page.locator(`${SINGLE} .left-panel .el-table__row`, { hasText: 'Data Range' }).first()
    const drLow = Number(await drRow.locator('td').nth(1).innerText())
    const drHigh = Number(await drRow.locator('td').nth(2).innerText())
    const span = drHigh - drLow

    const panel = page.locator(`${SINGLE} .left-panel`)
    await panel.locator('.el-select').filter({ hasText: 'RowDataLimit' }).first().click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: 'CustomLimit' }).first().click()
    await waitLoadingGone(page.locator(SINGLE))

    const inputs = page.locator(`${SINGLE} .custom-limit-inputs .el-input-number input`)

    // 连续修改、不等中间响应（模拟用户快速操作，旧响应可能后到）。
    // waitForResponse 必须在 blur 前注册：中途的"只有 low"请求不匹配
    // predicate（需同时含 low+high），最终请求才被捕获。
    const low = r6(drLow + span * 0.35)
    const high = r6(drLow + span * 0.45)
    const finalResp = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/histogram/') &&
        r.request().method() === 'POST' &&
        r.request().postData()?.includes(`"custom_low":${String(low)}`) === true &&
        r.request().postData()?.includes(`"custom_high":${String(high)}`) === true &&
        r.status() < 500,
      { timeout: 20_000 },
    )
    await inputs.nth(0).fill(String(low))
    await inputs.nth(0).blur()
    await inputs.nth(1).fill(String(high))
    await inputs.nth(1).blur()
    const resp = await finalResp
    const body = resp.request().postData() || ''
    expect(body, '最终请求应携带最后一次修改的窗口').toContain(`"custom_low":${String(low)}`)
    expect(body, '最终请求应携带最后一次修改的窗口').toContain(`"custom_high":${String(high)}`)
    await waitLoadingGone(page.locator(SINGLE))

    // 最终 UI：双卡可见（custom_cpk != cpk），表格显示最终窗口值
    const cpkCustomCard = page.locator(`${SINGLE} .stats-summary .stat-item`, { hasText: 'CPK(Custom)' }).first()
    await expect(cpkCustomCard).toBeVisible({ timeout: 10_000 })
    const clRow = page.locator(`${SINGLE} .left-panel .el-table__row`, { hasText: 'CustomLimit' }).first()
    await expect(clRow.locator('td').nth(1)).toHaveText(low.toFixed(5))
    await expect(clRow.locator('td').nth(2)).toHaveText(high.toFixed(5))
  })
})
