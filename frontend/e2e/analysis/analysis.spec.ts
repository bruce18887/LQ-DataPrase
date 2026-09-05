import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { expectChartRendered, waitLoadingGone } from '../helpers/charts'
import {
  selectAnalysisFile,
  listParams,
  selectParam,
  sampleN,
  filterControl,
  pickTabFile,
} from '../helpers/params'
import { pickOption } from '../helpers/elplus'
import { PARAM_SAMPLE_COUNT, RECOMMENDED, SINGLE_SITE_FILES } from '../fixtures/test-data'

/**
 * 数据分析页（功能最密集）。使用 admin storageState + 预植入数据集。
 *
 * 文件选择策略：
 *   - 单参数 / 趋势 / 相关性 → CTA8280F FT（10000 行，参数最丰富）
 *   - 晶圆图 → STS8200 CP（含 Wafer 坐标，唯一适合 Wafer Map 的文件）
 */

const SINGLE = '.single-param-tab'

async function enterAnalysis(page: import('@playwright/test').Page, filename?: string) {
  await gotoApp(page, '/analysis')
  await selectAnalysisFile(page, filename)
  await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
}

test.describe('@p0 数据分析 - 进入', { tag: ['@p0', '@analysis'] }, () => {
  test('选择 CTA8280F 文件后进入分析并渲染直方图', async ({ page }) => {
    await enterAnalysis(page, RECOMMENDED.analysis)
    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)
  })
})

test.describe('@p1 单参数分析', { tag: ['@p1', '@analysis'] }, () => {
  test(`抽样 ${PARAM_SAMPLE_COUNT} 个参数，逐个断言直方图渲染`, async ({ page }) => {
    test.slow()
    await enterAnalysis(page, RECOMMENDED.analysis)

    const all = await listParams(page)
    expect(all.length, '参数列表应非空').toBeGreaterThan(0)

    const picks = sampleN(all, PARAM_SAMPLE_COUNT)
    console.log(`抽样参数 (${picks.length}/${all.length}): ${picks.join(', ')}`)

    for (const p of picks) {
      await selectParam(page, p)
      await waitLoadingGone(page.locator(SINGLE))
      // 直方图 canvas 应渲染且有尺寸
      await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)
    }

    // 统计摘要存在
    await expect(page.locator(`${SINGLE}`).getByText(/Mean|均值|N\b/i).first()).toBeVisible()
  })

  test('@p1 切换范围类型触发 histogram 重新请求并重渲染', async ({ page }) => {
    await enterAnalysis(page, RECOMMENDED.analysis)
    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)

    // 选「3 Sigma」应携带 range_type=S3 重新请求后端分箱（修复前后端忽略 range_type）
    // 注意：必须过滤请求体 —— 页面加载时 onFileChange 会发一个瘦请求
    // ({file_id, ignore_no_limit})，若其响应晚于本监听注册时刻返回，会被
    // waitForResponse 误捕获（后端慢时确定性复现），导致断言拿到瘦请求体。
    const respPromise = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/histogram/') &&
        r.request().method() === 'POST' &&
        r.request().postData()?.includes('"S3"') === true &&
        r.status() < 500,
      { timeout: 20_000 },
    )

    const panel = page.locator(`${SINGLE} .left-panel`)
    await panel.locator('.el-select').filter({ hasText: 'RowDataLimit' }).first().click()
    await page
      .locator('.el-select-dropdown__item:visible')
      .filter({ hasText: '3 Sigma' })
      .first()
      .click()

    const resp = await respPromise
    const body = resp.request().postData() || ''
    expect(body, 'histogram 请求体应携带 range_type=S3').toContain('S3')

    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)
  })

  test('@p1 开启 QQ 图后渲染 QQ 图与正态性标签', async ({ page }) => {
    await enterAnalysis(page, RECOMMENDED.analysis)
    await waitLoadingGone(page.locator(SINGLE))

    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/analysis/qqplot/') && r.status() < 500,
      { timeout: 20_000 },
    )
    await page.getByText('显示QQ图').click()
    await respPromise

    // QQ 激活后为上下双图（SVG 渲染）
    await expect
      .poll(() => page.locator(`${SINGLE} svg`).count(), { timeout: 15_000 })
      .toBeGreaterThanOrEqual(2)
    await expect(page.locator(`${SINGLE} .normality-tag`)).toBeVisible()
  })

  test('@p1 开启 QQ 图后逐个抽样参数不应触发 4xx/5xx (回归: 空列名 + cross axisPointer)', async ({ page }) => {
    test.slow()
    await enterAnalysis(page, RECOMMENDED.analysis)
    await waitLoadingGone(page.locator(SINGLE))

    // 关键断言 1: 参数下拉里不能出现空字符串（CTA8280F trailing comma 解析 bug 修复）
    const all = await listParams(page)
    expect(all.length, '参数列表应非空').toBeGreaterThan(0)
    for (const p of all) {
      expect(p, '参数下拉不应包含空字符串 / 纯空白列名').toBeTruthy()
      expect(p.trim(), '参数下拉不应包含纯空白列名').toBe(p)
    }

    // 关键断言 2: 开启 QQ 图后, 抽样逐个切换, 不应出现 4xx/5xx
    await page.getByText('显示QQ图').click()

    // 等待首次 qqplot 200 之后, 后续切换也必须 200（避免空列名 400 + ECharts cross axisPointer 500）
    const picks = sampleN(all, Math.min(PARAM_SAMPLE_COUNT, all.length))
    console.log(`QQ 图抽样 (${picks.length}/${all.length}): ${picks.join(', ')}`)

    for (const p of picks) {
      // 等待本次 qqplot 响应, 状态必须 < 400
      const respPromise = page.waitForResponse(
        (r) => r.url().includes('/analysis/qqplot/'),
        { timeout: 20_000 },
      )
      await selectParam(page, p)
      const resp = await respPromise
      expect(
        resp.status(),
        `切换到参数 ${p} 时 qqplot 不应 4xx/5xx (status=${resp.status()})`,
      ).toBeLessThan(400)
      await waitLoadingGone(page.locator(SINGLE))
    }

    // 关键断言 3: 控制台无 getAxesOnZeroOf / DOM width or height 报错
    // （前几次复现 axisPointer: 'cross' + 动态 yAxis 触发的 TypeError）
    const fatalErrors: string[] = []
    page.on('pageerror', (err) => {
      if (err.message.includes('getAxesOnZeroOf') || err.message.includes('DOM width or height')) {
        fatalErrors.push(err.message)
      }
    })
    // 关闭→重开 QQ 图触发的是 qqplot 重载（histogram 只在参数/配置变化时
    // 重发），等 qqplot 响应落地后 ECharts 重新 setOption 验证 axisPointer fix
    const qqResp = page.waitForResponse(
      (r) => r.url().includes('/analysis/qqplot/') && r.status() < 500,
      { timeout: 20_000 },
    )
    await page.getByText('显示QQ图').click() // 关闭
    await page.waitForTimeout(300)
    await page.getByText('显示QQ图').click() // 重新开启
    await qqResp
    await page.waitForTimeout(500)
    expect(fatalErrors, '页面运行时不应出现 axisPointer TypeError').toEqual([])
  })
})

