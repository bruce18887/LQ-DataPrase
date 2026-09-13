import { test, expect, type Page, type Locator } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, selectParamWithSpecLimits, filterControl } from '../helpers/params'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 序列分布多 Site 重叠可读性（spec: docs/superpowers/specs/2026-09-12-serial-overlap-design.md）
 *  - §1 自适应点径/透明度分级 + 最密垫底 z 序（fail/超界点随 Site 系列着色，
 *    2026-09-13 回退 §1.3 独立强调层）
 *  - §3 slider 覆盖与重载重置
 *  - §2 按 Site 拆分小多图
 *  - §4 双主题视觉快照
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
 * site 系列绘制点数总和（fail/超界点随 Site 系列着色、计入 site 系列；
 * ≈ 分级依据 pointCount 差 anchor=1 不绘制点数）
 *
 * 注意口径微差：本函数返回的是「绘制点数」，而组件分级依据是 pointCount
 * （原始 series_data 长度和，含 anchor=1 的不绘制点，spec §1.1 定义）。两者仅
 * 在存在 anchor=1 点时相差该数量；当前两个 fixture（10k / 500 点）均远离
 * 5000 / 20000 档位边界，故两种口径落在同一档。换 fixture 时需留意边界。
 */
function drawnSiteTotals(opt: any): number {
  return (opt?.series ?? []).reduce(
    (a: number, s: any) => (/^Site /.test(s.name) ? a + (s.data?.length ?? 0) : a),
    0,
  )
}

/** body 中是否存在「会被绘制」的 fail 点（is_fail=1 或 anchor∈{2,3}；anchor=1 无值不绘制）——fixture 前提钉：fail 点应随 Site 系列可见 */
function hasDrawnFailPoints(body: any): boolean {
  return (body?.series_data || []).some((sd: any) =>
    (sd.data || []).some((p: any[]) => {
      const anchor = p[3] ?? 0
      return anchor !== 1 && ((p[2] ?? 0) === 1 || anchor !== 0)
    }),
  )
}

/** 按系列名计数（拆分模式同名系列按 lane 复制） */
function seriesCountByName(opt: any, name: string): number {
  return (opt?.series ?? []).filter((s: any) => s.name === name).length
}

/**
 * 复刻组件的每 lane 数据自适应范围规则（SerialChart.rangeOfPoints，2026-09-13）：
 * anchor==0 值的 min/max ±8% pad（单值退化用 |v|·5%），有锚到轴边的超界点再多留
 * 15% 头部。测试侧重写一份算法 = 回归钉（旧行为共享完整规格限范围时会不等）。
 */
