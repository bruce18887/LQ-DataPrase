import { test, expect, type Page } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, selectParam } from '../helpers/params'
import { waitLoadingGone } from '../helpers/charts'
import { SEEDED_FILES, RECOMMENDED } from '../fixtures/test-data'

/**
 * [edge-clip 回归] 多系列 bar 在同一 value xAxis 分组错位时，最左系列第 0 点柱体
 * （x=xAxis.min）与最右系列最后点柱体（x=xAxis.max）被挤出绘图区整根裁剪
 * （el.ignore=true，柱体与 label 消失，tooltip 仍正常）。
 *
 * 复现场景：STS8200 8 站点文件（9 个 bar 系列：Site1~8 + All Site），Vth_Post
 * overflow bin（超 USL 5 颗 fail，x = bin_centers[-1] = xAxis.max）——修复前
 * All Site 柱体与百分比标签不渲染（用户报告），Site1 的 underflow bin 同样被丢。
 *
 * 断言方式（渲染级）：不能数 SVG path —— ecmeta_* 属性仅在 ECharts SSR 模式写入，
 * 浏览器 DOM 渲染不存在。改数渲染对象：BarView clip 后柱元素 el.ignore=true
 * （echarts getData().getItemGraphicEl(i)），断言所有 bar 系列 0 个被 ignore。
 */

const SINGLE = '.single-param-tab'
const MULTI = '.multi-file-tab'

/** 统计各 bar 系列中被 clip 忽略的元素数（纯数据返回，chart 对象不可跨 evaluate 序列化） */
async function countIgnoredBars(
  page: Page,
  scope: string,
  names: string[],
): Promise<Record<string, { total: number; ignored: number }> | null> {
  return page.evaluate(
    ({ sel, wanted }) => {
      const dom = document.querySelector(`${sel} .chart-container`) as any
      const chart = dom?.__echartsInstance__
      if (!chart) return null
      const option = chart.getOption()
      if (!option?.series) return null
      const nameToIndex: Record<string, number> = {}
      option.series.forEach((s: any, i: number) => {
        nameToIndex[s.name] = i
      })
      const model = chart.getModel()
      const out: Record<string, { total: number; ignored: number }> = {}
      for (const name of wanted) {
        const idx = nameToIndex[name]
        if (idx == null) continue
        const data = model.getSeriesByIndex(idx).getData()
        let ignored = 0
        for (let i = 0; i < data.count(); i++) {
          const el = data.getItemGraphicEl(i)
          if (el && el.ignore) ignored++
        }
        out[name] = { total: data.count(), ignored }
      }
      return out
    },
    { sel: scope, wanted: names },
  )
}

/** 轮询直到 chart 可读且所有目标系列 0 个被 ignore（bar 入场动画期间 ignore 状态会波动） */
async function expectNoIgnoredBars(page: Page, scope: string, names: string[], timeout = 15_000) {
  await expect
    .poll(
      async () => {
        const stats = await countIgnoredBars(page, scope, names)
        if (!stats) return null
        if (Object.keys(stats).length !== names.length) return null // 系列未全部渲染
        return Object.values(stats).every((s) => s.ignored === 0)
      },
      { timeout, message: `series ${names.join(',')} 应全部渲染（无被 clip 忽略的柱体）` },
    )
    .toBe(true)
}