test.describe('@p1 默认配置', { tag: ['@p1', '@analysis'] }, () => {
  test('异常值处理默认为「不处理」', async ({ page }) => {
    await enterAnalysis(page, RECOMMENDED.analysis)
    // data-filter 契约属性定位（不依赖页头位置与顺序）
    await expect(filterControl(page, 'outlier-handling')).toHaveText('不处理')
  })

  test('多文件分析范围类型默认为 RDL', async ({ page }) => {
    await enterAnalysis(page, RECOMMENDED.analysis)
    await page.getByRole('tab', { name: /多文件分析/ }).click()
    // 通过内部 input#multi-range-type 定位到对应的 el-select 包装器
    const rangeSelect = page.locator('.el-select:has(#multi-range-type)')
    await expect(rangeSelect).toHaveText('Spec Limits (RDL)')
  })
})

test.describe('@p1 各分析 Tab 可达', { tag: ['@p1', '@analysis'] }, () => {
  // 注意：UI 已改版——箱线图不再是独立 tab，而是「单文件分析」tab 内的
  // 复选框（显示箱线图），2026-08-26 从 TABS 移除（此前该用例稳定失败）
  const TABS = ['晶圆图', '多文件分析', '相关性对比']

  for (const name of TABS) {
    test(`切换到「${name}」Tab 内容正常渲染`, async ({ page }) => {
      await enterAnalysis(page, RECOMMENDED.analysis)
      await page.getByRole('tab', { name: new RegExp(name) }).click()
      // 激活的 tabpanel 可见且非空
      const panel = page.locator('.el-tabs__content .el-tab-pane').filter({ visible: true }).first()
      await expect(panel).toBeVisible()
      // 不应有未捕获崩溃：页面主体仍在
      await expect(page.locator('.main-layout')).toBeVisible()
    })
  }

  test('@p1 切换 Tab 后返回单文件分析直方图仍渲染', async ({ page }) => {
    await enterAnalysis(page, RECOMMENDED.analysis)
    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)

    // 切到其它 tab 再切回，验证 echarts 在 display:none 恢复后能正确 resize/重绘
    await page.getByRole('tab', { name: /晶圆图/ }).click()
    await page.getByRole('tab', { name: /单文件分析/ }).click()

    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)
  })
})

