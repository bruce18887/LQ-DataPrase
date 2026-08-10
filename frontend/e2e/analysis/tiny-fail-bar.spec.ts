import { test, expect } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { gotoApp } from '../helpers/nav'
import { uploadFile } from '../helpers/upload'
import { cleanupQuiet } from '../helpers/cleanup'
import { expectChartRendered, waitLoadingGone } from '../helpers/charts'
import { selectAnalysisFile } from '../helpers/params'

/**
 * 极小 fail 百分比柱状图可见性（1/50000 = 0.002%、1/100000 = 0.001%）。
 *
 * 回归：后端 `round(pct, 2)` 把 0.002 四舍五入成 0.0 → bin 柱高 0 不渲染；
 * 修复后保留 6 位小数 + 前端最小柱高（非零柱 ≥ 0.5% ≈ 2px），
 * tooltip/标签显示真实精度与数量（bin_counts）。
 *
 * 断言链：
 *  - API：bin_percentages 最小非零 ≈ 0.002 / 0.001（旧代码为 0.0，必失败）；
 *    bin_counts 含 1 且总和 == 行数
 *  - DOM：ECharts 实例中「渲染值 > 0 的柱数」==「非零 bin 数」（无 bin 消失），
 *    且最小可见柱高度 ≥ 1.5px（钳制后肉眼可见）
 */

const SINGLE = '.single-param-tab'

/**
 * CTA8280F 最小 CSV：n 行规格内数据（[0.5, 1.99]）+ 1 行超上限（2.5 > max 2.0）fail。
 * 列集刻意精简：Serial_No/Dut_Pass 为非数值（分别被 meta 列排除 / TRUE→NaN），
 * 保证 KELVIN_VIN 是唯一数值参数 → 默认选中即 KELVIN_VIN（若含 Index_No 等
 * 会被识别为数值列排在前头，默认参数变成它们，断言谓词匹配不到）。
 */
function buildCsv(n: number): string {
  const lines = [
    'CTA8280F,',
    'Device Name,TEST_DEVICE,',
    '[Data]',
    'Serial_No,Dut_Pass,KELVIN_VIN,',
    'Unit,Unit,ohm,',
    'Min,Min,0,',
    'Max,Max,2,',
  ]
  for (let i = 1; i <= n; i++) {
    const v = (0.5 + ((i - 1) / (n - 1)) * 1.49).toFixed(4)
    lines.push(`${i},TRUE,${v},`)
  }
  lines.push(`${n + 1},TRUE,2.5,`)
  return lines.join('\n') + '\n'
}

const CASES = [
  { n: 50000, pct: 0.002, label: '1/50000' },
  { n: 100000, pct: 0.001, label: '1/100000' },
]

