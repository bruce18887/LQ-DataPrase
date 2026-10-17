import { test, expect, type Page, type Locator } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, selectParamWithSpecLimits, openSerialDistribution } from '../helpers/params'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 序列分布 Y 轴范围（2026-10-17 口径）：RDL/CL 档必须**同时**框住 LSL 与 USL，且两限
 * 外侧各留限宽 10% 的余量；其余档位（DR/S3/S4/S6）仍按 anchor==0 数据自适应，
 * 超出视野的参考线贴边钳制并加 ↑/↓。
 *
 * 分层：公式全组合在 T2（test/unit/serialAxisRange.spec.ts，12 例 / 5ms）。本 spec
 * 只留浏览器不可替代的两条接线证明——① 真实响应下两限确实入框、外侧留得出余量且
 * markLine 保持真实值；② 限值远在数据之外时是「轴在扩张」，而 σ 级参考线仍贴边钳制。
 * 旧版在此逐字复刻组件公式（expectedRange），新口径下那等于把已废的判据钉住，故删。
 */

async function readOption(loc: Locator): Promise<any> {
  return loc.evaluate((el: any) => el.__echartsInstance__?.getOption?.() ?? null)
}

async function enterSerial(page: Page, fileLabel: string) {
  await gotoApp(page, '/analysis')
  await selectAnalysisFile(page, fileLabel)
  await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
  const limited = await selectParamWithSpecLimits(page)
  test.skip(!limited, '当前文件没有带真实规格限的参数')
  return openSerialDistribution(page)
}

/** 本响应里「会被绘制」的点值（anchor==0；anchor=1 无值不画、2/3 贴边画） */
function drawableValues(body: any): number[] {
  return (body.series_data || [])
    .flatMap((sd: any) => sd.data || [])
    .filter((p: any[]) => (p[3] ?? 0) === 0 && typeof p[1] === 'number' && Number.isFinite(p[1]))
    .map((p: any[]) => p[1])
}

/** 按标签取规格限的两条 markLine（按下标取会让后端调序变成瞎红） */
function specLimitItems(opt: any) {
  const spec = (opt.series || []).find((s: any) => s.name === '规格限')
  const items: any[] = spec?.markLine?.data || []
  return {
    lsl: items.find((it) => it.label?.formatter === 'LSL'),
    usl: items.find((it) => it.label?.formatter === 'USL'),
  }
}

/** 把规格限推到数据范围之外（真实场景见用户截图的反面），不依赖 fixture 取值 */
function overrideSpecLimits(json: any, lo: number, hi: number) {
  json.lower_limit = lo
  json.upper_limit = hi
  for (const m of json.marks || []) {
    if (m.name !== '规格限') continue
    for (const it of m.markLine?.data || []) {
      if (it.label?.formatter === 'LSL') it.yAxis = lo
      else if (it.label?.formatter === 'USL') it.yAxis = hi
    }
  }
}

const SERIAL_ROUTE = /\/analysis\/serial_distribution\//