test.describe('@p2 晶圆图渲染', { tag: ['@p2', '@analysis'] }, () => {
  test('加载 CP 数据后晶圆图 canvas 渲染', async ({ page }) => {
    await enterAnalysis(page, RECOMMENDED.analysis)
    await page.getByRole('tab', { name: /晶圆图/ }).click()
    // 晶圆图吃自己那份文件选择：CP 文件必须在本 tab 内选（单文件 tab 的选择与它无关）
    await pickTabFile(page, 'wafer', RECOMMENDED.waferMap)

    const loadBtn = page.getByRole('button', { name: /加载晶圆图/ })
    if (!(await loadBtn.isVisible().catch(() => false))) {
      test.skip(true, '晶圆图加载按钮不可见')
    }
    const resp = page.waitForResponse(
      (r) => r.url().includes('/analysis/wafer_map/') && r.status() < 500,
      { timeout: 20_000 },
    )
    await loadBtn.click()
    await resp
    // 渲染器无关：上万 die 走 canvas，小晶圆走 svg
    await expectChartRendered(page.locator('.el-tab-pane:visible').first(), 0, 15_000)
  })
})

test.describe('@p1 箱线图', { tag: ['@p1', '@analysis'] }, () => {
  test('箱线图 toggle 显示', async ({ page }) => {
    await enterAnalysis(page, RECOMMENDED.analysis)
    await waitLoadingGone(page.locator(SINGLE))

    // 切换到数值分布模式
    await page.click('.el-radio-button:has-text("数值分布")')

    // 点击显示箱线图 checkbox
    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/statistics/boxplot/') && r.status() < 500,
      { timeout: 20_000 },
    )
    await page.getByText('显示箱线图').click()
    const resp = await respPromise
    expect(resp.status(), 'boxplot API 应返回 200').toBe(200)

    // 验证图表渲染（SVG）
    await expect
      .poll(() => page.locator(`${SINGLE} .chart-wrapper--bottom svg`).count(), { timeout: 15_000 })
      .toBeGreaterThanOrEqual(1)

    // 验证统计表显示
    await expect(page.locator('.boxplot-stats-table')).toBeVisible()
  })

  test('箱线图 groupBy 切换', async ({ page }) => {
    await enterAnalysis(page, RECOMMENDED.analysis)
    await waitLoadingGone(page.locator(SINGLE))

    // 切换到数值分布模式
    await page.click('.el-radio-button:has-text("数值分布")')

    // 开启箱线图
    const respPromise1 = page.waitForResponse(
      (r) => r.url().includes('/statistics/boxplot/') && r.status() < 500,
      { timeout: 20_000 },
    )
    await page.getByText('显示箱线图').click()
    await respPromise1

    // 切换到 bin 分组
    const respPromise2 = page.waitForResponse(
      (r) => r.url().includes('/statistics/boxplot/') && r.status() < 500,
      { timeout: 20_000 },
    )
    await page.locator('.el-select:has-text("按 Site 分组")').click()
    await page.locator('.el-select-dropdown__item:visible:has-text("按 Bin 分组")').click()
    const resp2 = await respPromise2
    expect(resp2.status(), 'boxplot API 应返回 200').toBe(200)

    // 验证图表重新渲染
    await expect
      .poll(() => page.locator(`${SINGLE} .chart-wrapper--bottom svg`).count(), { timeout: 15_000 })
      .toBeGreaterThanOrEqual(1)
  })

  test('箱线图 Jitter 散点切换', async ({ page }) => {
    await enterAnalysis(page, RECOMMENDED.analysis)
    await waitLoadingGone(page.locator(SINGLE))

    // 切换到数值分布模式
    await page.click('.el-radio-button:has-text("数值分布")')

    // 开启箱线图
    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/statistics/boxplot/') && r.status() < 500,
      { timeout: 20_000 },
    )
    await page.getByText('显示箱线图').click()
    await respPromise

    // 开启 Jitter（不需要新的 API 调用）
    await page.getByText('Jitter散点').click()

    // 验证图表更新
    await expect
      .poll(() => page.locator(`${SINGLE} .chart-wrapper--bottom svg`).count(), { timeout: 15_000 })
      .toBeGreaterThanOrEqual(1)
  })

  test('箱线图参数切换显示 loading', async ({ page }) => {
    await enterAnalysis(page, RECOMMENDED.analysis)
    await waitLoadingGone(page.locator(SINGLE))

    // 切换到数值分布模式
    await page.click('.el-radio-button:has-text("数值分布")')

    // 开启箱线图
    const respPromise1 = page.waitForResponse(
      (r) => r.url().includes('/statistics/boxplot/') && r.status() < 500,
      { timeout: 20_000 },
    )
    await page.getByText('显示箱线图').click()
    await respPromise1

    // 切换参数
    const params = await listParams(page)
    if (params.length > 1) {
      const respPromise2 = page.waitForResponse(
        (r) => r.url().includes('/statistics/boxplot/') && r.status() < 500,
        { timeout: 20_000 },
      )
      await selectParam(page, params[1])
      const resp2 = await respPromise2
      expect(resp2.status(), 'boxplot API 应返回 200').toBe(200)

      // 验证图表正确渲染
      await expect
        .poll(() => page.locator(`${SINGLE} .chart-wrapper--bottom svg`).count(), { timeout: 15_000 })
        .toBeGreaterThanOrEqual(1)
    }
  })
})

