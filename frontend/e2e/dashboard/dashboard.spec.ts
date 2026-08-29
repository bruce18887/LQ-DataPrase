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
 * 选择器依据（DashboardPage.vue，2026-08-30 指南 §11.2 重设计后）：
 *  - 总览条：data-testid="overview-strip"（取代 KPI 大卡）
 *  - Section 卡头 <h3>：「Bin 构成」等；Site 柱线图 aria-label=Site良率柱线组合图
 *  - Bin×Site 交叉表：卡内「表格 / 热力图」页签，表格 data-testid=bin-site-table
 *  - UPH 紧凑明细行：卡头「⚡ UPH 效率明细」，公式 ? 悬停 .uph-metric-label__help
 */

// describe 只挂模块 tag，优先级由各用例标题的 @pN 前缀承担（避免用例在多个 P 项目重复执行）
test.describe('仪表板', { tag: ['@dashboard'] }, () => {
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
    // 总览条就绪（file_id 就绪）后导出按钮才有效
    await expect(page.getByTestId('overview-strip')).toBeVisible()
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

  test('@p1 总览条字段可见（取代 KPI 大卡）', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)
    const strip = page.getByTestId('overview-strip')
    await expect(strip).toBeVisible()
    // 指南 §11.2 字段：程序/总记录/Pass/Fail/Yield/UPH/测试时长/测试开始 + 格式 chip；
    // UPH 标签内含公式 ? 悬停子元素，不能用 exact 匹配
    for (const label of ['总记录', 'Pass', 'Fail', 'Yield', '测试时长', '测试开始']) {
      await expect(strip.getByText(label, { exact: true }).first(), `总览条应含 ${label}`).toBeVisible()
    }
    await expect(strip.getByText(/UPH/).first(), '总览条应含 UPH').toBeVisible()
  })

  test('@p1 图表渲染（Bin Pareto + Site 柱线组合）', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)
    // Section 卡头确认内容区已进入（非空/错误态）
    await expect(page.getByRole('heading', { name: /Bin 构成/ })).toBeVisible()
    await expect(page.getByRole('heading', { name: /Site 良率/ })).toBeVisible()
    // Site 柱线组合图为 ECharts（SVG/canvas）；Pareto 为纯 CSS 条形
    await waitForCharts(page, 1)
    const siteChart = page.getByRole('img', { name: 'Site良率柱线组合图' })
    if (await siteChart.count()) {
      await expectChartRendered(siteChart, 0)
    }
  })

  /**
   * 课题1 回归：单文件分析的 SiteYield / BinSiteCrossTable 等图表
   * 从直接 echarts.init 改为 initEchartsWhenReady（零尺寸容器保护）。
   * 断言：各 role=img 图表容器内 svg/canvas 尺寸 > 0，且控制台无「DOM width or height」0 尺寸警告。
   */
  test('@p1 §课题1 单文件分析图表非空渲染且无 0 尺寸警告', async ({ page }) => {
    const errors = collectConsoleErrors(page)
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)

    // 关键图表容器（aria-label 来自各组件模板；重设计后：饼图/仪表盘/柱状图 → 柱线组合 + 热力图页签）
    const labels = [
      'Site良率柱线组合图',
    ]
    // 热力图需先切页签才挂载（v-if）
    const heatmapTab = page.getByText('热力图', { exact: true }).first()
    if (await heatmapTab.isVisible().catch(() => false)) {
      await heatmapTab.click()
      labels.push('Bin×Site热力图')
    }
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

  test('@p1 UPH 紧凑明细行显示', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)
    // UphCard.vue 卡头文本（重设计后标题改为「效率明细」）
    await expect(page.getByText('UPH 效率明细').first()).toBeVisible()
    // 紧凑明细行字段（平均测试时间 / 并行站点数）
    await expect(page.getByText('平均测试时间').first()).toBeVisible()

    // UPH helper（2026-08-13）：hover 问号图标 → tooltip 展示计算公式
    // （el-tooltip popper teleport 到 body，须 :visible + .last()）
    const helpIcon = page.locator('.uph-card .uph-metric-label__help').first()
    await expect(helpIcon).toBeVisible()
    await helpIcon.hover()
    const popper = page.locator('.el-popper:visible').last()
    await expect(popper).toContainText('× 3600', { timeout: 5_000 })
    // 「并行站点模型/测试时间」行仅在 site_count 就绪时渲染（部分文件无站点数），不作硬断言
  })

  test('@p1 Site 良率柱线组合图渲染', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)

    // 重设计（2026-08-30）：gauge 仪表盘已删除，整体 Yield 由总览条承载；
    // 单文件页的良率可视化 = Site 柱线组合图（柱色阶 + 良率折线）。
    const siteChart = page.getByRole('img', { name: 'Site良率柱线组合图' })
    if (await siteChart.count() === 0) {
      // 无 Site 数据时组件显示空态文案
      await expect(page.getByText('该阶段无 Site 数据')).toBeVisible()
      return
    }
    await expect(siteChart).toBeVisible({ timeout: 15_000 })
    await expectChartRendered(siteChart, 0)
    // 卡头 3 pills（最高/最低/Δ）
    await expect(page.getByText(/最高 /).first()).toBeVisible()
    await expect(page.getByText(/最低 /).first()).toBeVisible()
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
    await expect(page.getByTestId('overview-strip')).toBeVisible()
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
    // UPH 数据态（批次汇总）：紧凑明细行字段与来源标签可见（重设计后无 Units/Hour 大格）
    await expect(page.getByText('平均测试时间').first()).toBeVisible()
    await expect(page.getByText('批次汇总')).toBeVisible()
    // UPH helper 公式内容（重设计后来源文案改为行内标签，不再进 tooltip）
    const batchHelp = page.locator('.uph-card:visible .uph-metric-label__help').first()
    if (await batchHelp.isVisible().catch(() => false)) {
      await batchHelp.hover()
      const bPopper = page.locator('.el-popper:visible').last()
      await expect(bPopper).toContainText('× 3600', { timeout: 5_000 })
    }
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

    // 2) 至少 3 个 ECharts 容器（per-phase 饼图 + Top Fail 柱图 + Site 良率柱线图）；
    // 2026-08-30 重设计：Bin×Site 柱状图已改为「表格/热力图」页签（默认表格视图无图表容器）
    const chartContainers = binCard.locator('.chart-container, .chart-fill, [aria-label*="图"]')
    const chartCount = await chartContainers.count()
    expect(chartCount, 'Bin 分布卡内图表容器数应 >= 3').toBeGreaterThanOrEqual(3)
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
   * 测试项总览（TestItemOverviewSection.vue）：11 列全宽表格（排序/分页/点击行跳转分析页）
   * + 卡头双复选框行级过滤 + CPK 四色堆叠比例条 + Top 10 Fail 信息 chip 行。
   */
  test('@p1 测试项总览表格渲染（表头 + 比例条 + chip）', async ({ page }) => {
    const errors = collectConsoleErrors(page)
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)

    // 总览区表格（重设计后无独立 h2 标题，卡头在 panel-head）
    const table = page.locator('.overview-table')
    await expect(table).toBeVisible({ timeout: 20_000 })

    // 表头列（11 列：Fail数量+Fail占比 已合并为单列 Fail）
    const headers = ['参数名称', '数据点数', 'Mean', 'STD', 'Min', 'Max', 'LSL', 'USL', 'CPK', 'CPK Level', 'Fail']
    for (const h of headers) {
      await expect(table.locator('th', { hasText: h }).first(), `表头应含 ${h}`).toBeVisible()
    }

    // 卡头双复选框（默认勾选）
    await expect(page.getByText('忽略无 Limit')).toBeVisible()
    await expect(page.getByText('忽略无测试值')).toBeVisible()

    // 页脚统计与分页（总项数 = 过滤后行数）
    await expect(page.getByText(/共 \d+ 项/)).toBeVisible()
    await expect(page.locator('.overview-footer .el-pagination')).toBeVisible()

    // 下方两图已由新形态取代：CPK 饼图 → 四色堆叠比例条；Top 10 柱状 → 信息 chip 行（有数据时渲染）
    const cpkStrip = page.locator('.cpk-strip')
    if (await cpkStrip.count()) {
      await expect(cpkStrip).toBeVisible()
    }
    const failChips = page.locator('.fail-chip')
    if (await failChips.count()) {
      await expect(page.getByText('Top 10 Fail 测试项')).toBeVisible()
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

  test('@p2 测试项总览分页切换（固定 100 条/页）', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)

    const table = page.locator('.overview-table')
    await expect(table).toBeVisible({ timeout: 20_000 })
    const pagination = page.locator('.overview-footer .el-pagination')
    await expect(pagination).toBeVisible()

    // 双复选框默认勾选（行级过滤）：取消勾选恢复全量行数，保证总项数口径与历史一致
    const checks = page.locator('.ov-check input')
    if (await checks.count() === 2) {
      await checks.nth(0).uncheck()
      await checks.nth(1).uncheck()
    }

    // 固定 100 条/页：不渲染 page-size 切换器（.el-pagination__sizes）
    await expect(pagination.locator('.el-pagination__sizes')).toHaveCount(0)

    // 首页行数 = min(总项数, 100)，精确验证固定分页大小
    const totalText = await page.locator('.overview-total').innerText()
    const m = totalText.match(/共 (\d+) 项/)
    expect(m, '页脚应显示总项数').not.toBeNull()
    const total = parseInt(m![1], 10)
    const firstPageRows = await table.locator('.el-table__body-wrapper tr.el-table__row').count()
    expect(firstPageRows, `首页行数应 = min(${total}, 100)`).toBe(Math.min(total, 100))

    // 默认文件不足两页时，切换到高列数文件（1728 列 → 总览 >100 项）制造多页数据
    let pageCount = await pagination.locator('.el-pager li').count()
    if (pageCount <= 1) {
      const fileSelect = page.locator('.dash-file-select')
      await fileSelect.click()
      await fileSelect.locator('input').fill('BPD93204_FT1')
      await page
        .locator('.dp-file-select-dropdown .el-select-dropdown__item', { hasText: 'BPD93204_FT1' })
        .first()
        .click()
      // 等待总览刷新：总项数 > 100（1728 列文件的 CPK 参数表 + Fail 明细）
      await expect(async () => {
        const t = await page.locator('.overview-total').innerText()
        const n = parseInt((t.match(/共 (\d+) 项/) || [])[1] || '0', 10)
        expect(n, '切换高列数文件后总项数应 > 100').toBeGreaterThan(100)
      }).toPass({ timeout: 30_000 })
      // 多页数据下首页仍固定 100 行
      const rows = await table.locator('.el-table__body-wrapper tr.el-table__row').count()
      expect(rows, '多页数据下首页应恰好 100 行').toBe(100)
      pageCount = await pagination.locator('.el-pager li').count()
    }
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
