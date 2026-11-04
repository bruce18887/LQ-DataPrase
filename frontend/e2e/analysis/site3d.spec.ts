import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, selectParam, ensureChartToggles } from '../helpers/params'
import { waitLoadingGone } from '../helpers/charts'
import { SEEDED_FILES } from '../fixtures/test-data'

/**
 * 3D 站点柱阵（specs/2026-11-04）。只有两条，且都是 node 层量不到的：
 * ① 真 WebGL 出图（`echarts-gl` 注册失败/渲染器没被强制成 canvas 时，DOM 有容器但没画布；
 *    `expectChartRendered` 只判非零尺寸，本图要的是「真 WebGL 画布 + 实测盒 >100」，
 *    而且 R2⑤ 要求先 count 再 boundingBox，所以按 canvas 实测盒量）；
 * ② night 主题下 grid3D 的轴线/标签确实取 night token（双主题对比度只能看图）。
 * 其余判据（轴型、色键形状、barSize 两分量不相等、机位单一来源、两图同 bin 口径）全在
 * T2：test/unit/site3dOption.spec.ts —— 那里 0.6s，没必要占浏览器单价。
 */

const SINGLE = '.single-param-tab'
const HOST = '.chart-panel[data-chart-key="site3d"] [data-site3d-canvas]'

async function enter3D(page: import('@playwright/test').Page) {
  await gotoApp(page, '/analysis')
  await selectAnalysisFile(page, SEEDED_FILES.STS8200_CP)
  await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
  await waitLoadingGone(page.locator(SINGLE))
  // 自己收敛五个勾选：其余图开着会改变 dock 的行数/布局，且勾选账号级持久，用例自己声明要什么状态
  await ensureChartToggles(page, { hist: true, serial: false, qq: false, box: false, site3d: true })
  const paramSelect = page.locator('.param-selector .el-select')
  const current = await paramSelect.locator('.el-select__placeholder').textContent()
  if (!current?.includes('Vth')) {
    await selectParam(page, 'Vth')
    await waitLoadingGone(page.locator(SINGLE))
  }
  await expect(page.locator(HOST)).toBeVisible({ timeout: 25_000 })
}

/**
 * 读宿主上的 __echartsInstance__。getOption() 会把组件归一成**数组**（grid3D/xAxis3D 都是），
 * 先 pick 首项再取路径；直接按对象读会静默拿到 undefined。
 */
function grid3DStyleState(page: import('@playwright/test').Page) {
  return page.evaluate((sel) => {
    const dom = document.querySelector(sel) as any
    const opt = dom?.__echartsInstance__?.getOption?.()
    if (!opt) return null
    const pick = (v: any) => (Array.isArray(v) ? v[0] : v)
    const g = pick(opt.grid3D)
    const x = pick(opt.xAxis3D)
    if (!g) return null
    return {
      axisLineShow: g.axisLine?.show ?? null,
      axisColor: g.axisLine?.lineStyle?.color ?? null,
      // 平铺属性：ECharts 6 会对旧的嵌套 axisLabel.textStyle 做兼容拆平（textStyle 置 null）
      labelColor: g.axisLabel?.color ?? null,
      nameColor: x?.nameTextStyle?.color ?? null,
    }
  }, HOST)
}

test.describe('@p1 3D 站点柱阵', { tag: ['@p1', '@analysis'] }, () => {
  test.describe.configure({ timeout: 120_000 })

  test('勾选后 dock 出真 WebGL 画布且实测有尺寸', async ({ page }) => {
    await enter3D(page)
    try {
      const host = page.locator(HOST)
      // R2⑤：boundingBox 对空 locator 不是返回 null 而是等满超时后抛错，必须先 count()
      await expect.poll(async () => (await host.locator('canvas').count()), { timeout: 20_000 })
        .toBeGreaterThanOrEqual(1)
      const box = await host.boundingBox()
      expect(box, '3D 宿主应有有效布局尺寸').not.toBeNull()
      expect(box!.width).toBeGreaterThan(100)
      expect(box!.height).toBeGreaterThan(100)

      const stat = await page.evaluate((sel) => {
        const dom = document.querySelector(sel) as any
        const inst = dom?.__echartsInstance__
        const s = inst?.getOption?.()?.series?.find?.((x: any) => x.type === 'bar3D')
        return s ? { count: s.data.length, barSize: s.barSize, shading: s.shading } : null
      }, HOST)
      expect(stat, 'bar3D 系列应完成一次 setOption').not.toBeNull()
      expect(stat!.barSize, 'barSize 应是 [宽, 深] 两分量').toHaveLength(2)
      // 8 Site × 26 bin 去掉零占比后仍有大量柱；为 0 就是「容器在但没出图」
      expect(stat!.count).toBeGreaterThan(40)
      expect(stat!.shading).toBe('color')
      // 两个分量各管一个方向且不相等（写成一个 fill 会退回板状截面）
      expect(stat!.barSize[0]).not.toBeCloseTo(stat!.barSize[1], 6)
    } finally {
      await ensureChartToggles(page, { site3d: false })
    }
  })

  test('night 主题：grid3D 轴线与标签取 night token', async ({ page }) => {
    await enter3D(page)
    try {
      await page.locator('button.theme-toggle').click()
      await expect(page.locator('html')).toHaveAttribute('data-theme', 'night')
      // 主题切换 → useChart 的 theme watcher 重渲染，轮询到 night 那把值落地
      await expect
        .poll(() => grid3DStyleState(page), { timeout: 20_000, message: 'night 主题应重渲染 grid3D 样式' })
        .toEqual({
          axisLineShow: true,
          axisColor: 'rgba(255, 255, 255, 0.04)',
          labelColor: 'rgba(255, 255, 255, 0.76)',
          nameColor: 'rgba(255, 255, 255, 0.76)',
        })
    } finally {
      await ensureChartToggles(page, { site3d: false })
    }
  })
})