function expectedLaneRange(points: any[]): { min: number; max: number } | null {
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

/** 序列图齿轮设置按钮（点径/透明度/按 Site 拆分都在弹层里，2026-09-13 齿轮化） */
const serialGear = (page: Page) => page.locator(`${SINGLE} [data-testid="serial-settings-btn"]`)

/** 打开序列图齿轮弹层并返回 popper（teleport 到 body，按实例类定位） */
async function openSerialSettings(page: Page): Promise<Locator> {
  await serialGear(page).click()
  const pop = page.locator('.dp-serial-settings-popper')
  await expect(pop).toBeVisible({ timeout: 10_000 })
  return pop
}

/** 点开齿轮 → 切换「按 Site 拆分」→ 再点齿轮收起弹层（避免弹层遮挡快照/后续交互） */
async function toggleSplitBySite(page: Page) {
  const pop = await openSerialSettings(page)
  await pop.getByText('按 Site 拆分').click()
  await serialGear(page).click()
  await expect(pop).toBeHidden()
}

test.describe('@p1 序列分布多 Site 重叠可读性', { tag: ['@p1', '@analysis'] }, () => {
  test('自动档：分级表一致 + 最密垫底 + fail 随 Site 着色 + 图例 Site 升序', async ({ page }) => {
    const { canvas, resp } = await enterSerial(page, RECOMMENDED.analysis)
    const body = await resp.json()
    const opt = await readOption(canvas)
    const series: any[] = opt.series ?? []
    const siteSeries = series.filter((s) => /^Site /.test(s.name))
    expect(siteSeries.length, '应至少 2 个 site 系列').toBeGreaterThanOrEqual(2)

    const total = drawnSiteTotals(opt)
    expect(total, 'fixture 应走高密度路径 (>=5000 点)').toBeGreaterThanOrEqual(5000)
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

    // 回退钉（2026-09-13）：Fail/超界 独立置顶强调层已撤销，fail/超界点随 Site
    // 系列着色。前提用「存在被绘制的 fail 点」而非 fail_count>0：fail 全为
    // anchor=1（无值不绘制）时 fail_count>0 但图上无 fail 点可见
    expect(hasDrawnFailPoints(body), 'CTA8280F fixture 应含被绘制的 fail/超界点').toBe(true)
    expect(series.find((s) => s.name === 'Fail/超界'), 'Fail/超界 独立层已撤销').toBeUndefined()
    expect(
      siteSeries.some((s) => s.data.some((pt: any) => pt.isFail)),
      'fail 点随 Site 系列着色',
    ).toBe(true)
    expect(legend, '图例不含 Fail/超界').not.toContain('Fail/超界')
  })

  test('自动档①：500 点文件保持 6px/0.85', async ({ page }) => {
    const { canvas } = await enterSerial(page, 'Site12358-Chip12345_c')
    const opt = await readOption(canvas)
    const siteSeries = (opt.series ?? []).filter((s: any) => /^Site /.test(s.name))
    expect(siteSeries.length).toBeGreaterThanOrEqual(2)
    const total = drawnSiteTotals(opt)
    expect(total).toBeLessThan(5000)
    expect(expectedTier(total)).toEqual({ size: 6, opacity: 0.85 })
    for (const s of siteSeries) {
      expect(s.symbolSize).toBe(6)
      expect(s.itemStyle.opacity).toBe(0.85)
    }
  })

  test('slider 覆盖与重载重置：拖改生效、数据重载回自动', async ({ page }) => {
    const { canvas } = await enterSerial(page, RECOMMENDED.analysis)
    const siteSymbol = () =>
      readOption(canvas).then((o: any) => o?.series?.find((s: any) => /^Site /.test(s.name))?.symbolSize)
    const siteOpacity = () =>
      readOption(canvas).then((o: any) => o?.series?.find((s: any) => /^Site /.test(s.name))?.itemStyle?.opacity)
    await expect.poll(siteSymbol).toBeGreaterThanOrEqual(3)

    // 点径 自动值 → 键盘 +3 步；断言覆盖生效（max 8 封顶）
    const before = await siteSymbol()
    const pop = await openSerialSettings(page)
    const sizeBtn = pop.locator('.el-slider__button-wrapper').nth(0)
    await sizeBtn.focus()
    for (let i = 0; i < 3; i++) await page.keyboard.press('ArrowRight')
    await expect.poll(siteSymbol).toBe(Math.min(before + 3, 8))

    // 透明度 -1 步（step 5 → 百分比 -5 → 小数 -0.05），精确断言
    // 用整数百分比空间算术避免浮点雷（0.85-0.05=0.7999999999999999≠0.8）——与组件 effOpacityPct 同源
    const opBtn = pop.locator('.el-slider__button-wrapper').nth(1)
    const opBefore = await siteOpacity()
    await opBtn.focus()
    await page.keyboard.press('ArrowLeft')
    await expect.poll(siteOpacity).toBe(
      Math.max(Math.round(opBefore * 100) - 5, 10) / 100,
    )

    // 切过滤触发数据重载 → override 清零回自动（spec §3）
    const respPromise = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/serial_distribution/') &&
        r.request().method() === 'POST' &&
        r.status() < 500,
      { timeout: 30_000 },
    )
    // Bin1 过滤开关在「数据筛选」区（非 .chart-toggles），按 data-filter 契约属性定位
    await filterControl(page, 'data-only-bin1').click()
    await expect(filterControl(page, 'data-only-bin1')).toHaveClass(/is-checked/)
    await respPromise
    const opt = await readOption(canvas)
    const tier = expectedTier(drawnSiteTotals(opt))
    await expect.poll(siteSymbol).toBe(tier.size)
    await expect.poll(siteOpacity).toBe(tier.opacity)
  })

  test('按 Site 拆分：每 lane 贴合自身数据范围 + 联动缩放 + 图例去 Site', async ({ page }) => {
    const { canvas, resp } = await enterSerial(page, RECOMMENDED.analysis)
    const body = await resp.json()
    const n = (body.series_data || []).length
    test.skip(n < 2, 'fixture 无多 site，拆分模式不适用')
    await toggleSplitBySite(page)
    await expect.poll(async () => (await readOption(canvas))?.grid?.length).toBe(n)
    const opt = await readOption(canvas)
    expect(opt.xAxis.length).toBe(n)
    expect(opt.yAxis.length).toBe(n)
    // 每 lane 各自贴合其数据范围（2026-09-13：不再共享完整规格限范围，减少 lane 内空白）
    opt.yAxis.forEach((y: any, i: number) => {
      const exp = expectedLaneRange(body.series_data[i].data || [])
      if (!exp) return
      expect(y.min, `lane ${i} y 下限贴该 lane 数据`).toBeCloseTo(exp.min, 6)
      expect(y.max, `lane ${i} y 上限贴该 lane 数据`).toBeCloseTo(exp.max, 6)
    })
    // 仅末 lane 显示 X 标签
    opt.xAxis.forEach((x: any, i: number) => {
      expect(x.axisLabel.show, `lane ${i} X 标签`).toBe(i === n - 1)
    })
    // 缩放联动覆盖全 lane
    expect(opt.dataZoom[0].xAxisIndex).toEqual(Array.from({ length: n }, (_, i) => i))
    // 图例去 Site、保留参考线
    const legend: string[] = opt.legend[0].data
    expect(legend.some((l) => /^Site /.test(l))).toBe(false)
    const markNames = (body.marks || []).map((m: any) => m.name)
    expect(markNames.length, 'fixture 应带参考线（默认 chart_config 含 limit）').toBeGreaterThan(0)
    expect(legend, '拆分模式图例 = 参考线条目').toEqual(markNames)
    // per-lane 复制契约（spec §2）：每个参考线名的系列数 = laneCount；
    // markLine z 与宿主 series z 同取动态上限
    for (const m of body.marks || []) {
      expect(seriesCountByName(opt, m.name), `参考线 ${m.name} 按 lane 复制`).toBe(n)
    }
    const markZExpected = Math.max(20, n + 4)
    for (const s of opt.series ?? []) {
      if (s.markLine?.data?.length) {
        expect(s.markLine.z, 'markLine z 动态上限').toBe(markZExpected)
        expect(s.z, 'marks 宿主 series z 同值').toBe(markZExpected)
      }
    }
    // 取消勾选恢复单面板
    await toggleSplitBySite(page)
    await expect.poll(async () => (await readOption(canvas))?.grid?.length).toBe(1)
  })

  test('视觉快照：合并/拆分 × 双主题存 .qoder/verify_serial_*.png', async ({ page }) => {
    const { canvas } = await enterSerial(page, RECOMMENDED.analysis)
    const themeNow = () => page.evaluate(() => document.documentElement.getAttribute('data-theme'))
    const shot = (name: string) => canvas.screenshot({ path: `../.qoder/verify_serial_${name}.png` })
    const t0 = await themeNow()
    await shot(`merged_${t0}`)
    await toggleSplitBySite(page)
    await expect.poll(async () => (await readOption(canvas))?.grid?.length).toBeGreaterThanOrEqual(2)
    await shot(`split_${t0}`)
    const titleColor = () =>
      readOption(canvas).then((o: any) => o?.title?.[0]?.textStyle?.color)
    const c0 = await titleColor()
    await page.locator('button.theme-toggle').click()
    const t1 = t0 === 'light' ? 'night' : 'light'
    await expect(page.locator('html')).toHaveAttribute('data-theme', t1)
    // 主题切换后等图表 option 重绘（标题文字色随主题）再截图，避免抓到旧主题
    await expect.poll(titleColor).not.toBe(c0)
    await shot(`split_${t1}`)
    await toggleSplitBySite(page)
    await expect.poll(async () => (await readOption(canvas))?.grid?.length).toBe(1)
    await shot(`merged_${t1}`)
  })
})
