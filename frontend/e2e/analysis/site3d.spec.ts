import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, selectParam, ensureChartToggles, listParams } from '../helpers/params'
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
  // 只收敛本图自己要的键：账号级勾选被并行用例共享，翻别人的键会和 dock-resize 等互相踩
  await ensureChartToggles(page, { hist: true, site3d: true })
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
    try {
      await enter3D(page)
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
    try {
      await enter3D(page)
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

  /**
   * 视角记忆（specs/2026-11-05 §4）：拖拽 → 切参数 → 刷新，机位都要保留。
   * 落库链路是 400ms 静置 + 800ms 防抖，所以等**带着本次拖拽后 alpha 的 PUT**：
   * V3 起每份 settings PUT 都携带已知 site3dView，只判「postData 含 site3dView」
   * 会被切勾选/旧值 PUT 误命中。
   */
  test('视角在切参数与刷新后保持', async ({ page }) => {
    try {
      await enter3D(page)
      const readView = () =>
        page.evaluate((sel) => {
          const dom = document.querySelector(sel) as any
          const inst = dom?.__echartsInstance__
          const view = inst?.getViewOfComponentModel?.(inst.getModel().getComponent('grid3D'))
          const c = view?._control
          return c
            ? { alpha: c.getAlpha(), beta: c.getBeta(), distance: c.getDistance(), ortho: c.getOrthographicSize() }
            : null
        }, HOST)

      const host = page.locator(HOST)
      await host.scrollIntoViewIfNeeded()
      const bb = (await host.boundingBox())!
      const cx = bb.x + bb.width / 2
      const cy = bb.y + bb.height / 2
      const before = (await readView())!
      const viewPut = page.waitForResponse(
        (r) => {
          if (!r.url().includes('/auth/settings/') || r.request().method() !== 'PUT') return false
          try {
            const v = JSON.parse(r.request().postData() || '{}')?.analysis_chart_state?.site3dView
            return typeof v?.alpha === 'number' && Math.abs(v.alpha - before.alpha) > 1
          } catch {
            return false
          }
        },
        { timeout: 20_000 },
      )

      await page.mouse.move(cx, cy)
      await page.mouse.down()
      await page.mouse.move(cx + 140, cy - 60, { steps: 12 })
      await page.mouse.up()
      await page.waitForTimeout(800) // damping 余量
      const rotated = (await readView())!
      expect(Math.abs(rotated.alpha - before.alpha), '拖拽应改变机位').toBeGreaterThan(1)

      await viewPut // 视角已落库

      // 滚轮缩放：gl 的阻尼在后续帧才落到相机，事件当刻读不到变化 ⇒ 必须等落库后的 ortho
      const beforeZoom = (await readView())!
      const zoomPut = page.waitForResponse(
        (r) => {
          if (!r.url().includes('/auth/settings/') || r.request().method() !== 'PUT') return false
          try {
            const v = JSON.parse(r.request().postData() || '{}')?.analysis_chart_state?.site3dView
            // PUT 存的是模型值（生效值 − 1）
            return typeof v?.orthographicSize === 'number' &&
              Math.abs(v.orthographicSize - (beforeZoom.ortho - 1)) > 0.5
          } catch {
            return false
          }
        },
        { timeout: 20_000 },
      )
      await page.mouse.move(cx, cy)
      await page.mouse.wheel(0, -300)
      await expect
        .poll(async () => (await readView())!.ortho, { timeout: 5_000, message: '滚轮应改变正交视口尺寸' })
        .not.toBeCloseTo(beforeZoom.ortho, 1)
      await zoomPut
      const zoomed = (await readView())!

      // 切到另一个参数：重渲染必须带着同一机位（含 ortho，钉住 base 1 的换算）
      const params = await listParams(page)
      const next = params.find((p) => p !== 'Vth' && p !== 'Vth_Post') ?? params[1]
      await selectParam(page, next)
      await waitLoadingGone(page.locator(SINGLE))
      await page.waitForTimeout(1200)
      const afterSwitch = (await readView())!
      expect(afterSwitch.alpha).toBeCloseTo(zoomed.alpha, 0)
      expect(afterSwitch.beta).toBeCloseTo(zoomed.beta, 0)
      expect(afterSwitch.ortho).toBeCloseTo(zoomed.ortho, 0)

      // 刷新：账号记忆里应还是这个机位
      await page.reload()
      await enter3D(page)
      await page.waitForTimeout(1200)
      const afterReload = (await readView())!
      expect(afterReload.alpha).toBeCloseTo(zoomed.alpha, 0)
      expect(afterReload.beta).toBeCloseTo(zoomed.beta, 0)
      expect(afterReload.ortho).toBeCloseTo(zoomed.ortho, 0)

      // 收尾：复位并等落库，别把旋转/缩放后的视角留给后续用例/手工检查。
      // 按默认机位（site3dOption.ts 的 SITE3D_VIEW，T2 已钉住）比值，不能只判键存在。
      const resetPut = page.waitForResponse(
        (r) => {
          if (!r.url().includes('/auth/settings/') || r.request().method() !== 'PUT') return false
          try {
            const v = JSON.parse(r.request().postData() || '{}')?.analysis_chart_state?.site3dView
            return v?.alpha === 28 && v?.beta === 30
          } catch {
            return false
          }
        },
        { timeout: 20_000 },
      )
      await page.getByLabel('回到默认视角').click()
      await resetPut
      const afterReset = (await readView())!
      expect(afterReset.alpha).toBeCloseTo(28, 0)
      expect(afterReset.beta).toBeCloseTo(30, 0)
    } finally {
      await ensureChartToggles(page, { site3d: false })
    }
  })
})