test.describe('@p1 测试项相关性分析', { tag: ['@p1', '@analysis'] }, () => {
  test('相关性散点图完整流程：选择参数 → 自动加载 → 渲染图表 → 显示指标', async ({ page }) => {
    await enterAnalysis(page, RECOMMENDED.analysis)
    await page.getByRole('tab', { name: /相关性对比/ }).click()
    // 相关性 tab 吃自己那份文件选择：不选到 CTA8280F 就没有 KELVIN_VIN/KELVIN_SW
    await pickTabFile(page, 'correlation', RECOMMENDED.analysis)

    // 相关性工具面板（AnalysisTabLayout 三层布局；旧 .correlation-panel 已随
    // 2026-06-13 重构移除，选择器须匹配当前 DOM）
    const layout = page.locator('.analysis-tab-layout:visible')
    await expect(layout).toBeVisible({ timeout: 10_000 })

    // 选 X/Y 参数——选好后自动触发 correlation 请求（无「分析相关性」按钮）
    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/analysis/correlation/') && r.request().method() === 'POST' && r.status() < 500,
      { timeout: 25_000 },
    )
    await pickOption(page, '选择 X 轴参数', 'KELVIN_VIN', layout)
    // X 下拉关闭动画与 Y 下拉打开重叠会导致选项瞬时不稳定，间隔后再选 Y
    await page.waitForTimeout(600)
    await pickOption(page, '选择 Y 轴参数', 'KELVIN_SW', layout)
    const r = await respPromise
    expect(r.status(), 'correlation API 应返回 200').toBe(200)

    // 散点图渲染（SVG 或 canvas——大文件 large 模式为 canvas）
    const chart = layout.locator('.chart-inner svg, .chart-inner canvas').first()
    await expect(chart, '散点图应渲染').toBeVisible({ timeout: 15_000 })
    const box = await chart.boundingBox()
    expect(box, '图表应有有效尺寸').not.toBeNull()
    expect(box!.width, '宽 > 0').toBeGreaterThan(0)
    expect(box!.height, '高 > 0').toBeGreaterThan(0)

    // Pearson r 指标卡片
    const rCard = layout.locator('.metric-card').first()
    await expect(rCard).toBeVisible()
    await expect(rCard.locator('.metric-value')).not.toBeEmpty()

    // 数据点数指标卡片（Pearson r / R² / 数据点数 / 回归方程 的第 3 张）
    const nCard = layout.locator('.metric-card').nth(2)
    await expect(nCard).toBeVisible()
    const nText = await nCard.locator('.metric-value').innerText()
    expect(Number(nText.replace(/,/g, ''))).toBeGreaterThan(0)
  })

  test('坐标轴范围：西格玛模式出现倍数选择器', async ({ page }) => {
    await enterAnalysis(page, RECOMMENDED.analysis)
    await page.getByRole('tab', { name: /相关性对比/ }).click()
    await pickTabFile(page, 'correlation', RECOMMENDED.analysis)

    const layout = page.locator('.analysis-tab-layout:visible')
    await expect(layout).toBeVisible({ timeout: 10_000 })

    // 选 X/Y 触发自动分析，使坐标轴范围设置卡片出现
    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/analysis/correlation/') && r.request().method() === 'POST' && r.status() < 500,
      { timeout: 25_000 },
    )
    await pickOption(page, '选择 X 轴参数', 'KELVIN_VIN', layout)
    // X 下拉关闭动画与 Y 下拉打开重叠会导致选项瞬时不稳定，间隔后再选 Y
    await page.waitForTimeout(600)
    await pickOption(page, '选择 Y 轴参数', 'KELVIN_SW', layout)
    await respPromise

    // 展开坐标轴范围设置
    const collapse = layout.getByText('坐标轴范围设置')
    await collapse.click()

    // 西格玛模式 → 出现 sigma 倍数选择器
    const axisBody = layout.locator('.axis-body')
    await expect(axisBody).toBeVisible()

    // X 轴切到西格玛
    const xSelects = axisBody.locator('.axis-item').first().locator('.el-select').first()
    await xSelects.click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: '西格玛' }).first().click()
    // 应出现 sigma 倍数选择器
    const sigmaSel = axisBody.locator('.axis-item').first().locator('.el-select').filter({ hasText: 'σ' })
    await expect(sigmaSel, '西格玛模式下应出现 σ 倍数选择器').toBeVisible({ timeout: 5000 })

    // Y 轴切到自定义 → 出现 min/max 输入（X 轴下拉关闭动画后再操作 Y，避免重叠）
    await page.waitForTimeout(600)
    const ySelects = axisBody.locator('.axis-item').nth(1).locator('.el-select').first()
    await ySelects.click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: '自定义' }).first().click()
    const yInputs = axisBody.locator('.axis-item').nth(1).locator('.el-input-number input')
    await expect.poll(() => yInputs.count(), { timeout: 5000 }).toBeGreaterThanOrEqual(2)
  })
})

