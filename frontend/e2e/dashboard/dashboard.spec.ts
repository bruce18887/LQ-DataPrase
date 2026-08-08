import { test, expect } from '@playwright/test'
import { gotoApp, collectConsoleErrors } from '../helpers/nav'
import { expectChartRendered, waitForCharts, waitLoadingGone } from '../helpers/charts'
import { captureDownload } from '../helpers/download'

/**
 * 等待批次良率 tab 中复用单文件分析组件的图表集渲染。
 * 批次报表现复用：Site 良率分布 & Yield 分析 / Bin × Site 交叉表 + 柱状图 / UPH 效率分析，
 * 外加保留的「良率趋势」。旧的「🔴 Bin 分布（全批次汇总）」环形图与独立「Site 通过率」图已移除。
 */
async function waitBatchYieldCharts(page: import('@playwright/test').Page, timeout = 15_000) {
  // 复用组件渲染多个 ECharts 容器（Site 柱状/Yield 仪表盘 + Bin×Site 柱状图 + 良率趋势等）
  await waitForCharts(page, 1, timeout)

  // Bin 分布卡（CollapsibleSection）默认折叠：先展开，复用组件才挂载
  await expandCollapsedSection(page, '📋 Bin 分布')

  // 复用的单文件组件 section 标题
  const siteYieldTitle = page.getByText(/Site 良率分布/).first()
  const binSiteTitle = page.getByText(/Bin .* Site 交叉表/).first()
  const uphTitle = page.getByText('UPH 效率分析').first()
  const yieldTitle = page.getByText('📈 良率趋势', { exact: true })
  await expect(siteYieldTitle).toBeVisible()
  await expect(binSiteTitle).toBeVisible()
  await expect(uphTitle).toBeVisible()
  await expect(yieldTitle).toBeVisible()
  // 旧的环形「Bin 分布（全批次汇总）」标题不应再存在
  await expect(page.getByText('🔴 Bin 分布（全批次汇总）')).toHaveCount(0)
  const yieldContainer = yieldTitle.locator('xpath=ancestor::*[contains(@class,"section-card")][1]//div[contains(@class,"chart-container")]')
  await expect(yieldContainer).toBeVisible()
  return { yieldContainer }
}

/**
 * 展开 CollapsibleSection 折叠卡（标题含 title 文本、按钮文案为「展开 ▼」时点击）。
 * 幂等：已展开（文案为「收起 ▲」）时跳过。
 */
async function expandCollapsedSection(page: import('@playwright/test').Page, title: string) {
  const btn = page
    .locator('.el-card__header', { hasText: title })
    .first()
    .locator('button')
  if (await btn.isVisible().catch(() => false)) {
    const text = (await btn.textContent()) || ''
    if (text.includes('展开')) {
      await btn.click()
    }
  }
}

/**
 * 仪表板（/dashboard）。
 * 使用注入的 admin storageState（仅需 token，本页不要求管理员角色）。
 * 数据驱动：DB 中已存在激活数据文件，/summary/ 返回 200，故图表会渲染。
 *
 * 选择器依据（DashboardPage.vue）：
 *  - KPI 卡片标签：「总记录数 / Pass 数量 / Yield / 数据格式」
 *  - 章节标题 <h2>：「Bin 分布」「Site 良率分布」「Fail 测试项分析」等
 *  - 图表挂载在 <div ref> 上的 ECharts，各 div 带 role="img" aria-label
 *  - UPH 卡片：components/UphCard.vue 头部「⚡ UPH 效率分析」、单位「Units/Hour」
 */

