import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, pickTabFile } from '../helpers/params'
import { waitLoadingGone } from '../helpers/charts'
import { pickOption } from '../helpers/elplus'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 轴刻度小数位精度（2026-08-13 回归）：
 * 所有分析图表共用共享工具 formatAxisValue——整数原样、非整数最多 4 位小数
 * 并去尾零（10.5 → "10.5"、12.34567 → "12.3457"）。此前 QQ 图 Y 轴 / 相关性
 * 散点 X/Y / 箱线图 Y 轴无 formatter，浮点精度会显示一长串小数。
 *
 * 断言方式：useChart 会把 ECharts 实例挂到容器 DOM 的 __echartsInstance__
 * （histogram-fail-bins 既有范式），在页面上下文直接调用 formatter 函数——
 * 与渲染器无关（QQ/序列大文件是 canvas，无 svg text 可查），返回值是字符串
 * 序列化安全。实例就绪以「容器内出现 svg/canvas」为前提（init 完成 + option
 * 已应用），再轮询 formatter，避免零尺寸容器异步 init 的时序竞态。
 */

const SINGLE = '.single-param-tab'
/** 直方图 X 轴应输出（共享智能格式） */
const SMART_CASES: Array<[number, string]> = [
  [12.34567, '12.3457'],
  [10, '10'],
  [10.5, '10.5'],
]
// SITE_COLORS_8 亮色主题版（Tol muted，chart-bar.ts getSiteColors8(false)）
const PALETTE_8 = ['#0077BB', '#EE7733', '#009988', '#CC3311', '#33BBEE', '#EE3377', '#BBBBBB', '#648FFF']

/**
 * 页面上下文里按选择器取「可见容器」（el-tabs 非活动 pane 为 display:none，
 * querySelector 只取第一个会命中隐藏实例；:visible 是 Playwright 伪类，
 * 页面上下文不可用，须用 offsetParent 判定可见性）
 */
const PAGE_SELECTOR_FN = `(sel) => {
  const els = Array.from(document.querySelectorAll(sel));
  return els.find((e) => e.offsetParent !== null) ?? els[0];
}`

/** 等待容器内 ECharts 实际渲染（init 完成 + option 已应用） */
async function waitChartRendered(page: import('@playwright/test').Page, containerSelector: string, timeout = 20_000) {
  await expect
    .poll(async () => {
      const el = await page.evaluate(
        ([sel, finderSrc]) => {
          const finder = new Function(`return (${finderSrc})`)() as (s: string) => any
          const el = finder(sel)
          return !!el?.querySelector('svg, canvas')
        },
        [containerSelector, PAGE_SELECTOR_FN] as const,
      )
      return el
    }, { timeout })
    .toBe(true)
}

/** 读取指定容器 ECharts 实例的 axisLabel.formatter 在 v 上的输出（轮询等待实例就绪） */
async function axisFormatterOutput(
  page: import('@playwright/test').Page,
  containerSelector: string,
  axis: 'xAxis' | 'yAxis',
  v = 12.34567,
): Promise<string | null> {
  for (let i = 0; i < 150; i++) {
    const out = await page.evaluate(
      ([sel, a, val, finderSrc]) => {
        const finder = new Function(`return (${finderSrc})`)() as (s: string) => any
        const el = finder(sel)
        const chart = el?.__echartsInstance__
        const fn = chart?.getOption?.()?.[a]?.[0]?.axisLabel?.formatter
        if (typeof fn !== 'function') return null
        return fn(val) as string
      },
      [containerSelector, axis, v, PAGE_SELECTOR_FN] as const,
    )
    if (out !== null) return out
    await page.waitForTimeout(100)
  }
  return null
}

/** 读取 ECharts option 的某段配置（轮询等待就绪；picker 转字符串后构造，Playwright 只序列化 JSON 参数） */
async function readOption(
  page: import('@playwright/test').Page,
  containerSelector: string,
  picker: (opt: any) => unknown,
): Promise<unknown> {
  const pickerSrc = picker.toString()
  for (let i = 0; i < 150; i++) {
    const out = await page.evaluate(
      ([sel, fnSrc, finderSrc]) => {
        const finder = new Function(`return (${finderSrc})`)() as (s: string) => any
        const el = finder(sel)
        const chart = el?.__echartsInstance__
        const opt = chart?.getOption?.()
        if (!opt) return null
        const fn = new Function('opt', `return (${fnSrc})(opt)`) as (o: any) => unknown
        return fn(opt)
      },
      [containerSelector, pickerSrc, PAGE_SELECTOR_FN] as const,
    )
    if (out !== null && out !== undefined) return out
    await page.waitForTimeout(100)
  }
  return null
}

