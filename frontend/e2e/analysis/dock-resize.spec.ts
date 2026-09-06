import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { expectChartRendered, waitLoadingGone } from '../helpers/charts'
import { selectAnalysisFile } from '../helpers/params'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * dock 面板缩放回归（2026-09-06 二次修复）：
 *  - 历史教训：只断言 .chart-panel 的 boundingBox（CSS 层）不够——曾出现面板高度
 *    正确跟随、但内部 ECharts 画布尺寸卡死在初始值（grid 轨道 1fr 的 auto 最小
 *    尺寸被内容撑住 + 条件渲染容器没有 ResizeObserver）→ 用户看到图表被裁切/
 *    底部条下留大片空白。断言落到真实渲染层：宿主容器内的 svg/canvas rect 必须
 *    贴合宿主自身盒（inst.getWidth/getHeight 是内部缓存、可能滞后，不可靠；
 *    参照也不能用 .chart-b——序列图宿主因 col-selector/OutlierHintBar 等兄弟
 *    元素本来就不等于面板体）。
 *  - 底部横条改整体高度：4 张图画布双向（压矮/撑高）都跟随。
 *  - 行间自定义拖拽条改两行占比：两行图画布此消彼长且都跟随。
 * 行不再用 el-splitter（它把行尺寸一次性锁成 px、容器变高不重算），改自定义 % 行。
 */

const SINGLE = '.single-param-tab'
const KEYS = ['hist', 'serial', 'qq', 'box'] as const
type Key = (typeof KEYS)[number]

async function panelHeight(page: import('@playwright/test').Page, key: Key): Promise<number> {
  const panel = page.locator(`.chart-panel[data-chart-key="${key}"]`)
  return (await panel.boundingBox())?.height ?? 0
}

/** 图表面板 key → ECharts 宿主容器选择器（useChart 在宿主上暴露 __echartsInstance__） */
const HOST_SEL: Record<Key, string> = {
  hist: '.chart-container',
  serial: '.serial-canvas',
  qq: '.qqplot-container',
  box: '.chart-container',
}

/**
 * 宿主容器内真实渲染元素（svg/canvas）与宿主自身盒的尺寸（同一帧读取）。
 * 不用 inst.getWidth/getHeight：ECharts 内部缓存可能滞后于真实 DOM（实测出现过
 * inst 报旧值而 svg 已贴合），svg/canvas 的实际 rect 才是用户看到的画布尺寸。
 * 占位态（v-if 未翻转/未渲染）返回 null。
 */
async function renderSize(
  page: import('@playwright/test').Page,
  key: Key,
): Promise<{ host: { w: number; h: number }; chart: { w: number; h: number } } | null> {
  const host = page
    .locator(`.chart-panel[data-chart-key="${key}"] ${HOST_SEL[key]}`)
    .first()
  if ((await host.count()) === 0) return null
  return host.evaluate((el) => {
    const chart = el.querySelector('svg, canvas')
    if (!chart) return null
    const r = chart.getBoundingClientRect()
    return {
      host: { w: el.clientWidth, h: el.clientHeight },
      chart: { w: r.width, h: r.height },
    }
  })
}

/** 断言某图画布渲染尺寸贴合其宿主容器（容差 4px，覆盖 ECharts resize 的舍入） */
async function expectCanvasFits(page: import('@playwright/test').Page, key: Key) {
  await expect.poll(
    async () => {
      const s = await renderSize(page, key)
      if (!s) return false
      return Math.abs(s.chart.w - s.host.w) <= 4 && Math.abs(s.chart.h - s.host.h) <= 4
    },
    { timeout: 8_000, message: `${key} 画布应渲染为宿主容器尺寸（跟随分隔条缩放）` },
  ).toBe(true)
}

async function expectAllCanvasFit(page: import('@playwright/test').Page) {
  for (const k of KEYS) await expectCanvasFits(page, k)
}

function toggle(page: import('@playwright/test').Page, label: string) {
  return page.locator(`${SINGLE} .chart-toggles .el-checkbox`).filter({ hasText: label })
}

async function enterAll(page: import('@playwright/test').Page) {
  await gotoApp(page, '/analysis')
  await selectAnalysisFile(page, RECOMMENDED.analysis)
  await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
  await waitLoadingGone(page.locator(SINGLE))
  await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)
  for (const label of ['显示序列分布', '显示QQ图', '显示箱线图']) {
    await toggle(page, label).click()
  }
  for (const k of KEYS) {
    await expect(page.locator(`.chart-panel[data-chart-key="${k}"]`)).toBeVisible({ timeout: 20_000 })
  }
  await waitLoadingGone(page.locator(SINGLE))
}

async function dragBar(
  page: import('@playwright/test').Page,
  selector: string,
  index: number,
  dy: number,
) {
  const bar = page.locator(selector).nth(index)
  await bar.scrollIntoViewIfNeeded()
  const b = (await bar.boundingBox())!
  const cx = b.x + b.width / 2
  const cy = b.y + b.height / 2
  await page.mouse.move(cx, cy)
  await page.mouse.down()
  await page.mouse.move(cx, cy + dy, { steps: 8 })
  await page.mouse.up()
  await page.waitForTimeout(600)
}

/** 底部横条顶边与最下方面板底边的距离（布局填满时应 ≈ flex gap 6px） */
async function bottomGap(page: import('@playwright/test').Page): Promise<number> {
  return page.evaluate(() => {
    const rt = document.querySelector('.chart-dock__resize')!.getBoundingClientRect().top
    const pb = Math.max(...[...document.querySelectorAll('.chart-panel')].map((p) => p.getBoundingClientRect().bottom))
    return rt - pb
  })
}

