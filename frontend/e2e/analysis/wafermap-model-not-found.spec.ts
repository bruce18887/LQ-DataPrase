import { test, expect, type Locator } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile } from '../helpers/params'
import { expectChartRendered } from '../helpers/charts'

/**
 * 回归：STS8200 大文件（BN281R3CYCAA_*.csv，14178 行、237 个重复坐标）
 * 在晶圆图上渲染/交互时，ECharts 报
 * "[ECharts] model or view can not be found by params"。
 *
 * 该警告来自 echarts 内部鼠标事件路径（lib/core/echarts.js _initEvents）：
 * 鼠标命中的元素其 ecData 指向的 series 已不在当前图表模型中（陈旧元素）。
 * 本用例：加载该文件 → 悬停/图例/缩放/模式切换/高度拖拽，断言全程无该警告。
 */

const FILE_SUBSTR = 'BN281R3CYCAA'

/** 收集 ECharts 相关控制台警告/错误 */
function collectEChartsConsole(page: import('@playwright/test').Page): string[] {
  const messages: string[] = []
  page.on('console', (msg) => {
    const text = msg.text()
    if (/\[ECharts\]|model or view can not be found/.test(text)) {
      messages.push(`console.${msg.type()}: ${text}`)
    }
  })
  page.on('pageerror', (err) => messages.push(`pageerror: ${err.message}`))
  return messages
}

/** 在图表区域内做网格状鼠标扫过（模拟真实悬停命中大量散点） */
async function sweepMouse(loc: Locator) {
  const box = await loc.boundingBox()
  if (!box) return
  for (let gy = 0; gy < 5; gy++) {
    for (let gx = 0; gx < 8; gx++) {
      const x = box.x + box.width * (0.08 + 0.12 * gx)
      const y = box.y + box.height * (0.15 + 0.17 * gy)
      await loc.page().mouse.move(x, y, { steps: 3 })
    }
  }
}

test('机制复现：lazyUpdate 期间悬停被移除 series 的陈旧散点 → ECharts model-or-view 警告', {
  tag: ['@p1', '@analysis'],
}, async ({ page }) => {
  // 页面级 console 监听：按顺序收集 ECharts 警告（基线阶段 0 条，陈旧悬停阶段 ≥1 条）
  const warns: string[] = []
  page.on('console', (msg) => {
    if (msg.type() === 'warning' && /model or view can not be found/.test(msg.text())) {
      const loc = msg.location()
      warns.push(`${msg.text()} @${loc.url?.split('/').pop()}:${loc.lineNumber}:${loc.columnNumber}`)
    }
  })

  await gotoApp(page, '/analysis')
  await selectAnalysisFile(page, FILE_SUBSTR)
  await expect(page.getByRole('tab', { name: /晶圆图/ })).toBeVisible({ timeout: 30_000 })
  // lazy 挂载：先打开 tab，面板控件才存在
  await page.getByRole('tab', { name: /晶圆图/ }).click()
  const loadBtn = page.locator('button').filter({ hasText: '加载晶圆图' })
  await expect(loadBtn).toBeEnabled({ timeout: 120_000 })
  const panel = page.getByRole('tabpanel', { name: /晶圆图/ })
  const chart = panel.locator('div[_echarts_instance_]').first()
  await expect(chart).toHaveCount(1, { timeout: 20_000 })

  const respPromise = page.waitForResponse(
    (r) => r.url().includes('/analysis/wafer_map/') && r.request().method() === 'POST',
    { timeout: 180_000 },
  )
  await loadBtn.click()
  expect((await respPromise).status()).toBe(200)
  await expect(panel.getByText('Total Dies')).toBeVisible({ timeout: 30_000 })
  await expectChartRendered(chart, 0, 60_000)

  // 在真实实例上做确定性复现（分两步，避免基线/陈旧阶段的警告混在一起）：
  // 1) 基线：对 Fail die 位置 dispatch mousemove → 全 series 存在，不应警告；
  // 2) 陈旧窗口：setOption(只剩 Pass, notMerge + lazyUpdate) 后、flush 前再次 dispatch
  //    → 陈旧 Fail die 仍可被命中，其 seriesIndex 已超出新模型 → ECharts 警告。
  // 多处 Fail die 位置逐一尝试（237 个重复坐标可能使部分位置被 Pass die 覆盖）。
  const stalePx: number[][] = await chart.evaluate((el: any) => {
    const chart = el.__echartsInstance__
    const zr = chart.getZr()
    const opt = chart.getOption()
    const failIdx = opt.series.findIndex((s: any) => s.name === 'Fail')
    const failData = (opt.series[failIdx]?.data ?? []).slice(0, 30)
    const pxList = failData.map((d: any) =>
      chart.convertToPixel({ seriesIndex: failIdx }, d.value),
    )
    // 基线：全部命中现有 series → 无警告
    for (const px of pxList) zr.handler.dispatch('mousemove', { zrX: px[0], zrY: px[1] })
    return pxList
  })
  expect(stalePx.length, '该文件应存在 Fail die').toBeGreaterThan(0)

  await page.waitForTimeout(100)
  const baselineWarns = warns.length
  expect(baselineWarns, `基线悬停不应产生警告，实际: ${warns.join(' | ')}`).toBe(0)

  // 陈旧窗口：同步 setOption（旧元素即刻移除）→ 对原 Fail die 位置 dispatch
  await chart.evaluate((el: any, pxList: number[][]) => {
    const chart = el.__echartsInstance__
    const zr = chart.getZr()
    const opt = chart.getOption()
    chart.setOption(
      { ...opt, series: opt.series.filter((s: any) => s.name === 'Pass'), legend: undefined },
      { notMerge: true },
    )
    for (const px of pxList) zr.handler.dispatch('mousemove', { zrX: px[0], zrY: px[1] })
  }, stalePx)

  // 陈旧窗口的警告在 dispatch 时同步打出；等 flush 完成后应不再新增。
  // 修复前（lazyUpdate 延迟刷新）：陈旧 Fail die 命中 → 必有 ≥1 条警告（已确认复现）；
  // 修复后（同步 setOption）：旧元素即刻移除 → 任何阶段都不应再有警告。
  await page.waitForTimeout(200)
  const staleWarns = warns.length - baselineWarns
  expect(warns.length, 'flush 完成后不应再新增警告').toBe(baselineWarns + staleWarns)
  expect(
    staleWarns,
    `陈旧悬停不应产生 ECharts model-or-view 警告（修复=lazyUpdate 移除，同步 setOption）`,
  ).toBe(0)
})

