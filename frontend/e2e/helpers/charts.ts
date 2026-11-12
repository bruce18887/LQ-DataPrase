import { expect, type Locator, type Page } from '@playwright/test'

type Box = NonNullable<Awaited<ReturnType<Locator['boundingBox']>>>

/**
 * 断言 ECharts 图表已正确渲染。
 * 兼容 SVG（默认）和 Canvas 两种渲染器：
 * 优先检测 svg 元素，回退到 canvas。
 *
 * @param scope 限定查找范围的 Locator（默认整页）
 * @param index 同一范围内多个图表元素时的索引
 */
export async function expectChartRendered(
  scope: Locator | Page,
  index = 0,
  timeout = 15_000,
) {
  const root = 'locator' in scope ? scope : scope

  // 先轮询等待任一图表元素（svg/canvas）出现，再按实际渲染器断言。
  // 一次性 count() 在图表尚未渲染完成时返回 0，会把 SVG 渲染器误判成
  // canvas 分支并等满超时（时序竞态，flaky 根因）。
  await expect
    .poll(
      async () =>
        (await root.locator('svg').count()) +
        (await root.locator('canvas').count()),
      { timeout },
    )
    .toBeGreaterThanOrEqual(index + 1)

  // SVG 渲染：检测 svg 元素存在且有可见尺寸
  const svg = root.locator('svg').nth(index)
  const svgCount = await svg.count()

  if (svgCount > 0) {
    await expect(svg, 'ECharts SVG 应可见').toBeVisible({ timeout })
    // 一次性 boundingBox 会在「可见判定 → 读取」之间被重渲染 detach 成 null
    // （负载下窗口变宽，2026-11-12 wafermap:73 实测）⇒ 条件轮询重试，判据不变。
    let box: Box | null = null
    await expect
      .poll(async () => {
        box = await svg.boundingBox()
        return box
      }, { timeout })
      .not.toBeNull()
    expect(box!.width, 'SVG 宽度应 > 0').toBeGreaterThan(0)
    expect(box!.height, 'SVG 高度应 > 0').toBeGreaterThan(0)
    return
  }

  // Canvas 渲染回退
  const canvas = root.locator('canvas').nth(index)
  await expect(canvas, 'ECharts canvas 应存在且可见').toBeVisible({ timeout })
  let box: Box | null = null
  await expect
    .poll(async () => {
      box = await canvas.boundingBox()
      return box
    }, { timeout })
    .not.toBeNull()
  expect(box!.width, 'canvas 宽度应 > 0').toBeGreaterThan(0)
  expect(box!.height, 'canvas 高度应 > 0').toBeGreaterThan(0)
}

/** 等待页面上至少 n 个图表元素（svg 或 canvas）出现 */
export async function waitForCharts(page: Page, n = 1, timeout = 15_000) {
  await expect
    .poll(
      async () =>
        (await page.locator('svg').count()) + (await page.locator('canvas').count()),
      { timeout },
    )
    .toBeGreaterThanOrEqual(n)
}

/** 等待 Element Plus loading 遮罩消失 */
export async function waitLoadingGone(scope: Locator | Page, timeout = 30_000) {
  const mask = scope.locator('.el-loading-mask')
  await expect(mask).toHaveCount(0, { timeout }).catch(() => {
    /* 某些页面无 loading 遮罩，忽略 */
  })
}