test.describe('@p1 序列分布 Y 轴范围', { tag: ['@p1', '@analysis'] }, () => {
  test('RDL：LSL/USL 同时入框，两限外侧有余量、参考线不被钉到轴边', async ({ page }) => {
    const { canvas, resp } = await enterSerial(page, RECOMMENDED.analysis)
    const body = await resp.json()
    const lo = body.lower_limit
    const hi = body.upper_limit
    test.skip(!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo, '该参数无有效规格限窗')

    const opt = await readOption(canvas)
    const y = opt.yAxis[0]
    const margin = (hi - lo) * 0.09 // 断 9% 而非 10%：系数改动不该让本用例误红
    expect(y.min, 'LSL 外侧留得出余量（旧口径下 LSL 压在 X 轴上）').toBeLessThan(lo - margin)
    expect(y.max, 'USL 外侧留得出余量').toBeGreaterThan(hi + margin)

    const { lsl, usl } = specLimitItems(opt)
    expect(lsl, '应含 LSL 参考线').toBeTruthy()
    expect(usl, '应含 USL 参考线').toBeTruthy()
    expect(lsl.yAxis, 'LSL 画在真实值上，未被钳制').toBeCloseTo(lo, 6)
    expect(usl.yAxis, 'USL 画在真实值上，未被钳制').toBeCloseTo(hi, 6)
    expect(lsl.label.formatter, 'LSL 标签不带 ↓').not.toContain('↓')
    expect(usl.label.formatter, 'USL 标签不带 ↑').not.toContain('↑')
  })

  /**
   * 一次注入造出两种距离：限值推到数据外 5 倍带宽、σ 级参考线推到 50 倍。
   * 于是「轴为限值扩张」与「σ 仍贴边钳制」在同一份响应里对照断言——这正好是新
   * 口径的分界线本身，比拆成两条各拦一次更省一次 route.fetch（实测拦两次会撞上
   * 单进程 dev server 的 ECONNRESET，2026-10-17 首跑即 flaky）。
   */
  test('限值远在数据外→轴扩张盖住两限；σ 级参考线更远→仍贴边钳制 + ↑/↓', async ({ page }) => {
    await page.route(SERIAL_ROUTE, async (route) => {
      const response = await route.fetch()
      const json: any = await response.json()
      const vals = drawableValues(json)
      if (vals.length) {
        const mn = Math.min(...vals)
        const mx = Math.max(...vals)
        const span = Math.max(mx - mn, 1e-9)
        overrideSpecLimits(json, mn - span * 5, mx + span * 5)
        json.marks = json.marks || []
        json.marks.push({
          name: 'σ范围夹具',
          type: 'scatter',
          data: [],
          markLine: {
            symbol: 'none',
            precision: 4,
            data: [
              { yAxis: mx + span * 50, lineStyle: { color: '#fac858', width: 3, type: 'dotted' }, label: { show: true, formatter: '6σ上限', position: 'insideEndTop' } },
              { yAxis: mn - span * 50, lineStyle: { color: '#fac858', width: 3, type: 'dotted' }, label: { show: true, formatter: '6σ下限', position: 'insideEndTop' } },
            ],
          },
        })
      }
      await route.fulfill({ response, json })
    })

    const { canvas, resp } = await enterSerial(page, RECOMMENDED.analysis)
    await page.unroute(SERIAL_ROUTE)
    const body = await resp.json()
    const lo = body.lower_limit
    const hi = body.upper_limit
    const opt = await readOption(canvas)
    const y = opt.yAxis[0]

    const vals = drawableValues(body)
    expect(y.min, '轴扩到 LSL 之外，且仍覆盖全部正常点').toBeLessThan(Math.min(lo, ...vals))
    expect(y.max, '轴扩到 USL 之外，且仍覆盖全部正常点').toBeGreaterThan(Math.max(hi, ...vals))
    const { lsl, usl } = specLimitItems(opt)
    expect(lsl.yAxis, 'LSL 画在真实值上，未被钉到轴边').toBeCloseTo(lo, 6)
    expect(usl.yAxis, 'USL 画在真实值上，未被钉到轴边').toBeCloseTo(hi, 6)
    expect(lsl.label.formatter, 'LSL 不带 ↓').not.toContain('↓')
    expect(usl.label.formatter, 'USL 不带 ↑').not.toContain('↑')

    const sigma = (opt.series || []).find((s: any) => s.name === 'σ范围夹具')
    const items: any[] = sigma?.markLine?.data || []
    const up = items.find((it) => it.label?.formatter?.startsWith('6σ上限'))
    const down = items.find((it) => it.label?.formatter?.startsWith('6σ下限'))
    expect(up, '应含 6σ上限 参考线').toBeTruthy()
    expect(down, '应含 6σ下限 参考线').toBeTruthy()
    expect(up.yAxis, '6σ上限钉到上界').toBeCloseTo(y.max, 6)
    expect(up.label.formatter, '6σ上限标签带 ↑').toContain('↑')
    expect(down.yAxis, '6σ下限钉到下界').toBeCloseTo(y.min, 6)
    expect(down.label.formatter, '6σ下限标签带 ↓').toContain('↓')
  })
})