test('大文件晶圆图：悬停/图例/缩放/模式切换全程无 ECharts model-or-view 警告', {
  tag: ['@p1', '@analysis'],
}, async ({ page }) => {
  const problems = collectEChartsConsole(page)

  await gotoApp(page, '/analysis')
  await selectAnalysisFile(page, FILE_SUBSTR)
  await expect(page.getByRole('tab', { name: /晶圆图/ })).toBeVisible({ timeout: 30_000 })

  // lazy 挂载：先打开 tab；按钮可用 = 参数列表加载完成
  await page.getByRole('tab', { name: /晶圆图/ }).click()
  const loadBtn = page.locator('button').filter({ hasText: '加载晶圆图' })
  await expect(loadBtn).toBeEnabled({ timeout: 120_000 })

  const panel = page.getByRole('tabpanel', { name: /晶圆图/ })
  const chart = panel.locator('div[_echarts_instance_]').first()
  await expect(chart).toHaveCount(1, { timeout: 20_000 })

  // 等 wafer_map 响应真正返回（14k 行首次解析较慢，空图 svg 会提前出现，不能只看容器）
  const respPromise = page.waitForResponse(
    (r) => r.url().includes('/analysis/wafer_map/') && r.request().method() === 'POST',
    { timeout: 180_000 },
  )
  await loadBtn.click()
  const resp = await respPromise
  expect(resp.status()).toBe(200)

  // 统计卡片出现（Total Dies）→ 数据真正渲染
  await expect(panel.getByText('Total Dies')).toBeVisible({ timeout: 30_000 })
  await expectChartRendered(chart, 0, 60_000)

  // 1) 悬停扫过散点区域
  await sweepMouse(chart)

  // 2) 图例交互：逐个隐藏/显示 series（触发 legend 重渲染）。
  // canvas 渲染器下图例是像素不是 DOM 节点，改用等价的 legendToggleSelect；
  // svg 渲染器仍按真实 DOM 点击。
  const isCanvas = await chart.evaluate((el: any) => !!el.querySelector('canvas'))
  const legendNames: string[] = await chart.evaluate((el: any) =>
    ((el.__echartsInstance__.getOption().legend?.[0]?.data ?? []) as any[])
      .map((d: any) => (typeof d === 'string' ? d : d.name))
      .filter((n: string) => /Pass|Fail|Wafer Edge|Notch/.test(n)))
  expect(legendNames.length, '图例项应存在').toBeGreaterThanOrEqual(2)
  for (const name of legendNames.slice(0, 3)) {
    if (isCanvas) {
      await chart.evaluate(
        (el: any, n: string) => el.__echartsInstance__.dispatchAction({ type: 'legendToggleSelect', name: n }),
        name,
      )
    } else {
      // force：x 轴 dataZoom 滑块背景 path 覆盖在底部图例上方，正常点击被滑块拦截
      await chart.locator('svg text').filter({ hasText: name }).first().click({ force: true })
    }
    await sweepMouse(chart)
  }

  // 3) dataZoom 滑块拖拽（x 滑块在底部）；canvas 下无 svg，用图表容器定位
  // 注意：boundingBox() 对空 locator 会等满超时，必须先判存在
  const dragBox = (await chart.locator('svg').count())
    ? await chart.locator('svg').first().boundingBox()
    : await chart.boundingBox()
  if (dragBox) {
    await page.mouse.move(dragBox.x + dragBox.width / 2, dragBox.y + dragBox.height - 15)
    await page.mouse.down()
    await page.mouse.move(dragBox.x + dragBox.width * 0.3, dragBox.y + dragBox.height - 15, { steps: 5 })
    await page.mouse.up()
    await sweepMouse(chart)
  }

  // 4) 模式切换 result → site → zone → result（每次切换都是 notMerge 全量重渲染）
  for (const mode of [/按\s*Site/, '分区模式', '按结果']) {
    await page.locator('.el-radio-button').filter({ hasText: mode }).click()
    await expectChartRendered(chart, 0, 60_000)
    await sweepMouse(chart)
  }

  // 5) 图表高度拖拽（每步触发 ResizeObserver → renderOption 全量重渲染）
  // 必须限定在晶圆图 tabpanel 内：页面上其它 tab 的滑块是隐藏的；
  // dragTo 会被滑块自身容器拦截，改用手动 mouse 拖动
  const heightSlider = panel.locator('.el-slider__button').first()
  const hb = await heightSlider.boundingBox()
  if (hb) {
    await page.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2)
    await page.mouse.down()
    await page.mouse.move(hb.x + hb.width / 2 + 60, hb.y + hb.height / 2, { steps: 10 })
    await page.mouse.up()
  }
  await sweepMouse(chart)

  const bad = problems.filter((m) => /model or view can not be found/.test(m))
  expect(bad, `ECharts 出现 model-or-view 警告（共 ${problems.length} 条 ECharts 消息）:\n${problems.join('\n')}`).toEqual([])
})
