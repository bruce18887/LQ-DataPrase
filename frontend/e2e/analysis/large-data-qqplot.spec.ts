/**
 * Regression test: 大文件（数万行，如 E263105801 批次 68k 行 CSV）启用 QQ 图时
 * 崩溃 "RangeError: Maximum call stack size exceeded"。
 *
 * Root cause: 后端 compute_qqplot 逐行返回一个分位数对（无降采样），前端
 * QQPlotChart.vue 原先用 Math.min(...allValues) / Math.max(...allValues) 把
 * ~13.6 万个值展开为函数参数 —— 超出 JS 引擎调用栈上限（实测 ~11 万即崩）。
 *
 * Fix: 单趟循环求 min/max + 大数据量（≥5000 点）切 large 模式 + canvas 渲染；
 * 后端对 >5000 点的分位数做保形降采样（→≤2000 点，响应 1.3MB→0.04MB）。
 * 本用例上传 8 万行合成 CTA8280F 文件（16 万值，远超崩溃阈值），断言
 * QQ 图正常渲染且无 pageerror。
 */
import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { gotoApp } from '../helpers/nav'
import { uploadFile, expectUploadSuccess } from '../helpers/upload'
import { selectAnalysisFile, selectParam } from '../helpers/params'
import { waitLoadingGone } from '../helpers/charts'
import { cleanupQuiet } from '../helpers/cleanup'

const SINGLE = '.single-param-tab'

/** 生成 CTA8280F 格式合成大文件（窄列、确定性数值，文件小解析快） */
function buildLargeCsv(rows: number): string {
  const lines = [
    'CTA8280F,,,,,,,,',
    'Device ID,140000',
    'Device Name,BIG_DATA_QQPLOT',
    'TestFileName,C:\\TMS\\BIG_DATA_QQPLOT.dll',
    '[Data],,,,,,,,,',
    'Index_No,Dut_No,Serial_No,Site_No,Dut_Pass,SW_Bin,CON_VIN,CON_VCC',
    'Unit,Unit,Unit,Unit,Unit,Unit,V,V',
    'Min,Min,Min,Min,Min,Min,-0.57,-0.58',
    'Max,Max,Max,Max,Max,Max,-0.39,-0.40',
  ]
  for (let i = 1; i <= rows; i++) {
    // 确定性正弦波动，围绕规格限分布，避免随机导致 flaky
    const vin = -0.48 + 0.005 * Math.sin(i)
    const vcc = -0.49 + 0.005 * Math.cos(i * 0.7)
    lines.push(`${i},${i},${i},1,TRUE,1,${vin.toFixed(4)},${vcc.toFixed(4)}`)
  }
  return lines.join('\n') + '\n'
}

test.describe('大数据文件 QQ 图：不栈溢出 + 正常渲染（回归）', { tag: ['@p1', '@analysis'] }, () => {
  // 8 万行 → 理论/观测各 8 万个值 → 展开参数 16 万，远超崩溃阈值（~11 万）
  const ROWS = 80_000
  let filename = ''
  let csvPath = ''

  test.beforeAll(() => {
    filename = `e2e_large_qqplot_${Date.now()}.csv`
    csvPath = path.join(os.tmpdir(), filename)
    fs.writeFileSync(csvPath, buildLargeCsv(ROWS), 'utf-8')
  })

  test.afterAll(() => {
    cleanupQuiet(csvPath)
  })

  test('8 万行文件 QQ 图正常渲染且无 Maximum call stack 错误', async ({ page }) => {
    const pageErrors: string[] = []
    page.on('pageerror', (err) => {
      pageErrors.push(`[pageerror] ${err.message}`)
    })

    // 上传大文件（上传端点同步解析，解析完成后才返回成功）
    await gotoApp(page, '/data')
    await page.locator('button').filter({ hasText: '上传文件' }).click()
    await uploadFile(page, csvPath)
    await expectUploadSuccess(page, 120_000)

    // 分析页：选文件 → 参数列表加载 → 启用 QQ 图
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, filename)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))

    await page.getByText('显示QQ图').click()

    const respPromise = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/qqplot/') &&
        r.request().method() === 'POST' &&
        (r.request().postData() ?? '').includes('"param":"CON_VIN"'),
      { timeout: 30_000 },
    )
    await selectParam(page, 'CON_VIN')
    const resp = await respPromise
    expect(resp.status(), 'qqplot 接口应返回 200').toBe(200)
    // 大响应不做全局 gzip：GZipMiddleware 已于 45f741e 移除（实测压缩 68MB JSON
    // 耗 3.6s > localhost 传输 0.2s，见 config/settings/base.py MIDDLEWARE 注释）。
    // 若将来部署到 LAN/WAN 改由 nginx 或定向压缩负责，届时同步此断言。
    expect(
      resp.headers()['content-encoding'] ?? '',
      '本机直连不应出现 gzip（响应体由降采样而非压缩控制）',
    ).toBe('')

    // 关键断言：后端大数据保形降采样：8 万点分位数 → ≤2000 点（68k 行文件响应
    // 1.3MB → 0.04MB）；点数必须大于 0（有效数据）
    const body = await resp.json()
    const bodyBytes = (await resp.body()).length
    expect(bodyBytes, '降采样后 8 万行 qqplot 响应体应远小于原始数据量').toBeLessThan(300_000)
    const qLen = body.theoretical_quantiles?.length ?? 0
    expect(qLen, 'qqplot 应返回降采样后的分位数（≤2000）').toBeGreaterThan(0)
    expect(qLen, 'qqplot 分位数不应超过降采样上限').toBeLessThanOrEqual(2000)

    // 关键断言：QQ 图容器内必须渲染出尺寸有效的图表元素（svg 或 canvas——
    // 降采样后 2000 点走 SVG 渲染器，无需再强制 canvas）。
    // 旧代码 Math.min(...) 展开 16 万参数抛 RangeError，被 useChart 的 try/catch
    // 吞掉（仅 console.warn，不冒泡成 pageerror），.qqplot-container 永远为空——
    // 只有「容器内出现图表元素」才能钉住此回归（histogram 等其他图表也在
    // .single-param-tab 内，不能拿它们的结果来掩盖 QQ 图失败）
    const qqScope = page.locator(`${SINGLE} .qqplot-container`)
    await expect
      .poll(
        async () => {
          const els = await qqScope.locator('svg, canvas').evaluateAll((nodes) =>
            nodes.map((el) => ({ w: el.clientWidth, h: el.clientHeight })),
          )
          return els.filter((b) => b.w > 0 && b.h > 0).length
        },
        { timeout: 20_000, message: 'QQ 图容器内应出现尺寸有效的图表元素' },
      )
      .toBeGreaterThan(0)

    // 不得出现栈溢出 / 任何 pageerror
    const stackErrors = pageErrors.filter(
      (e) => e.includes('Maximum call stack') || e.includes('RangeError'),
    )
    expect(stackErrors, `QQ 图不应栈溢出，实际 pageerror:\n${pageErrors.join('\n')}`).toEqual([])
  })
})
