import { test, expect, type Page, type Locator } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, selectParamWithSpecLimits, filterControl } from '../helpers/params'
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
 * site 系列 + Fail/超界 系列的点数总和（≈ 拆 Fail 层前的 pointCount（差 anchor=1 不绘制点数））
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

/** 按系列名计数（拆分模式同名系列按 lane 复制） */
function seriesCountByName(opt: any, name: string): number {
  return (opt?.series ?? []).filter((s: any) => s.name === name).length
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
    // 上一行硬钉后 hasDrawnFailPoints 恒真，下列断言无条件执行（原 if/else 外壳 else 不可达已删）
    expect(hasDrawnFailPoints(body), 'CTA8280F fixture 应含被绘制的 fail/超界点（spec §1.3）').toBe(true)
    const fail = series.find((s) => s.name === 'Fail/超界')
    expect(fail, 'Fail/超界 强调层应存在').toBeTruthy()
    expect(fail.itemStyle.opacity).toBe(1)
    expect(fail.z).toBeGreaterThan(Math.max(...zs))
    expect(legend).toContain('Fail/超界')
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

  test('slider 覆盖与重载重置：拖改生效、数据重载回自动', async ({ page }) => {
    const { canvas } = await enterSerial(page, RECOMMENDED.analysis)
    const siteSymbol = () =>
      readOption(canvas).then((o: any) => o?.series?.find((s: any) => /^Site /.test(s.name))?.symbolSize)
    const siteOpacity = () =>
      readOption(canvas).then((o: any) => o?.series?.find((s: any) => /^Site /.test(s.name))?.itemStyle?.opacity)
    await expect.poll(siteSymbol).toBeGreaterThanOrEqual(3)

    // 点径 自动值 → 键盘 +3 步；断言覆盖生效（max 8 封顶）
    const before = await siteSymbol()
    const sizeBtn = page.locator(`${SINGLE} .serial-header__slider`).nth(0).locator('.el-slider__button-wrapper')
    await sizeBtn.focus()
    for (let i = 0; i < 3; i++) await page.keyboard.press('ArrowRight')
    await expect.poll(siteSymbol).toBe(Math.min(before + 3, 8))

    // 透明度 -1 步（step 5 → 百分比 -5 → 小数 -0.05），精确断言
    // 用整数百分比空间算术避免浮点雷（0.85-0.05=0.7999999999999999≠0.8）——与组件 effOpacityPct 同源
    const opBtn = page.locator(`${SINGLE} .serial-header__slider`).nth(1).locator('.el-slider__button-wrapper')
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
    const tier = expectedTier(siteAndFailTotals(opt))
    await expect.poll(siteSymbol).toBe(tier.size)
    await expect.poll(siteOpacity).toBe(tier.opacity)
  })

  test('按 Site 拆分：N lane 共享刻度 + 联动缩放 + 图例去 Site', async ({ page }) => {
    const { canvas, resp } = await enterSerial(page, RECOMMENDED.analysis)
    const body = await resp.json()
    const n = (body.series_data || []).length
    test.skip(n < 2, 'fixture 无多 site，拆分模式不适用')
    await page.getByText('按 Site 拆分').click()
    await expect.poll(async () => (await readOption(canvas))?.grid?.length).toBe(n)
    const opt = await readOption(canvas)
    expect(opt.xAxis.length).toBe(n)
    expect(opt.yAxis.length).toBe(n)
    // 共享刻度（跨 Site 可比）
    expect(new Set(opt.yAxis.map((y: any) => y.min)).size).toBe(1)
    expect(new Set(opt.yAxis.map((y: any) => y.max)).size).toBe(1)
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
    // per-lane 复制契约（spec §2）：Fail 层数 = 有可绘制 fail 点的 lane 数；
    // 每个参考线名的系列数 = laneCount；markLine z 与宿主 series z 同取动态上限
    const drawnFailLanes = (body.series_data || []).filter((sd: any) =>
      (sd.data || []).some((p: any[]) => {
        const anchor = p[3] ?? 0
        return anchor !== 1 && ((p[2] ?? 0) === 1 || anchor !== 0)
      }),
    ).length
    expect(
      seriesCountByName(opt, 'Fail/超界'),
      'Fail 层按 lane 复制数 = 有可绘制 fail 点的 lane 数',
    ).toBe(drawnFailLanes)
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
    await page.getByText('按 Site 拆分').click()
    await expect.poll(async () => (await readOption(canvas))?.grid?.length).toBe(1)
  })

  test('双主题：Fail 层色随主题 errorColor', async ({ page }) => {
    const { canvas, resp } = await enterSerial(page, RECOMMENDED.analysis)
    const body = await resp.json()
    test.skip(!hasDrawnFailPoints(body), 'fixture 无可绘制 fail 点，无 Fail 层')
    const failColor = () =>
      readOption(canvas).then(
        (o: any) => o?.series?.find((s: any) => s.name === 'Fail/超界')?.itemStyle?.color,
      )
    const themeNow = () => page.evaluate(() => document.documentElement.getAttribute('data-theme'))
    const expectFor = (t: string | null) => (t === 'light' ? '#b91c1c' : '#f5576c')
    const t0 = await themeNow()
    await expect.poll(failColor).toBe(expectFor(t0))
    await page.locator('button.theme-toggle').click()
    const t1 = t0 === 'light' ? 'night' : 'light'
    await expect(page.locator('html')).toHaveAttribute('data-theme', t1)
    await expect.poll(failColor).toBe(expectFor(t1))
  })

  test('视觉快照：合并/拆分 × 双主题存 .qoder/verify_serial_*.png', async ({ page }) => {
    const { canvas } = await enterSerial(page, RECOMMENDED.analysis)
    const themeNow = () => page.evaluate(() => document.documentElement.getAttribute('data-theme'))
    const shot = (name: string) => canvas.screenshot({ path: `../.qoder/verify_serial_${name}.png` })
    const t0 = await themeNow()
    await shot(`merged_${t0}`)
    await page.getByText('按 Site 拆分').click()
    await expect.poll(async () => (await readOption(canvas))?.grid?.length).toBeGreaterThanOrEqual(2)
    await shot(`split_${t0}`)
    await page.locator('button.theme-toggle').click()
    const t1 = t0 === 'light' ? 'night' : 'light'
    await expect(page.locator('html')).toHaveAttribute('data-theme', t1)
    // 主题切换后等图表 option 重绘（Fail 层色随 errorColor）再截图，避免抓到旧主题
    await expect.poll(async () =>
      (await readOption(canvas))?.series?.find((s: any) => s.name === 'Fail/超界')?.itemStyle?.color,
    ).toBe(t1 === 'light' ? '#b91c1c' : '#f5576c')
    await shot(`split_${t1}`)
    await page.getByText('按 Site 拆分').click()
    await expect.poll(async () => (await readOption(canvas))?.grid?.length).toBe(1)
    await shot(`merged_${t1}`)
  })
})