test.describe('@p1 多系列直方图边缘柱体不被裁剪', { tag: ['@p1', '@analysis'] }, () => {
  test('8 站点直方图：All Site overflow bin 与 Site1 underflow bin 柱体均渲染（回归 edge-clip）', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, SEEDED_FILES.STS8200_CP)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))

    // 文件自动加载首个参数；显式切到 Vth_Post（8 颗 fail：5 超 USL → overflow bin）
    const paramSelectWrapper = page.locator('.param-selector .el-select')
    const currentParam = await paramSelectWrapper.locator('.el-select__placeholder').textContent()
    if (!currentParam?.includes('Vth_Post')) {
      await selectParam(page, 'Vth_Post')
      await waitLoadingGone(page.locator(SINGLE))
    }
    await expect(page.locator(`${SINGLE} .chart-container`)).toBeVisible({ timeout: 10_000 })

    // 9 个 bar 系列：Site1~Site8 + All Site，每个 26 个数据点（1 underflow + 24 normal + 1 overflow）
    // 修复前：All Site 的 overflow 柱（x=xAxis.max）与 Site1 的 underflow 柱（x=xAxis.min）
    // 被分组布局挤出绘图区整根裁剪 → ignored ≥ 1；修复后 0
    await expectNoIgnoredBars(page, SINGLE, ['All Site', 'Site1'])

    const stats = await countIgnoredBars(page, SINGLE, ['All Site', 'Site1'])
    expect(stats?.['All Site']?.total, 'All Site 系列应有完整 bin 数据').toBeGreaterThan(0)
    expect(stats?.['Site1']?.total, 'Site1 系列应有完整 bin 数据').toBeGreaterThan(0)
  })

  test('多文件对比：2 文件柱状图各系列柱体全部渲染（pad 修复不引入回归）', async ({ page }) => {
    await gotoApp(page, '/analysis')
    // 顶部先选一个「与多文件清单不重叠」的文件，tabs 才出现（同 multi-file.spec.ts）
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await page.getByRole('tab', { name: /多文件分析/ }).click()
    await expect(page.locator(MULTI)).toBeVisible({ timeout: 20_000 })

    // 在左栏「数据文件」多选里勾选两个 buyoff 文件
    const select = page.locator(`${MULTI} .left-panel .el-select`).first()
    const input = select.locator('input').first()
    await select.click()
    const dropdown = page.locator('.el-select-dropdown:visible').last()
    await expect(dropdown).toBeVisible({ timeout: 10_000 })
    for (const name of [RECOMMENDED.buyoff[0], RECOMMENDED.buyoff[1]]) {
      await input.fill(name)
      const option = dropdown.locator('.el-select-dropdown__item').filter({ hasText: name }).first()
      await expect(option).toBeVisible({ timeout: 10_000 })
      await option.click()
      await input.fill('')
    }
    await page.keyboard.press('Escape')
    await page.waitForResponse(
      (r) => r.url().includes('/analysis/multi_lot/') && r.request().method() === 'POST' && r.status() < 500,
      { timeout: 25_000 },
    )
    await expect(page.locator(`${MULTI} .chart-wrapper svg`)).toBeVisible({ timeout: 15_000 })

    // 所有 bar 系列（每文件一个）0 个被 ignore；名称以文件名/图例名动态取，
    // 从 getOption 读取全部 bar 系列名再断言
    const names = await page.evaluate((sel) => {
      const dom = document.querySelector(`${sel} .chart-container`) as any
      const option = dom?.__echartsInstance__?.getOption?.()
      if (!option?.series) return []
      return option.series.filter((s: any) => s.type === 'bar').map((s: any) => s.name)
    }, MULTI)
    expect(names.length, '多文件柱状图应存在 bar 系列').toBeGreaterThanOrEqual(2)
    await expectNoIgnoredBars(page, MULTI, names)
  })

  test('8 站点直方图：贴限 bin 柱体不越过 USL 线（回归 limit-line-cross）', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, SEEDED_FILES.STS8200_CP)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))

    // Vth：超 USL 0 颗，bin 20（[1.08,1.10)，右边界=USL）含 1 颗贴限值 1.0898。
    // 修复前：9 系列并排柱组宽 0.04 单位 > bin 宽，AllSite 柱体右缘越过 USL ~4.7px
    const paramSelectWrapper = page.locator('.param-selector .el-select')
    const currentParam = await paramSelectWrapper.locator('.el-select__placeholder').textContent()
    if (!currentParam?.includes('Vth')) {
      await selectParam(page, 'Vth')
      await waitLoadingGone(page.locator(SINGLE))
    }
    await expect(page.locator(`${SINGLE} .chart-container`)).toBeVisible({ timeout: 10_000 })

    await expect
      .poll(async () => {
        const result = await page.evaluate(() => {
          const dom = document.querySelector('.single-param-tab .chart-container') as any
          const chart = dom?.__echartsInstance__
          if (!chart) return null
          const option = chart.getOption()
          if (!option?.series) return null
          const barSeries = option.series.filter((s: any) => s.type === 'bar')
          if (barSeries.length < 2) return null
          // 贴限 bin = bin_centers 中最后一个 count>0 的 bin
          const allSite = barSeries.find((s: any) => s.name === 'All Site')
          const binCounts = (allSite?.data || []).map((d: any) => Number(d?.[3] ?? 0))
          const lastIdx = binCounts.map((c: number, i: number) => (c > 0 ? i : -1)).filter((i: number) => i >= 0).pop()
          if (lastIdx == null) return null
          const usl = option.series.flatMap((s: any) => s.markLine?.data || []).find((m: any) => m.label?.formatter === 'USL')?.xAxis
          if (usl == null) return null
          const uslPx = chart.convertToPixel({ xAxisIndex: 0 }, usl)
          if (uslPx == null) return null
          let maxRight = -Infinity
          for (const s of barSeries) {
            const idx = option.series.indexOf(s)
            const data = chart.getModel().getSeriesByIndex(idx).getData()
            const layout = data.getItemLayout(lastIdx)
            if (layout && layout.x + layout.width > maxRight) maxRight = layout.x + layout.width
          }
          return { uslPx, maxRight, lastIdx }
        })
        if (!result) return null
        // 柱体右缘 ≤ USL 线位置（+0.5px 浮点容差）
        return result.maxRight <= result.uslPx + 0.5
      }, { timeout: 15_000, message: '贴限 bin 的柱体右缘不应越过 USL 线' })
      .toBe(true)
  })

  test('柱宽/柱体重合 slider 联动（8 站点 → 默认重合 5% 时柱宽上限 10%）', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, SEEDED_FILES.STS8200_CP)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))

    // 展开「更多」显示柱宽/柱体重合 slider（aria 挂在 button-wrapper，EP role="slider"）
    await page.locator('.more-btn').click()
    const sliders = page.locator('.single-param-tab .el-slider__button-wrapper')
    await expect(sliders.first()).toBeVisible({ timeout: 10_000 })
    await expect(sliders, '应有两个 slider：柱宽 + 柱体重合').toHaveCount(2)
    const widthSlider = sliders.nth(0)
    const overlapSlider = sliders.nth(1)

    // 默认重合 5%：柱宽上限 = floor(87/(9-8×0.05)) = 10，默认 20% 被 clamp 到 10
    await expect
      .poll(async () => await widthSlider.getAttribute('aria-valuemax'), { timeout: 15_000 })
      .toBe('10')
    await expect(widthSlider).toHaveAttribute('aria-valuenow', '10')
    await expect(overlapSlider).toHaveAttribute('aria-valuenow', '5')

    // 拖重合到 0%（完全并排）→ 柱宽上限收窄到 9（floor(87/9)）
    await overlapSlider.click()
    await page.keyboard.press('Home')
    await expect
      .poll(async () => await overlapSlider.getAttribute('aria-valuenow'), { timeout: 10_000 })
      .toBe('0')
    await expect
      .poll(async () => await widthSlider.getAttribute('aria-valuemax'), { timeout: 15_000 })
      .toBe('9')
    // 默认 20% 被 clamp 显示为 9
    await expect(widthSlider).toHaveAttribute('aria-valuenow', '9')

    // 拖重合到 100% → 柱宽上限放开到 87（单根柱视觉）
    await page.keyboard.press('End')
    await expect
      .poll(async () => await overlapSlider.getAttribute('aria-valuenow'), { timeout: 10_000 })
      .toBe('100')
    await expect
      .poll(async () => await widthSlider.getAttribute('aria-valuemax'), { timeout: 15_000 })
      .toBe('87')
  })

  test('Site 统计表：Yield=百分比3位(总数)、Fail/<Min/>Max=数量(百分比3位)（回归 2026-08-13 格式）', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, SEEDED_FILES.STS8200_CP)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))

    // 切到 Vth（site_stats 需要 param）——Site 统计表随参数加载
    const paramSelectWrapper = page.locator('.param-selector .el-select')
    const currentParam = await paramSelectWrapper.locator('.el-select__placeholder').textContent()
    if (!currentParam?.includes('Vth')) {
      await selectParam(page, 'Vth')
      await waitLoadingGone(page.locator(SINGLE))
    }

    // SiteStatsTable 卡片（页面有多个 el-table，用卡片标题定位）
    const table = page.locator('.el-card', { hasText: 'Site统计' }).locator('.el-table')
    await expect(table).toBeVisible({ timeout: 15_000 })
    // 格式断言（正则，不依赖具体数值——site_stats 口径与直方图 filter 不同）：
    // Yield = 99.819%(1659) ｜ Fail/<Min/>Max = 3(0.181%)
    await expect
      .poll(
        async () => {
          const texts = await table.locator('.el-table__body tbody tr').allInnerTexts()
          return texts.find((t) => t.includes('Site7')) ?? null
        },
        { timeout: 15_000, message: 'Site 统计表应出现 Site7 行' },
      )
      .not.toBeNull()
    const rows = await table.locator('.el-table__body tbody tr').allInnerTexts()
    const site7Row = rows.find((t) => t.includes('Site7'))
    expect(site7Row, '应有 Site7 行').toBeDefined()
    expect(site7Row!).toMatch(/\d+\.\d{3}%\(\d+\)/)            // Yield 格式
    expect(site7Row!).toMatch(/\d+\(\d+\.\d{3}%\)/)            // Fail 格式
    expect(site7Row!).toMatch(/\d+\(\d+\.\d{3}%\)/)            // <Min 格式
    const allRow = rows.find((t) => t.includes('ALL Site'))
    expect(allRow, '应有 ALL Site 行').toBeDefined()
    expect(allRow!).toMatch(/\d+\.\d{3}%\(\d+\)/)
  })
})
