import { test, expect, type Page, type Locator } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, selectParamWithSpecLimits } from '../helpers/params'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 序列分布多 Site 重叠可读性（spec: docs/superpowers/specs/2026-09-12-serial-overlap-design.md）
 *  - §1 自适应点径/透明度分级 + 最密垫底 z 序 + Fail/超界 置顶强调层
 *  - §3 slider 覆盖与重载重置
 *  - §2 按 Site 拆分小多图
 *  - §4 双主题 errorColor + 视觉快照
 */

const SINGLE = '.single-param-tab'
const SERIAL_CANVAS = `${SINGLE} .serial-chart-wrapper div[_echarts_instance_]`

/** 读图表实例 option（useChart 把实例挂在容器 div 本身） */
async function readOption(loc: Locator): Promise<any> {
  return loc.evaluate((el: any) => el.__echartsInstance__?.getOption?.() ?? null)
}

/** 进分析页 → 选带规格限参数 → 开序列分布；返回 canvas 与 serial 响应 */
async function enterSerial(page: Page, fileLabel: string) {
  await gotoApp(page, '/analysis')
  await selectAnalysisFile(page, fileLabel)
  await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
  const limited = await selectParamWithSpecLimits(page)
  test.skip(!limited, '当前文件没有带真实规格限的参数')
  // R2④：waitForResponse 必须在触发动作之前注册
  const respPromise = page.waitForResponse(
    (r) =>
      r.url().includes('/analysis/serial_distribution/') &&
      r.request().method() === 'POST' &&
      r.status() < 500,
    { timeout: 30_000 },
  )
  await page.getByText('显示序列分布').click()
  const resp = await respPromise
  const canvas = page.locator(SERIAL_CANVAS).first()
  await expect(canvas).toBeVisible({ timeout: 20_000 })
  return { canvas, resp }
}

/** 分级表一致性（spec §1.1）：点径/透明度由总点数决定 */
function expectedTier(total: number) {
  if (total < 5000) return { size: 6, opacity: 0.85 }
  if (total <= 20000) return { size: 4, opacity: 0.5 }
  return { size: 3, opacity: 0.35 }
}

/**
 * site 系列 + Fail/超界 系列的点数总和（= 拆 Fail 层前的 pointCount）
 *
 * 注意口径微差：本函数返回的是「绘制点数」，而组件分级依据是 pointCount
 *（原始 series_data 长度和，含 anchor=1 的不绘制点，spec §1.1 定义）。两者仅
 * 在存在 anchor=1 点时相差该数量；当前两个 fixture（10k / 500 点）均远离
 * 5000 / 20000 档位边界，故两种口径落在同一档。换 fixture 时需留意边界。
 */
function siteAndFailTotals(opt: any): number {
  return (opt?.series ?? []).reduce(
    (a: number, s: any) =>
      /^Site /.test(s.name) || s.name === 'Fail/超界' ? a + (s.data?.length ?? 0) : a,
    0,
  )
}

/** body 中是否存在「会被绘制」的 fail 点（is_fail=1 或 anchor∈{2,3}；anchor=1 无值不绘制）——与组件 Fail 层创建条件同口径 */
function hasDrawnFailPoints(body: any): boolean {
  return (body?.series_data || []).some((sd: any) =>
    (sd.data || []).some((p: any[]) => {
      const anchor = p[3] ?? 0
      return anchor !== 1 && ((p[2] ?? 0) === 1 || anchor !== 0)
    }),
  )
}

test.describe('@p1 序列分布多 Site 重叠可读性', { tag: ['@p1', '@analysis'] }, () => {
  test('自动档：分级表一致 + 最密垫底 + Fail/超界置顶强调层 + 图例 Site 升序', async ({ page }) => {
    const { canvas, resp } = await enterSerial(page, RECOMMENDED.analysis)
    const body = await resp.json()
    const opt = await readOption(canvas)
    const series: any[] = opt.series ?? []
    const siteSeries = series.filter((s) => /^Site /.test(s.name))
    expect(siteSeries.length, '应至少 2 个 site 系列').toBeGreaterThanOrEqual(2)

    const total = siteAndFailTotals(opt)
    expect(total, 'fixture 应走高密度路径（>=5000 点）').toBeGreaterThanOrEqual(5000)
    const tier = expectedTier(total)
    for (const s of siteSeries) {
      expect(s.symbolSize, '自动点径').toBe(tier.size)
      expect(s.itemStyle.opacity, '自动透明度').toBe(tier.opacity)
    }

    // z 序：按点数降序严格单调（最密垫底，spec §1.2）
    const counts = siteSeries.map((s) => s.data.length)
    const zs = siteSeries.map((s) => s.z)
    for (let i = 1; i < siteSeries.length; i++) {
      if (counts[i] === counts[i - 1]) continue
      expect(counts[i] < counts[i - 1] ? zs[i] > zs[i - 1] : zs[i] < zs[i - 1]).toBe(true)
    }

    // 图例前段 = site 升序（数组序不变约定）
    const legend: string[] = opt.legend[0].data
    expect(legend.slice(0, siteSeries.length)).toEqual(siteSeries.map((s) => s.name))

    // Fail/超界 强调层（spec §1.3）；全 pass fixture 退化为「不应存在」
    // 前提用「存在被绘制的 fail 点」而非 fail_count>0：fail 全为 anchor=1（无值不绘制）时
    // fail_count>0 但组件不会创建 Fail 层，用 fail_count 会误红
    if (hasDrawnFailPoints(body)) {
      const fail = series.find((s) => s.name === 'Fail/超界')
      expect(fail, 'Fail/超界 强调层应存在').toBeTruthy()
      expect(fail.itemStyle.opacity).toBe(1)
      expect(fail.z).toBeGreaterThan(Math.max(...zs))
      expect(legend).toContain('Fail/超界')
    } else {
      expect(series.find((s) => s.name === 'Fail/超界')).toBeUndefined()
    }
  })

  test('自动档①：500 点文件保持 6px/0.85', async ({ page }) => {
    const { canvas } = await enterSerial(page, 'Site12358-Chip12345_c')
    const opt = await readOption(canvas)
    const siteSeries = (opt.series ?? []).filter((s: any) => /^Site /.test(s.name))
    expect(siteSeries.length).toBeGreaterThanOrEqual(2)
    const total = siteAndFailTotals(opt)
    expect(total).toBeLessThan(5000)
    expect(expectedTier(total)).toEqual({ size: 6, opacity: 0.85 })
    for (const s of siteSeries) {
      expect(s.symbolSize).toBe(6)
      expect(s.itemStyle.opacity).toBe(0.85)
    }
  })
})