async function assertSmartFormatter(
  page: import('@playwright/test').Page,
  containerSelector: string,
  axis: 'xAxis' | 'yAxis',
) {
  for (const [input, expected] of SMART_CASES) {
    const out = await axisFormatterOutput(page, containerSelector, axis, input)
    expect(out, `${axis} formatter(${input}) 应为 "${expected}"`).toBe(expected)
  }
}

async function enterAnalysis(page: import('@playwright/test').Page, filename?: string) {
  await gotoApp(page, '/analysis')
  await selectAnalysisFile(page, filename)
  await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
}

test.describe('@p1 轴刻度小数位精度（formatAxisValue 统一）', { tag: ['@p1', '@analysis'] }, () => {
  test('直方图 X 轴：智能 4 位格式 + 轴刻度无 5 位以上小数', async ({ page }) => {
    await gotoApp(page, '/analysis')
    // 先注册 histogram 响应监听再选文件（首次挂载即自动请求，含参数计算路径）
    const histResp = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/histogram/') &&
        r.request().method() === 'POST' &&
        (r.request().postData() || '').includes('"param"') &&
        r.status() < 500,
      { timeout: 30_000 },
    )
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))
    // 响应可能已在注册前发出（页面挂载自动选文件即请求），超时视为已加载，以渲染轮询为准
    await histResp.catch(() => null)

    const container = `${SINGLE} .chart-wrapper--top .chart-container`
    await waitChartRendered(page, container)
    await assertSmartFormatter(page, container, 'xAxis')

    // 渲染出的刻度文本不应出现 5 位以上小数（SVG 渲染器；KDE/正态密度轴是
    // toExponential(2)，不匹配 \d+\.\d{5,}）
    await expect
      .poll(async () => {
        const texts = (await page.locator(`${SINGLE} .chart-wrapper--top text`).allTextContents()).join(' | ')
        return /\d+\.\d{5,}/.test(texts) ? texts : ''
      }, { timeout: 10_000 })
      .toBe('')
  })

  test('QQ 图 X/Y 轴：智能 4 位格式 + fontSize 9 + 标题 15', async ({ page }) => {
    await enterAnalysis(page, RECOMMENDED.analysis)
    await waitLoadingGone(page.locator(SINGLE))

    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/analysis/qqplot/') && r.status() < 500,
      { timeout: 25_000 },
    )
    await page.getByText('显示QQ图').click()
    await respPromise

    const container = `${SINGLE} .qqplot-container`
    await waitChartRendered(page, container)
    await assertSmartFormatter(page, container, 'xAxis')
    await assertSmartFormatter(page, container, 'yAxis')

    const axisLabel = await readOption(page, container, (opt) => opt.xAxis?.[0]?.axisLabel)
    expect((axisLabel as any)?.fontSize, 'X 轴刻度字号应统一为 9').toBe(9)
    const title = await readOption(page, container, (opt) => opt.title?.[0]?.textStyle)
    expect((title as any)?.fontSize, '标题字号应统一为 15').toBe(15)
  })

  test('序列分布 Y 轴：智能 4 位格式 + 8 色板 + 标题 15', async ({ page }) => {
    await enterAnalysis(page, RECOMMENDED.analysis)
    await waitLoadingGone(page.locator(SINGLE))

    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/analysis/serial_distribution/') && r.request().method() === 'POST' && r.status() < 500,
      { timeout: 30_000 },
    )
    await page.locator('.el-radio-button').filter({ hasText: '序列分布' }).first().click()
    await respPromise
    await expect(page.locator(`${SINGLE} .serial-chart-wrapper`)).toBeVisible({ timeout: 20_000 })

    const container = `${SINGLE} .serial-chart-wrapper div[_echarts_instance_]`
    await waitChartRendered(page, container)
    await assertSmartFormatter(page, container, 'yAxis')

    const firstSeries = await readOption(page, container, (opt) => opt.series?.[0]?.itemStyle?.color)
    expect(PALETTE_8, '系列色应来自直方图 8 色板').toContain(firstSeries)
    const title = await readOption(page, container, (opt) => opt.title?.[0]?.textStyle)
    expect((title as any)?.fontSize, '标题字号应统一为 15').toBe(15)
  })

  test('相关性散点 X/Y 轴：智能 4 位格式（用户点名回归）', async ({ page }) => {
    await enterAnalysis(page, RECOMMENDED.analysis)
    await page.getByRole('tab', { name: /相关性对比/ }).click()
    // 相关性 tab 吃自己那份文件选择：不选到 CTA8280F 就没有 KELVIN_VIN/KELVIN_SW
    await pickTabFile(page, 'correlation', RECOMMENDED.analysis)

    const layout = page.locator('.analysis-tab-layout:visible')
    await expect(layout).toBeVisible({ timeout: 10_000 })

    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/analysis/correlation/') && r.request().method() === 'POST' && r.status() < 500,
      { timeout: 30_000 },
    )
    await pickOption(page, '选择 X 轴参数', 'KELVIN_VIN', layout)
    // X 下拉关闭动画与 Y 下拉打开重叠会导致选项瞬时不稳定，间隔后再选 Y
    await page.waitForTimeout(600)
    await pickOption(page, '选择 Y 轴参数', 'KELVIN_SW', layout)
    await respPromise

    // locator 用 :visible 唯一化；页面上下文用不带伪类的选择器（finder 内部判可见性）
    const container = '.analysis-tab-layout .chart-inner'
    await waitChartRendered(page, container)
    await assertSmartFormatter(page, container, 'xAxis')
    await assertSmartFormatter(page, container, 'yAxis')
  })

  test('箱线图 Y 轴：智能 4 位格式 + 箱体固定直方图蓝', async ({ page }) => {
    await enterAnalysis(page, RECOMMENDED.analysis)
    await waitLoadingGone(page.locator(SINGLE))

    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/statistics/boxplot/') && r.status() < 500,
      { timeout: 30_000 },
    )
    await page.getByText('显示箱线图').click()
    await respPromise

    const container = `${SINGLE} .chart-wrapper--bottom .chart-container`
    await waitChartRendered(page, container)
    await assertSmartFormatter(page, container, 'yAxis')

    const boxSeries = await readOption(page, container, (opt) =>
      (opt.series || []).find((s: any) => s.type === 'boxplot')?.itemStyle?.borderColor)
    expect(boxSeries, '箱体边框应固定直方图蓝 #1E88E5').toBe('#1E88E5')
  })

  test('多文件对比 X 轴：智能 4 位格式', async ({ page }) => {
    await enterAnalysis(page, RECOMMENDED.analysis)
    await page.getByRole('tab', { name: /多文件分析/ }).click()
    await expect(page.locator('.multi-file-tab')).toBeVisible({ timeout: 20_000 })

    // 选两个同产品文件触发合并请求
    const distResp = page.waitForResponse(
      (r) => r.url().includes('/analysis/multi_lot/') && r.request().method() === 'POST' && r.status() < 500,
      { timeout: 30_000 },
    )
    const select = page.locator('.multi-file-tab .left-panel .el-select').first()
    const input = select.locator('input').first()
    await select.click()
    const dropdown = page.locator('.el-select-dropdown:visible').last()
    await expect(dropdown).toBeVisible({ timeout: 10_000 })
    for (const name of RECOMMENDED.buyoff.slice(0, 2)) {
      await input.fill(name)
      const option = dropdown.locator('.el-select-dropdown__item').filter({ hasText: name }).first()
      await expect(option).toBeVisible({ timeout: 10_000 })
      await option.click()
      await input.fill('')
    }
    await page.keyboard.press('Escape')
    await distResp

    const container = '.multi-file-tab .chart-wrapper .chart-container'
    await waitChartRendered(page, container)
    await assertSmartFormatter(page, container, 'xAxis')
  })
})