test.describe('极小 fail 百分比柱状图可见', { tag: ['@p1', '@analysis'] }, () => {
  const files: { n: number; filename: string; path: string }[] = []

  test.beforeAll(() => {
    for (const c of CASES) {
      const filename = `e2e_tiny_fail_${c.n}_${Date.now()}.csv`
      const csvPath = path.join(os.tmpdir(), filename)
      fs.writeFileSync(csvPath, buildCsv(c.n), 'utf-8')
      files.push({ n: c.n, filename, path: csvPath })
    }
  })

  test.afterAll(() => {
    for (const f of files) cleanupQuiet(f.path)
  })

  for (const c of CASES) {
    test(`极小 fail 百分比可见（${c.label}）：精度保留 + 最小柱高`, async ({ page }) => {
      test.setTimeout(180_000) // 10 万行文件上传 + 解析耗时较长
      const f = files.find((x) => x.n === c.n)!

      // 上传
      await gotoApp(page, '/data')
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadFile(page, f.path)
      await expect(page.getByText(/上传成功/).first()).toBeVisible({ timeout: 120_000 })

      // 进入分析页。注意：页面挂载时可能自动选中文件列表第一个文件并触发带参
      // histogram 请求（并行用例可能恰好选中对方用例的文件）——不能用
      // waitForResponse 匹配第一个响应，改为按响应体 filename 精确收集目标
      // 文件的响应（自动选中的文件响应被忽略）。
      const targetResponses: any[] = []
      page.on('response', (resp) => {
        if (
          resp.url().includes('/analysis/histogram/') &&
          resp.request().method() === 'POST' &&
          resp.status() === 200
        ) {
          resp.json().then((b: any) => {
            if (b?.filename === f.filename && b?.results?.KELVIN_VIN?.bin_percentages) {
              targetResponses.push(b)
            }
          }).catch(() => {})
        }
      })
      await gotoApp(page, '/analysis')
      await selectAnalysisFile(page, f.filename)
      await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })

      // API 精度断言：最小非零百分比必须保留（旧代码 round(…, 2) → 0.0 必失败）
      await expect.poll(() => targetResponses.length, { timeout: 30_000 }).toBeGreaterThan(0)
      const body = targetResponses[targetResponses.length - 1]
      const r = body.results?.KELVIN_VIN
      expect(r, 'histogram 响应应含 KELVIN_VIN 结果').toBeTruthy()
      const pcts: number[] = r.bin_percentages || []
      const minNonZero = Math.min(...pcts.filter((v) => v > 0))
      expect(minNonZero, `最小非零百分比应为 ${c.pct}%（不得归零）`).toBeCloseTo(c.pct, 4)
      expect(r.bin_counts, 'bin_counts 应与 bin_centers 对齐下发').toBeDefined()
      expect(r.bin_counts).toContain(1)
      expect(r.bin_counts.reduce((a: number, b: number) => a + b, 0)).toBe(c.n + 1)
      const nonzeroCount = pcts.filter((v) => v > 0).length

      // DOM 断言：非零 bin 的柱全部渲染，且最小可见柱 ≥ 1.5px
      await waitLoadingGone(page.locator(SINGLE))
      const chartDiv = page.locator(`${SINGLE} .histogram-chart-wrapper div[_echarts_instance_]`)
      await expect(chartDiv).toBeVisible({ timeout: 15_000 })
      await expectChartRendered(page.locator(SINGLE), 0)

      // 柱数据取 option 原始值（series[0].data = [x, 渲染值, 真实值, 计数]）；
      // 像素高度按解析式推导：height_px = 渲染值 / yAxisMax * 绘图区高度
      // （grid.top/bottom + 容器高度），与 ECharts 的实际换算一致，不依赖内部 API。
      const barStats = await chartDiv.evaluate((el: any) => {
        const chart = el.__echartsInstance__
        if (!chart) return null
        const opt = chart.getOption() as any
        const barSeries = (opt.series || []).find((s: any) => s.type === 'bar')
        const dataArr: number[][] = Array.isArray(barSeries?.data) ? barSeries.data : []
        const yAxis = (opt.yAxis || []).find((a: any) => a.position === 'left') ?? opt.yAxis?.[0]
        const grid = (opt.grid || [])[0] ?? { top: 0, bottom: 0 }
        const containerH = el.getBoundingClientRect().height
        const plotH = containerH - (grid.top ?? 0) - (grid.bottom ?? 0)
        return { data: dataArr, plotH, yMax: yAxis?.max ?? 100 }
      })
      expect(barStats, 'ECharts 实例应已初始化').not.toBeNull()
      expect(barStats!.plotH, '绘图区高度应有效').toBeGreaterThan(200)

      const rendered = barStats!.data.map((item) => ({
        clamped: Number(item[1] ?? 0),
        real: Number(item[2] ?? item[1] ?? 0),
        height: (Number(item[1] ?? 0) / barStats!.yMax) * barStats!.plotH,
      }))
      // 渲染值 > 0 的柱数 == 非零 bin 数（钳制后无 bin 消失）
      const visibleBars = rendered.filter((b) => b.clamped > 0)
      expect(visibleBars.length, '非零 bin 的柱应全部渲染（无 bin 消失）').toBe(nonzeroCount)
      // 钳制不改变真实值：渲染值 > 0 的柱其真实百分比也 > 0
      expect(visibleBars.every((b) => b.real > 0), '钳制不得虚构非零柱').toBe(true)
      // 最小可见柱高 ≥ 1.5px（0.5% × ~430px 轴高 ≈ 2px）
      const minHeight = Math.min(...visibleBars.map((b) => b.height))
      expect(minHeight, '极小 fail 柱应可见（≥1.5px）').toBeGreaterThanOrEqual(1.5)
      // 主分布柱显著更高：fail 柱应明显矮于峰值柱（钳制保底但不夸张）
      const maxHeight = Math.max(...visibleBars.map((b) => b.height))
      expect(maxHeight, '主分布柱应显著高于 fail 柱').toBeGreaterThan(minHeight * 3)
    })
  }
})
