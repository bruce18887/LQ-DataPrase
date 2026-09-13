import { test, expect, type Page, type Locator } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, selectParamWithSpecLimits } from '../helpers/params'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 序列分布 Y 轴数据自适应 + 参考线贴边钳制（2026-09-13 空间利用率优化）。
 *
 * 背景：后端 y_min/y_max = 规格限 ±10%；规格限离数据很远时整个绘图区被撑成
 * 「数据窄带 + 大片空白」。前端改为按 anchor==0 点的实际值算紧凑范围，超视野的
 * 规格限/σ 线贴边钳制并加 ↑/↓。后端契约不变（本 spec 只读响应比对）。
 */

const SINGLE = '.single-param-tab'
const SERIAL_CANVAS = `${SINGLE} .serial-chart-wrapper div[_echarts_instance_]`

async function readOption(loc: Locator): Promise<any> {
  return loc.evaluate((el: any) => el.__echartsInstance__?.getOption?.() ?? null)
}

async function enterSerial(page: Page, fileLabel: string) {
  await gotoApp(page, '/analysis')
  await selectAnalysisFile(page, fileLabel)
  await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
  const limited = await selectParamWithSpecLimits(page)
  test.skip(!limited, '当前文件没有带真实规格限的参数')
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

/** 复刻组件 SerialChart.rangeOfPoints 的规则（回归钉） */
function expectedRange(points: any[]): { min: number; max: number } | null {
  const vals: number[] = []
  let above = false
  let below = false
  for (const p of points) {
    const a = p[3] ?? 0
    if (a === 2) above = true
    else if (a === 3) below = true
    if (a !== 0) continue
    if (typeof p[1] === 'number' && Number.isFinite(p[1])) vals.push(p[1])
  }
  if (!vals.length) return null
  const mn = Math.min(...vals)
  const mx = Math.max(...vals)
  let lo: number
  let hi: number
  if (mx > mn) { const pad = (mx - mn) * 0.08; lo = mn - pad; hi = mx + pad }
  else { const dlt = Math.max(Math.abs(mx) * 0.05, 1e-9); lo = mn - dlt; hi = mx + dlt }
  const span = hi - lo
  if (above) hi += span * 0.15
  if (below) lo -= span * 0.15
  return { min: lo, max: hi }
}

test.describe('@p1 序列分布 Y 轴数据自适应', { tag: ['@p1', '@analysis'] }, () => {
  test('合并模式：Y 轴按数据自适应，不再等于规格限范围', async ({ page }) => {
    const { canvas, resp } = await enterSerial(page, RECOMMENDED.analysis)
    const body = await resp.json()
    const opt = await readOption(canvas)
    const y = opt.yAxis[0]
    const allPts = (body.series_data || []).flatMap((sd: any) => sd.data || [])
    const exp = expectedRange(allPts)
    expect(exp, 'fixture 应有可绘制的数据点').not.toBeNull()
    expect(y.min, 'y 下限贴数据').toBeCloseTo(exp!.min, 6)
    expect(y.max, 'y 上限贴数据').toBeCloseTo(exp!.max, 6)
    // 旧行为（共享后端 spec 范围）会等于 y_min/y_max；此处应与之有别
    // （除非数据恰好填满规格限——那时范围自然相近，属可接受）
    const specRange = [body.y_min, body.y_max]
    const tightRange = [y.min, y.max]
    expect(tightRange).not.toEqual(specRange)
  })

  test('规格限线超出可见范围：贴边钳制并在标签后加 ↑/↓', async ({ page }) => {
    // 种子数据的规格限未必远离数据带（真实场景见用户截图），用 route 把规格限
    // markLine 推到数据范围之外，稳定构造「贴边钳制」分支，不依赖 fixture 取值。
    const serialRoute = /\/analysis\/serial_distribution\//
    await page.route(serialRoute, async (route) => {
      const resp = await route.fetch()
      const json: any = await resp.json()
      const pts = (json.series_data || [])
        .flatMap((sd: any) => sd.data || [])
        .filter((p: any[]) => (p[3] ?? 0) === 0 && typeof p[1] === 'number')
        .map((p: any[]) => p[1])
      if (pts.length) {
        const mn = Math.min(...pts)
        const mx = Math.max(...pts)
        const span = Math.max(mx - mn, 1e-9)
        for (const m of json.marks || []) {
          if (m.name !== '规格限') continue
          for (const it of m.markLine?.data || []) {
            if (it.label?.formatter === 'LSL') it.yAxis = mn - span * 5
            else if (it.label?.formatter === 'USL') it.yAxis = mx + span * 5
          }
        }
      }
      await route.fulfill({ response: resp, json })
    })

    const { canvas } = await enterSerial(page, RECOMMENDED.analysis)
    await page.unroute(serialRoute)
    const opt = await readOption(canvas)
    const y = opt.yAxis[0]
    const spec = (opt.series || []).find((s: any) => s.name === '规格限')
    expect(spec?.markLine?.data, '应含规格限参考线').toBeTruthy()
    const items: any[] = spec.markLine.data
    const lslItem = items.find((it) => it.label?.formatter?.startsWith('LSL'))
    const uslItem = items.find((it) => it.label?.formatter?.startsWith('USL'))
    expect(lslItem, '应含 LSL 参考线').toBeTruthy()
    expect(uslItem, '应含 USL 参考线').toBeTruthy()
    // 注入的 LSL/USL 远在数据范围之外 → 应被钉到轴边并加箭头
    expect(lslItem.yAxis, 'LSL 钉到下界').toBeCloseTo(y.min, 6)
    expect(lslItem.label.formatter, 'LSL 标签带 ↓').toContain('↓')
    expect(uslItem.yAxis, 'USL 钉到上界').toBeCloseTo(y.max, 6)
    expect(uslItem.label.formatter, 'USL 标签带 ↑').toContain('↑')
  })
})