test.describe('@p1 dock 面板缩放自适应', { tag: ['@p1', '@analysis'] }, () => {
  test('底部横条压矮/撑高 → 4 图画布双向跟随（不只面板高度）', async ({ page }) => {
    await enterAll(page)
    await expectAllCanvasFit(page)

    // 压矮：画布必须同步变小且仍贴合面板体（画布 > 面板体 = 本轮 bug 形态）
    const before = {} as Record<Key, number>
    for (const k of KEYS) before[k] = await panelHeight(page, k)
    await dragBar(page, '.chart-dock__resize', 0, -260)
    for (const k of KEYS) {
      await expect
        .poll(async () => await panelHeight(page, k), { timeout: 8_000, message: `${k} 面板应随 dock 压矮变矮` })
        .toBeLessThan(before[k])
    }
    await expectAllCanvasFit(page)

    // 撑高：画布同步变大且贴合
    await dragBar(page, '.chart-dock__resize', 0, 600)
    for (const k of KEYS) {
      await expect
        .poll(async () => await panelHeight(page, k), { timeout: 8_000, message: `${k} 面板应随 dock 撑高变高` })
        .toBeGreaterThan(before[k])
    }
    await expectAllCanvasFit(page)
  })

  test('行间拖拽条改两行占比 → 上下两行图画布都跟随', async ({ page }) => {
    await enterAll(page)
    await expectAllCanvasFit(page)

    const histBefore = await panelHeight(page, 'hist')
    const serialBefore = await panelHeight(page, 'serial')
    // 第一行的行间拖拽条（index 0）：向下拖 → 直方图行变矮、辅助行变高
    await dragBar(page, '.chart-dock__rowbar', 0, 120)
    await expect
      .poll(async () => await panelHeight(page, 'hist'), { timeout: 8_000 })
      .toBeLessThan(histBefore)
    await expect
      .poll(async () => await panelHeight(page, 'serial'), { timeout: 8_000 })
      .toBeGreaterThan(serialBefore)
    await expectAllCanvasFit(page)
  })

  test('拖图合并行（删行）→ 行占比自动归一，底部横条贴合最后一行', async ({ page }) => {
    await enterAll(page)
    // 默认 4 行 [[hist],[serial],[qq],[box]]。把 box 的 ⠿ 手柄拖到 QQ 图左半
    // （drop dir=left 合并为一行）→ moveTo 删掉 box 空行。
    const grip = page.locator('.chart-panel[data-chart-key="box"] .chart-h__grip')
    await grip.scrollIntoViewIfNeeded()
    await page.waitForTimeout(300)
    const gb = (await grip.boundingBox())!
    // QQ 面板在 box 行正上方一行：drop 点取其左 15%、垂直居中（rx<0.3 → dir=left）
    const qb = (await page.locator('.chart-panel[data-chart-key="qq"]').boundingBox())!
    const tx = qb.x + qb.width * 0.15
    const ty = qb.y + qb.height / 2
    await page.mouse.move(gb.x + gb.width / 2, gb.y + gb.height / 2)
    await page.mouse.down()
    await page.mouse.move(tx, ty, { steps: 12 })
    await page.mouse.up()
    await page.waitForTimeout(600)

    // 结构变化生效：面板仍 4 张、行数变 3（box 与 qq 同行）
    await expect(page.locator('.chart-panel')).toHaveCount(4)
    await expect(page.locator('.chart-dock__row')).toHaveCount(3)
    // 关键回归断言：删行后剩余行占比必须重新铺满 dock body，
    // 否则底部横条与最后一行之间留下 (100−sum)% 的永久空白（2026-09-06 用户截图症状）
    await expect
      .poll(async () => await bottomGap(page), { timeout: 8_000, message: '底部横条应贴合最后一行图表（行占比归一）' })
      .toBeLessThanOrEqual(14)
    await expectAllCanvasFit(page)
  })

  test('最大化可复原：勾选变化自动退出最大化，⤡ 还原按钮可复原', async ({ page }) => {
    await enterAll(page)
    const panels = page.locator('.chart-panel')

    // 最大化 hist → 只剩一张；按钮翻转为还原态（title=还原；字形 ⤡ 与 ⤢ 成对，
    // 不再用 ⤓——它与下载箭头近形，用户误读为导出）
    await page.locator('.chart-panel[data-chart-key="hist"] .chart-h__btn[title="最大化"]').click()
    await expect(panels).toHaveCount(1)
    await expect(page.locator('.chart-panel[data-chart-key="hist"] .chart-h__btn[title="还原"]')).toBeVisible()

    // 关键回归（2026-09-06 用户卡死场景）：最大化态下取消再勾选其它图，
    // 必须自动退出最大化、四张图全部回来（旧行为：maxKey 残留，新勾的图
    // 永远不显示，勾选框怎么点都没反应，用户只能刷新页面）
    await toggle(page, '显示序列分布').click()
    await expect(panels).toHaveCount(3)
    await toggle(page, '显示序列分布').click()
    await expect(panels).toHaveCount(4)

    // 显式出口：最大化 serial → 点其 ⤡ 还原按钮复原
    await page.locator('.chart-panel[data-chart-key="serial"] .chart-h__btn[title="最大化"]').click()
    await expect(panels).toHaveCount(1)
    await page.locator('.chart-panel[data-chart-key="serial"] .chart-h__btn[title="还原"]').click()
    await expect(panels).toHaveCount(4)
    await expectAllCanvasFit(page)
  })
})