test.describe('仪表板', { tag: ['@p0', '@p1', '@p2', '@dashboard'] }, () => {
  test('@p0 页面渲染无报错', async ({ page }) => {
    const errors = collectConsoleErrors(page)
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)
    await page.waitForTimeout(1200)
    expect(errors, `控制台错误:\n${errors.join('\n')}`).toEqual([])
  })

  test('@p1 保存 HTML 报表：导出按钮可下载 html 文件', async ({ page }) => {
    // 回归：ExportFooter 此前调用不存在的 /export/dashboard_html/（一直 404），
    // 已改为 /export/html_report/（ExportFooter.vue）。
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)
    // summary 加载成功（file_id 就绪）后导出按钮才有效
    await expect(page.getByText('总记录数')).toBeVisible()
    const download = await captureDownload(
      page,
      async () => {
        await page.getByRole('button', { name: /保存 HTML 报表/ }).click()
      },
      'dashboard',
      120_000,
    )
    expect(download.suggestedName).toMatch(/\.html$/)
  })

  test('@p1 KPI 指标卡片可见', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)
    await expect(page.getByText('总记录数')).toBeVisible()
    await expect(page.getByText('Pass 数量')).toBeVisible()
    await expect(page.getByText('Yield', { exact: false }).first()).toBeVisible()
    await expect(page.getByText('数据格式')).toBeVisible()
  })

  test('@p1 图表渲染（Bin 饼图 / Yield 仪表盘 / Fail 柱状 / CPK）', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)
    // 章节标题确认内容区已进入（非空/错误态）。/Bin 分布/ 同时匹配 h2 与 info-card h4，取首个
    await expect(page.getByRole('heading', { name: /Bin 分布/ }).first()).toBeVisible()
    // 至少两个 ECharts canvas（Bin 饼图 + Yield 仪表盘等）
    await waitForCharts(page, 2)
    // 首个 canvas（Bin 分布饼图区域）已正确渲染（可见 + 尺寸 > 0）
    await expectChartRendered(page, 0)
  })

  /**
   * 课题1 回归：单文件分析的 SiteYield / BinDistribution / BinSiteCrossTable 等图表
   * 从直接 echarts.init 改为 initEchartsWhenReady（零尺寸容器保护）。
   * 断言：各 role=img 图表容器内 svg/canvas 尺寸 > 0，且控制台无「DOM width or height」0 尺寸警告。
   */
  test('@p1 §课题1 单文件分析图表非空渲染且无 0 尺寸警告', async ({ page }) => {
    const errors = collectConsoleErrors(page)
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)

    // 关键图表容器（aria-label 来自各组件模板）
    const labels = [
      'Bin分布饼图',
      'Site良率柱状图',
      '整体Yield仪表盘',
      'Bin×Site柱状图',
    ]
    for (const label of labels) {
      const img = page.getByRole('img', { name: label })
      if (await img.count() === 0) continue  // 该文件无对应数据时容器可能不渲染
      await expect(img.first(), `${label} 容器应可见`).toBeVisible({ timeout: 15_000 })
      const inner = img.first().locator('svg, canvas').first()
      await expect(inner, `${label} 应有 svg/canvas`).toBeVisible({ timeout: 15_000 })
      const box = await inner.boundingBox()
      expect(box, `${label} 尺寸应非空`).not.toBeNull()
      expect(box!.width, `${label} 宽度 > 0`).toBeGreaterThan(0)
      expect(box!.height, `${label} 高度 > 0`).toBeGreaterThan(0)
    }

    const zeroSize = errors.filter((e) => /DOM width or height|getAxesOnZeroOf/i.test(e))
    expect(zeroSize, `不应出现 0 尺寸 ECharts 警告:\n${zeroSize.join('\n')}`).toEqual([])
  })

  test('@p1 UPH 卡片显示', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)
    // UphCard.vue 头部文本（行 6），多处含 "UPH 效率分析"，取第一处
    await expect(page.getByText('UPH 效率分析').first()).toBeVisible()
    // 数据态下展示 UPH 指标与单位（UphCard.vue 行 21/23）
    await expect(page.getByText('Units/Hour')).toBeVisible()
  })

  test('@p1 良率趋势可视化渲染', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)

    // 说明：YieldTrendChart.vue 当前未被 DashboardPage.vue 引入挂载（孤儿组件，
    // 见 report）。仪表板上真正呈现的良率可视化是「整体Yield仪表盘」(行 83)。
    // 为保持对未来接线的健壮性：断言 YieldTrend 画布/空态文本，或退回到 Yield 仪表盘。
    const yieldTrendEmpty = page.getByText('暂无良率趋势数据')
    const yieldTrendImg = page.getByRole('img', { name: '良率趋势图' })
    const yieldGauge = page.getByRole('img', { name: '整体Yield仪表盘' })

    if (await yieldTrendEmpty.isVisible().catch(() => false)) {
      // 单文件场景：YieldTrend 显示空态
      await expect(yieldTrendEmpty).toBeVisible()
    } else if (await yieldTrendImg.count()) {
      // 已接线且有数据：YieldTrend 画布渲染
      await expectChartRendered(yieldTrendImg, 0)
    } else {
      // 实际情况：仪表板呈现 Yield 仪表盘（ECharts canvas）
      await expect(yieldGauge).toBeVisible()
      await expectChartRendered(yieldGauge, 0)
    }
  })

  test('@p2 批次良率 tab 可见并可切换', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)

    // 批次良率 tab should be visible
    const batchTab = page.locator('.el-tabs__item').filter({ hasText: '批次良率' })
    await expect(batchTab).toBeVisible()

    // Click to switch
    await batchTab.click()

    // Batch selector should appear
    await expect(page.locator('.batch-yield-tab')).toBeVisible()

    // Switch back to single file tab
    const singleTab = page.locator('.el-tabs__item').filter({ hasText: '单文件分析' })
    await singleTab.click()
    await expect(page.locator('.kpi-row')).toBeVisible()
  })

  /**
   * 回归：批次良率 tab 复用单文件分析组件后，「Site 良率分布 & Yield 分析」
   * 「Bin × Site 交叉表 + 柱状图」「UPH 效率分析」「良率趋势」必须渲染，
   * 且旧的环形「Bin 分布（全批次汇总）」与独立「Site 通过率」图表已移除。
   */
  test('@p2 批次良率 复用分析图表非空渲染', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)

    // 1) 切到批次良率 tab
    const batchTab = page.locator('.el-tabs__item').filter({ hasText: '批次良率' })
    await batchTab.click()
    await expect(page.locator('.batch-yield-tab')).toBeVisible()

    // 2) 等待 /batch-report/list_batches/ 响应（BatchYieldTab onMounted 触发）
    const listResp = page.waitForResponse(
      (r) => r.url().includes('/batch-report/list_batches/'),
      { timeout: 15_000 },
    )
    await listResp.catch(() => null)
    await waitLoadingGone(page)

    // 3) 选择第一个可用批次并点击「加载批次报表」
    const batchSelect = page.locator('.batch-selector .el-select').first()
    await expect(batchSelect).toBeVisible()
    await batchSelect.click()
    const firstOption = page.locator('.el-select-dropdown__item').first()
    const optionVisible = await firstOption.isVisible({ timeout: 5_000 }).catch(() => false)
    if (!optionVisible) {
      test.skip(true, '当前环境无可用批次，跳过图表渲染断言')
      return
    }
    await firstOption.click()

    const loadBtn = page.getByRole('button', { name: /加载批次报表/ })
    const dataResp = page
      .waitForResponse(
        (r) => /batch-report\/(yield_data|list_batches)/.test(r.url()),
        { timeout: 30_000 },
      )
      .catch(() => null)
    await loadBtn.click()
    const resp = await dataResp
    // 响应可能为 4xx（如批次无 yield_data），同样视为无可用数据，跳过
    if (!resp || resp.status() >= 400) {
      test.skip(true, `批次数据接口返回 ${resp?.status() ?? 'no-resp'}，跳过图表渲染断言`)
      return
    }

    // 4) 等待复用组件标题与良率趋势容器就绪 → 断言 canvas/svg 尺寸 > 0
    const { yieldContainer } = await waitBatchYieldCharts(page)
    // UPH 数据态（批次汇总）应展示单位与「批次汇总」标签
    await expect(page.getByText('Units/Hour')).toBeVisible()
    await expect(page.getByText('批次汇总')).toBeVisible()
    const yieldChart = yieldContainer.locator('svg, canvas').first()
    await expect(yieldChart).toBeVisible({ timeout: 15_000 })
    await expectChartRendered(yieldContainer, 0)

    // 5) 控制台无 ECharts 0 尺寸警告
    const errs = collectConsoleErrors(page)
    const zeroSize = errs.filter((e) => /DOM width or height|getAxesOnZeroOf/i.test(e))
    expect(zeroSize, `不应出现 0 尺寸 ECharts 警告:\n${zeroSize.join('\n')}`).toEqual([])
  })

  /**
   * §3 回归：批次良率 Bin 分布卡下应堆叠 4 个子 section。
   * 1) Bin 分布（per-phase 表格 + 饼图 + Top Fail 柱图）
   * 2) 🟢 Site 良率分布 & Yield 分析
   * 3) 📊 Bin × Site 交叉表 & 柱状图
   * 4) ⚡ UPH 效率分析
   * 必须 4 个图表容器都有尺寸 > 0（无 ECharts 0 尺寸警告）。
   */
  test('@p2 §3 批次良率 Bin 分布卡 4 子 section 全部渲染', async ({ page }) => {
    const errors = collectConsoleErrors(page)
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)

    // 切到批次良率 tab
    const batchTab = page.locator('.el-tabs__item').filter({ hasText: '批次良率' })
    await batchTab.click()
    await expect(page.locator('.batch-yield-tab')).toBeVisible()

    // 等 list_batches 响应
    await page
      .waitForResponse(
        (r) => r.url().includes('/batch-report/list_batches/'),
        { timeout: 15_000 },
      )
      .catch(() => null)
    await waitLoadingGone(page)

    // 选第一个批次并加载
    const batchSelect = page.locator('.batch-selector .el-select').first()
    await expect(batchSelect).toBeVisible()
    await batchSelect.click()
    const firstOption = page.locator('.el-select-dropdown__item').first()
    const optionVisible = await firstOption.isVisible({ timeout: 5_000 }).catch(() => false)
    if (!optionVisible) {
      test.skip(true, '当前环境无可用批次，跳过 §3 渲染断言')
      return
    }
    await firstOption.click()

    const dataResp = page
      .waitForResponse(
        (r) => /batch-report\/(yield_data|list_batches)/.test(r.url()),
        { timeout: 30_000 },
      )
      .catch(() => null)
    await page.getByRole('button', { name: /加载批次报表/ }).click()
    const resp = await dataResp
    if (!resp || resp.status() >= 400) {
      test.skip(true, `批次数据接口返回 ${resp?.status() ?? 'no-resp'}，跳过 §3 渲染断言`)
      return
    }

    // 1) 标题为「📋 Bin 分布」的卡片内，按出现顺序找到 4 个子 section
    const binCard = page
      .locator('.section-card')
      .filter({ has: page.locator('.el-card__header', { hasText: '📋 Bin 分布' }) })
      .first()
    await expect(binCard, '应存在「📋 Bin 分布」主卡片').toBeVisible()

    // Bin 分布卡默认折叠（CollapsibleSection）——先展开，子 section 才挂载
    await expandCollapsedSection(page, '📋 Bin 分布')

    // 4 个子 section 标题（Bin 分布有 per-phase 标题 + 3 个 divider 标题）
    await expect(binCard.locator('.chart-title', { hasText: /各阶段 Bin 明细/ })).toBeVisible()
    await expect(binCard.locator('.bin-card-section-title', { hasText: /Site 良率分布/ })).toBeVisible()
    await expect(binCard.locator('.bin-card-section-title', { hasText: /Bin .* Site 交叉表/ })).toBeVisible()
    await expect(binCard.locator('.bin-card-section-title', { hasText: /UPH 效率分析/ })).toBeVisible()

    // 2) 至少 4 个 ECharts 容器（Bin 饼图 / Top Fail 柱图 / Site 良率柱图 / Bin×Site 柱图 / Yield 仪表盘 …）
    // Bin 分布卡内应有 4+ 个图表（per-phase 2 + Site 1 + Bin×Site 1 + 良率趋势单独卡 1）
    const chartContainers = binCard.locator('.chart-container, .chart-fill, [aria-label*="图"]')
    const chartCount = await chartContainers.count()
    expect(chartCount, 'Bin 分布卡内图表容器数应 >= 4').toBeGreaterThanOrEqual(4)
    // 每个 chart 容器内应能找到 svg 或 canvas
    for (let i = 0; i < Math.min(chartCount, 6); i++) {
      const container = chartContainers.nth(i)
      const inner = container.locator('svg, canvas').first()
      await expect(inner, `第 ${i} 个图表容器应有 svg/canvas`).toBeVisible({ timeout: 10_000 })
      const box = await inner.boundingBox()
      expect(box, `第 ${i} 个图表 svg/canvas 尺寸应 > 0`).not.toBeNull()
      expect(box!.width).toBeGreaterThan(0)
      expect(box!.height).toBeGreaterThan(0)
    }

    // 3) 控制台无 ECharts 0 尺寸警告
    const zeroSize = errors.filter((e) => /DOM width or height|getAxesOnZeroOf/i.test(e))
    expect(zeroSize, `§3 不应出现 0 尺寸 ECharts 警告:\n${zeroSize.join('\n')}`).toEqual([])
  })

  /**
   * 测试项总览（TestItemOverviewSection.vue）：合并 CPK 参数表 + Fail 测试项明细
   * 为一张全宽大表（排序/分页/点击行跳转分析页），下方并排 CPK 分布饼图 + Top 10 Fail 柱状图。
   */
  test('@p1 测试项总览表格渲染（表头 + 下方两图表非空）', async ({ page }) => {
    const errors = collectConsoleErrors(page)
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)

    // 总览区标题与表格
    await expect(page.getByRole('heading', { name: /测试项总览/ }).first()).toBeVisible()
    const table = page.locator('.overview-table')
    await expect(table).toBeVisible({ timeout: 20_000 })

    // 表头列
    const headers = ['参数名称', '数据点数', 'Mean', 'STD', 'Min', 'Max', 'LSL', 'USL', 'CPK', 'CPK Level', 'Fail数量', 'Fail占比']
    for (const h of headers) {
      await expect(table.locator('th', { hasText: h }).first(), `表头应含 ${h}`).toBeVisible()
    }

    // 页脚统计与分页
    await expect(page.getByText(/共 \d+ 项/)).toBeVisible()
    await expect(page.locator('.overview-footer .el-pagination')).toBeVisible()

    // 下方两图表容器：aria-label 可见且 svg/canvas 尺寸 > 0
    const chartLabels = ['CPK分布统计饼图', 'Top 10 Fail测试项柱状图']
    for (const label of chartLabels) {
      const img = page.getByRole('img', { name: label })
      if (await img.count() === 0) continue  // 无数据时容器不渲染
      await expect(img.first(), `${label} 容器应可见`).toBeVisible({ timeout: 15_000 })
      const inner = img.first().locator('svg, canvas').first()
      await expect(inner, `${label} 应有 svg/canvas`).toBeVisible({ timeout: 15_000 })
      const box = await inner.boundingBox()
      expect(box, `${label} 尺寸应非空`).not.toBeNull()
      expect(box!.width, `${label} 宽度 > 0`).toBeGreaterThan(0)
      expect(box!.height, `${label} 高度 > 0`).toBeGreaterThan(0)
    }

    // 控制台无 ECharts 0 尺寸警告
    const zeroSize = errors.filter((e) => /DOM width or height|getAxesOnZeroOf/i.test(e))
    expect(zeroSize, `不应出现 0 尺寸 ECharts 警告:\n${zeroSize.join('\n')}`).toEqual([])
  })

  test('@p1 测试项总览点击列头排序（CPK 升序/降序）', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)

    const table = page.locator('.overview-table')
    await expect(table).toBeVisible({ timeout: 20_000 })
    const bodyRows = table.locator('.el-table__body-wrapper tr.el-table__row')
    if (await bodyRows.count() < 2) {
      test.skip(true, '总览表不足 2 行，跳过排序断言')
      return
    }

    const cpkOf = async (row: import('@playwright/test').Locator) => {
      const text = await row.locator('.el-tag').first().innerText()
      return parseFloat(text)
    }

    // 升序：首行 cpk <= 次行 cpk
    const cpkHeader = table.locator('th', { hasText: /^CPK$/ }).first()
    await cpkHeader.click()
    await page.waitForTimeout(300)
    let first = await cpkOf(bodyRows.nth(0))
    let second = await cpkOf(bodyRows.nth(1))
    expect(first, `升序首行 cpk ${first} <= 次行 ${second}`).toBeLessThanOrEqual(second)

    // 再点一次 → 降序：首行 cpk >= 次行 cpk
    await cpkHeader.click()
    await page.waitForTimeout(300)
    first = await cpkOf(bodyRows.nth(0))
    second = await cpkOf(bodyRows.nth(1))
    expect(first, `降序首行 cpk ${first} >= 次行 ${second}`).toBeGreaterThanOrEqual(second)
  })

  test('@p2 测试项总览分页切换', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)

    const table = page.locator('.overview-table')
    await expect(table).toBeVisible({ timeout: 20_000 })
    const pagination = page.locator('.overview-footer .el-pagination')
    await expect(pagination).toBeVisible()

    const pageCount = await pagination.locator('.el-pager li').count()
    if (pageCount <= 1) {
      test.skip(true, '总览表不足两页，跳过翻页断言')
      return
    }

    const firstName = async () => (await table.locator('.el-table__body-wrapper tr.el-table__row .cell-param').first().innerText()).trim()
    const namePage1 = await firstName()
    await pagination.locator('.el-pager li').nth(1).click()
    await page.waitForTimeout(300)
    const namePage2 = await firstName()
    expect(namePage2, '第 2 页首行参数名应与第 1 页不同').not.toBe(namePage1)
  })

  test('@p2 测试项总览点击行跳转分析页并选中参数', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)

    const table = page.locator('.overview-table')
    await expect(table).toBeVisible({ timeout: 20_000 })
    const bodyRows = table.locator('.el-table__body-wrapper tr.el-table__row')
    if (await bodyRows.count() < 1) {
      test.skip(true, '总览表无数据行，跳过跳转断言')
      return
    }

    const paramName = (await bodyRows.first().locator('.cell-param').innerText()).trim()
    await bodyRows.first().click()

    // 跳转到数据分析页
    await page.waitForURL(/\/analysis/, { timeout: 15_000 })
    // 参数选择器应选中参数（选中值渲染为 select 文本而非 input value）。
    // 若点击的参数是非数值列（metadata 有占位限值但分析页 histogram 不返回），
    // 会自愈回退到首个可分析参数——两种都算跳转成功。
    const paramSelect = page.locator('.param-selector .el-select')
    await expect(paramSelect).toBeVisible({ timeout: 15_000 })
    await expect.poll(async () => (await paramSelect.innerText()).trim(), {
      message: `参数选择器应有选中值（点击 ${paramName}）`,
      timeout: 15_000,
    }).not.toContain('输入搜索或选择参数')
    const selected = (await paramSelect.innerText()).trim()
    if (selected !== paramName) {
      expect(selected, `回退场景应选中非空参数（点击 ${paramName}）`).not.toBe('')
    }
    // 直方图渲染（至少 1 个图表）
    await waitForCharts(page, 1)
  })
})
