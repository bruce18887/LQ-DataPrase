import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, selectParamWithSpecLimits, pickTabFile, filePicker, ensureChartToggles } from '../helpers/params'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 图例颜色与图形颜色严格对应（需求7，2026-08-20）。
 *
 * ECharts 图例 marker 取 series.itemStyle.color（不取 lineStyle.color）——
 * 此前 markLine 系列/正态分布/KDE 缺 itemStyle 时图例落主题色板，与实际
 * 线色（红/灰/蓝/青/橙、#F57F17/#7B1FA2）不对应。断言：
 *  - 直方图 markLine 系列 itemStyle.color === 线色
 *  - 直方图正态分布/KDE itemStyle.color === lineStyle.color
 *  - 多文件柱/线 itemStyle.color === 后端 lot.color（light 下映射恒等）
 *  - 序列分布 marks 系列 itemStyle.color === 线色
 *  - 相关性回归线 itemStyle.color === lineStyle.color
 */

const SINGLE = '.single-param-tab'

/** 读取图表实例的 option（useChart 把实例挂在容器 div 本身） */
async function readOption(loc: import('@playwright/test').Locator) {
  return loc.evaluate((el: any) => el.__echartsInstance__?.getOption?.() ?? null)
}

test.describe('@p1 图例颜色严格对应', { tag: ['@p1', '@analysis'] }, () => {
  test('直方图：markLine 系列 itemStyle.color 与线色一致，正态/KDE 与 lineStyle 一致', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    // 只读直方图那一个实例，所以要自己把其它三张图关掉：它们账号级持久，
    // 起点未必干净（2026-10-13 实测停在四 toggle 全开时，下面这条 strict 选择器
    // 直接命中 3 个实例，用例在选参数**之前**就红）。
    await ensureChartToggles(page, { serial: false, qq: false, box: false })
    const container = `${SINGLE} .chart-wrapper div[_echarts_instance_]`
    await expect(page.locator(container)).toBeVisible({ timeout: 20_000 })

    // 默认选中的第一列（CTA8280F 的 Index_No）限值字段是字面 'Min'/'Max'，
    // 语义为「无规格限」→ 后端修正后返回 null，HistogramChart.vue:173 不再画
    // 「规格限」 markLine 组。本用例要校的正是规格限 + 6σ 两组 markLine 的
    // 图例色，所以必须先选一个真有规格限的参数。旧行为下它靠 Index_No 的
    // **幻影限值线**（把数据自身极值当 LSL/USL）凑够 2 组 —— 钉住的是 bug。
    const limited = await selectParamWithSpecLimits(page)
    test.skip(!limited, '当前文件没有带真实规格限的参数')
    await expect(page.locator(container)).toBeVisible({ timeout: 20_000 })

    const opt = await readOption(page.locator(container).first())
    const series: any[] = opt?.series ?? []
    expect(series.length).toBeGreaterThan(0)
    let markLineChecked = 0
    for (const s of series) {
      if (s.markLine?.data?.length) {
        const lineColor = s.markLine.data[0].lineStyle?.color
        expect(lineColor, `${s.name} 线色应存在`).toBeTruthy()
        expect(s.itemStyle?.color, `${s.name} 图例 marker 色应等于线色`).toBe(lineColor)
        markLineChecked++
      }
      if (s.name === '正态分布' || s.name === 'KDE曲线') {
        expect(s.itemStyle?.color, `${s.name} itemStyle 应与 lineStyle 同源`).toBe(s.lineStyle?.color)
      }
    }
    // 默认配置 limit+s6+kde → 至少 2 个 markLine 系列（规格限/6σ线）被校验
    expect(markLineChecked).toBeGreaterThanOrEqual(2)
  })

  test('多文件分析：柱/limit/正态线颜色与后端 lot.color 一致（light 主题映射恒等）', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await page.getByRole('tab', { name: /多文件分析/ }).click()
    const select = filePicker(page, 'multi')
    await expect(select).toBeVisible({ timeout: 20_000 })
    // 合并请求必须在选文件**之前**注册（R2④）。只认 200：单文件时后端返回
    // 400 need_at_least_2_files，第一个 200 就是「两个文件都选上」那一次。
    const mergedResp = page.waitForResponse(
      (r) => r.url().includes('/analysis/multi_lot/') &&
        r.request().method() === 'POST' && r.status() === 200,
      { timeout: 25_000 },
    )
    await select.click()
    const dropdown = page.locator('.el-select-dropdown:visible').last()
    await expect(dropdown).toBeVisible({ timeout: 10_000 })
    await select.locator('input').first().pressSequentially('BPD60320')
    for (const name of RECOMMENDED.analysisMulti) {
      const opt = dropdown.locator('.el-select-dropdown__item').filter({ hasText: name.slice(0, 12) }).first()
      await expect(opt).toBeVisible({ timeout: 5_000 })
      await opt.click()
      await page.waitForTimeout(300)
    }
    await page.keyboard.press('Escape')
    const merged = await mergedResp

    const container = '.multi-file-tab .chart-wrapper div[_echarts_instance_]'
    await expect(page.locator(container)).toBeVisible({ timeout: 25_000 })
    const opt = await readOption(page.locator(container).first())
    const series: any[] = opt?.series ?? []
    // lot.color 直接读**图表消费的那一份响应**（后端浅色板；light 主题下映射恒等，
    // 柱色必须等于它）。不再自己按文件名搜 /files/ 再重发一次 multi_lot：
    // 那条路每页只有 20 行，库里累积的 BZJ*_FT.csv 上传残留会把 BPD60320_FT.csv
    // 挤到第 2 页 → 只搜到 1 个 id → 400 need_at_least_2_files（2026-10-13 实测）。
    // 顺带也消掉了「比对基准与图表数据来自两次不同请求」这条缝。
    const lotColors = ((await merged.json())?.lot_data ?? [])
      .map((lot: any) => ({ file_id: lot.file_id, color: lot.color }))
    expect(lotColors.length, 'multi_lot 响应应带 >=2 个 lot_data').toBeGreaterThanOrEqual(2)
    // 柱系列按 lot_data 顺序与后端颜色一一对应（每个文件独立颜色）
    const barSeries = series.filter((s: any) => s.type === 'bar')
    expect(barSeries.length, '柱系列数应等于文件数').toBe(lotColors.length)
    for (let i = 0; i < barSeries.length; i++) {
      expect(barSeries[i].itemStyle?.color, `柱系列 ${barSeries[i].name} 颜色应等于后端 lot.color`)
        .toBe(lotColors[i].color)
    }
  })

  test('序列分布：marks 系列 itemStyle.color 与线色一致', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    // 切到序列分布模式（收敛而不是翻动：toggle 账号级持久，进来时可能已经是开的）
    await ensureChartToggles(page, { serial: true })
    const container = `${SINGLE} div[_echarts_instance_]`
    await expect(page.locator(container).first()).toBeVisible({ timeout: 20_000 })

    const opt = await readOption(page.locator(container).first())
    const series: any[] = opt?.series ?? []
    let markChecked = 0
    for (const s of series) {
      if (s.markLine?.data?.length) {
        const lineColor = s.markLine.data[0].lineStyle?.color
        expect(lineColor, `${s.name} 线色应存在`).toBeTruthy()
        expect(s.itemStyle?.color, `${s.name} 图例 marker 色应等于线色`).toBe(lineColor)
        markChecked++
      }
    }
    expect(markChecked, '序列分布应至少有一个 marks 系列').toBeGreaterThanOrEqual(1)
  })

  test('相关性散点：回归线 itemStyle.color 与 lineStyle.color 一致', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await page.getByRole('tab', { name: /相关性对比/ }).click()
    // 相关性 tab 吃自己那份文件选择（不选到 CTA8280F 就没有 Kelvin_VIN）。
    // 参数列表来自不带 params 的 histogram 快路径 —— 注册先于 pickTabFile
    // （R2④），列表落位前 X 下拉是空的（并行负载下 800ms 固定等待不够）。
    const listResp = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/histogram/') &&
        r.request().method() === 'POST' &&
        !(r.request().postData() || '').includes('"params"'),
      { timeout: 20_000 },
    )
    await pickTabFile(page, 'correlation', RECOMMENDED.analysis)
    await listResp
    // 同屏改造（2026-09-07）后 X/Y 两个下拉合进同一张卡，按卡内序区分
    const pairCard = page.locator('.el-tab-pane:visible .el-card').filter({ hasText: 'X 轴测试项' }).first()
    const xSelect = pairCard.locator('.el-select').first()
    await xSelect.click()
    await page.locator('.el-select-dropdown:visible .el-select-dropdown__item').filter({ hasText: 'Index_No' }).first().click()
    // X 下拉的关闭动画与 Y 下拉的打开重叠时，选项会瞬时不稳定、甚至整个下拉自己关掉
    // （known-red 的真实症状：`locator.click` 先报 element is not stable，再报
    // element is not visible）。同款已记录在 axis-label-precision.spec.ts:219，
    // 那边用固定 600ms 隔开；这里等「没有可见下拉」这个确定信号，而不是猜一个时长。
    await expect(page.locator('.el-select-dropdown:visible')).toHaveCount(0, { timeout: 10_000 })
    const ySelect = pairCard.locator('.el-select').nth(1)
    await ySelect.click()
    await ySelect.locator('input').first().pressSequentially('Kelvin_VIN')
    const yOpt = page.locator('.el-select-dropdown:visible .el-select-dropdown__item').filter({ hasText: 'Kelvin_VIN' }).first()
    await expect(yOpt).toBeVisible({ timeout: 15_000 })
    await yOpt.click()

    // 大文件（n=10000）散点走 canvas large + 渲染器切换时实例会短暂
    // dispose 重建，直接等 div[_echarts_instance_] 可能撞上空窗。
    // 改为轮询卡片头出现指标（渲染完成的事实信号）后再从容器读实例。
    const layout = page.locator('.analysis-tab-layout:visible')
    await expect(
      layout.locator('[data-corr-scatter-card] .head-metric').filter({ hasText: 'r=' }),
    ).toBeVisible({ timeout: 25_000 })
    // ⚠️ 实例属性挂在 .scatter-chart-inner 本体（ref 即 echarts 容器，探针实测
    // inner 子树无 div[_echarts_instance_]）：同屏改造后容器不再是「wrapper > 图表 div」
    // 的包裹结构，旧的『.scatter-chart-inner div[_echarts_instance_]』后代选择器
    // 恒不命中（假红根源）
    const inst = page.locator('.el-tab-pane:visible .scatter-chart-inner[_echarts_instance_]').first()
    await expect
      .poll(async () => (await inst.count()) > 0, { timeout: 30_000 })
      .toBe(true)
    const opt = await readOption(inst)
    const reg = (opt?.series ?? []).find((s: any) => s.name === '回归线')
    expect(reg, '回归线系列应存在').toBeTruthy()
    expect(reg.lineStyle?.color, '回归线 lineStyle 应有色').toBeTruthy()
    expect(reg.itemStyle?.color, '回归线图例 marker 色应等于线色').toBe(reg.lineStyle.color)
  })
})