test.describe('@p2 单 SITE 直方图图例（§2 回归）', { tag: ['@p2', '@analysis'] }, () => {
  /**
   * 当文件 Site_No 列只含 1 个值时（典型如 QA2 阶段只跑 Site 4），
   * 直方图图例文本必须是 `SiteN`（N=该站点编号），绝不能回退为「数据分布」。
   * 实现见 apps/analysis/services/data_services.py §site_histograms
   * （>= 1 守卫）和 frontend/src/pages/analysis/components/HistogramChart.vue
   * hasSiteData / `Site${site}` 命名。
   */
  test('单 SITE 站点图例显示 SiteN 而非「数据分布」', async ({ page }) => {
    test.slow()
    await enterAnalysis(page, SINGLE_SITE_FILES.SITE_4)
    await waitLoadingGone(page.locator(SINGLE))

    // 选个最普通的参数（避免选到全空 / 全相等导致无数据）
    const params = await listParams(page)
    expect(params.length, '参数列表应非空').toBeGreaterThan(0)
    await selectParam(page, params[0])

    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)

    // ECharts 会把 legend 渲染成 SVG <text> 元素。⚠️ 必须用 allTextContents()
    // 而非 allInnerTexts()：SVG 元素的 innerText 恒为空字符串（8/26 教训）。
    const legendTexts = await page.locator(`${SINGLE} text`).allTextContents()
    const flat = legendTexts.join(' | ')

    // 必须出现「Site4」（fixture 是 QA2 阶段只跑 Site 4）
    expect(flat, '单 SITE 图例应包含「Site4」').toMatch(/Site4/)
    // 不能出现旧分支硬编码的「数据分布」
    expect(flat, '单 SITE 时不应再出现「数据分布」字样').not.toMatch(/数据分布/)
  })

  test('gage_m_S1 单 Site1 文件图例也是 Site1', async ({ page }) => {
    test.slow()
    await enterAnalysis(page, SINGLE_SITE_FILES.SITE_1)
    await waitLoadingGone(page.locator(SINGLE))

    const params = await listParams(page)
    expect(params.length).toBeGreaterThan(0)
    await selectParam(page, params[0])
    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)

    const legendTexts = await page.locator(`${SINGLE} text`).allTextContents()
    const flat = legendTexts.join(' | ')
    expect(flat).toMatch(/Site1/)
    expect(flat).not.toMatch(/数据分布/)
  })
})
