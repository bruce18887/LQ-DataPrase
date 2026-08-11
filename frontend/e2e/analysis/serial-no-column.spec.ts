import { test, expect } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { gotoApp } from '../helpers/nav'
import { uploadFile } from '../helpers/upload'
import { cleanupQuiet } from '../helpers/cleanup'
import { expectChartRendered, waitLoadingGone } from '../helpers/charts'
import { selectAnalysisFile, selectParam } from '../helpers/params'

/**
 * 序列分布：无 Serial_No 列文件的错误提示 + Dut_No 回退 + Site12358 样本文件
 * 端到端验证。
 *
 * 回归 1：CTA8280F 文件缺 Serial_No 列时，后端曾以 HTTP 200 返回
 * ``{'error': 'no_serial_column'}``，前端把它当正常数据渲染出空白序列图
 * （无任何报错）。修复后后端 400 + detail，前端 el-alert 展示提示。
 * 回归 2：真实机台导出（Site12358-Chip12345_c）连 Dut_No 之外的列都没有，
 * 唯一标识是 Dut_No（每 site 内 1..100）——get_serial_column 回退 Dut_No，
 * 序列分布 200 正常渲染；多候选（_n 同时有 Serial_No + Dut_No）按优先级
 * 选 Serial_No，且前端选择器可手动切换。
 */

const SINGLE = '.single-param-tab'

/** 无任何序列候选列（serial/dut/part 都没有）的 CTA8280F 最小文件 */
const NO_SERIAL_CSV = [
  'CTA8280F,',
  'Device Name,TEST_DEVICE,',
  '[Data]',
  'Site_No,SW_Bin,KELVIN_VIN,',
  'Unit,Unit,ohm,',
  'Min,Min,0,',
  'Max,Max,2,',
  '1,1,0.5,',
  '1,1,0.7,',
  '',
].join('\n')

/** 无 X_COORD/Y_COORD 坐标列的 CTA8280F 最小文件（晶圆图缺陷形态） */
const NO_COORD_CSV = [
  'CTA8280F,',
  'Device Name,TEST_DEVICE,',
  '[Data]',
  'Index_No,Dut_No,Serial_No,Site_No,Dut_Pass,SW_Bin,QR_Code,Test_Time,Data_Num,KELVIN_VIN,',
  'Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,ohm,',
  'Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,0,',
  'Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,2,',
  '1,1,1,1,TRUE,1,None,4.1,10,0.5,',
  '2,1,2,1,TRUE,1,None,4.2,10,0.7,',
  '',
].join('\n')

/** STS8200 最小文件：无 Serial 列，唯一标识是 PART_ID（每 site 内的部件序号）。
 * 8 行：Site 8×4 / Site 7×3 / Site 6×1，SOFT_BIN 5 的 1 行失败。 */
const STS8200_NO_SERIAL_CSV = [
  'STS8200-43 StationA',
  'Date:2026-04-18',
  'Tester ID:STS8200-43',
  'User:admin',
  'Program:Z:\\JAVBN281R3CYCAAV1.6\\JAVBN281R3CYCAAV1.6.pgs',
  'Handler: UF200.dll',
  'Site: All Sites',
  'LOT_ID:TTTA803100.03',
  '',
  'Total: 8',
  'Pass: 7   87.50%',
  'Fail: 1   12.50%',
  '',
  'SITE_NUM,PART_ID,PASSFG,SOFT_BIN,T_TIME,X_COORD,Y_COORD,TEST_NUM,CONT_GATE,',
  'Unit,,,,ms,,,,V,',
  'LimitL,,,,,,,,-0.6500,',
  'LimitU,,,,,,,,-0.4700,',
  '',
  '8,1,True,1,1097,165,128,36,-0.5445,',
  '8,2,False,5,1096,165,127,36,-0.5448,',
  '7,1,True,1,1100,166,126,36,-0.5449,',
  '8,3,True,1,1100,165,126,36,-0.5452,',
  '7,2,True,1,1095,166,125,36,-0.5446,',
  '8,4,True,1,1095,165,125,36,-0.5450,',
  '7,3,True,1,1095,165,125,36,-0.5444,',
  '6,1,True,1,1095,166,124,36,-0.5443,',
  '',
].join('\n')

test.describe('序列分布：无序列号列错误提示 + Site12358 修复验证', { tag: ['@p1', '@analysis'] }, () => {
  let filename = ''
  let csvPath = ''
  let noCoordFilename = ''
  let noCoordPath = ''
  let sts8200Filename = ''
  let sts8200Path = ''

  test.beforeAll(() => {
    filename = `e2e_no_serial_${Date.now()}.csv`
    csvPath = path.join(os.tmpdir(), filename)
    fs.writeFileSync(csvPath, NO_SERIAL_CSV, 'utf-8')
    noCoordFilename = `e2e_no_coord_${Date.now()}.csv`
    noCoordPath = path.join(os.tmpdir(), noCoordFilename)
    fs.writeFileSync(noCoordPath, NO_COORD_CSV, 'utf-8')
    sts8200Filename = `e2e_sts8200_part_id_${Date.now()}.csv`
    sts8200Path = path.join(os.tmpdir(), sts8200Filename)
    fs.writeFileSync(sts8200Path, STS8200_NO_SERIAL_CSV, 'utf-8')
  })

  test.afterAll(() => {
    cleanupQuiet(csvPath)
    cleanupQuiet(noCoordPath)
    cleanupQuiet(sts8200Path)
  })

  test('无 Serial_No 列文件：序列分布显示错误提示而非空白图', async ({ page }) => {
    // 上传无 serial 文件
    await gotoApp(page, '/data')
    await page.locator('button').filter({ hasText: '上传文件' }).click()
    await uploadFile(page, csvPath)
    await expect(page.getByText(/上传成功/).first()).toBeVisible({ timeout: 60_000 })

    // 分析页选中该文件，切到序列分布
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, filename)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))

    const respPromise = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/serial_distribution/') &&
        r.request().method() === 'POST' &&
        r.status() < 500,
      { timeout: 20_000 },
    )
    await page.locator('.el-radio-button').filter({ hasText: '序列分布' }).first().click()
    const resp = await respPromise
    expect(resp.status(), '无序列号列必须返回 400（此前 200 静默空白）').toBe(400)
    const body = await resp.json()
    expect(body.error).toBe('no_serial_column')

    // 前端展示错误提示，且不渲染序列图容器（SerialChart 未挂载）
    const alert = page.locator(`${SINGLE} .serial-error-alert`)
    await expect(alert).toBeVisible({ timeout: 15_000 })
    await expect(alert).toContainText('序列列')
    await expect(page.locator(`${SINGLE} .serial-chart-wrapper`)).toHaveCount(0)
  })

  test('STS8200 无 Serial_No 列文件：序列分布回退到 PART_ID 并正常渲染', async ({ page }) => {
    // 上传 STS8200 最小文件（唯一标识列是 PART_ID，无 Serial_No）
    await gotoApp(page, '/data')
    await page.locator('button').filter({ hasText: '上传文件' }).click()
    await uploadFile(page, sts8200Path)
    await expect(page.getByText(/上传成功/).first()).toBeVisible({ timeout: 60_000 })

    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, sts8200Filename)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))

    await selectParam(page, 'CONT_GATE')
    await waitLoadingGone(page.locator(SINGLE))

    const respPromise = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/serial_distribution/') &&
        r.request().method() === 'POST' &&
        r.request().postData()?.includes('"param":"CONT_GATE"') === true,
      { timeout: 20_000 },
    )
    await page.locator('.el-radio-button').filter({ hasText: '序列分布' }).first().click()
    const resp = await respPromise
    expect(resp.status(), 'STS8200 文件必须回退到 PART_ID 并返回 200').toBe(200)

    // 响应体：serial_col=PART_ID、每行一个点（8 行）、bin 判定 7 pass / 1 fail
    const body = await resp.json()
    expect(body.serial_col).toBe('PART_ID')
    const totalPoints = (body.series_data || []).reduce(
      (sum: number, s: { data: unknown[] }) => sum + s.data.length, 0,
    )
    expect(totalPoints).toBe(8)
    expect(body.pass_count).toBe(7)
    expect(body.fail_count).toBe(1)

    // UI：无错误提示，序列图正常渲染
    await expect(page.locator(`${SINGLE} .serial-error-alert`)).toHaveCount(0, { timeout: 15_000 })
    await expect(page.locator(`${SINGLE} .serial-chart-wrapper`)).toBeVisible({ timeout: 15_000 })
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)
  })

  test('STS8200 大文件（1.4 万点）：large 模式 + canvas + tooltip 自定义字段正常', async ({ page }) => {
    // 用 e2e 环境已 seed 的真实 STS8200 样本（14174 行 × PART_ID）
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, 'BN281R3CYCAA_2604160006_TTTA803100.03_06_CP1_20260418161733.csv')
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))
    await selectParam(page, 'CONT_GATE')
    await waitLoadingGone(page.locator(SINGLE))

    const respPromise = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/serial_distribution/') &&
        r.request().method() === 'POST' &&
        r.request().postData()?.includes('"param":"CONT_GATE"') === true,
      { timeout: 20_000 },
    )
    await page.locator('.el-radio-button').filter({ hasText: '序列分布' }).first().click()
    const resp = await respPromise
    expect(resp.status()).toBe(200)
    const body = await resp.json()
    expect(body.serial_col).toBe('PART_ID')

    const wrapper = page.locator(`${SINGLE} .serial-chart-wrapper`)
    await expect(wrapper).toBeVisible({ timeout: 15_000 })
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)

    // 大数据量性能优化钉住：1.4 万点必须启用 ECharts large 模式（每个系列
    // 渲染为单个 path/单次绘制，否则产生上万 SVG DOM 节点拖垮交互）
    const chartInst = wrapper.locator('div[_echarts_instance_]')
    const chartState = await chartInst.evaluate((el: any) => {
      const inst = el.__echartsInstance__
      const opt = inst?.getOption?.()
      return {
        large: opt?.series?.[0]?.large === true,
        // canvas 渲染器：large 数据强制 canvas，DOM 中不应有逐点 svg path
        renderer: !!el.querySelector('canvas') ? 'canvas' : (el.querySelector('svg') ? 'svg' : 'none'),
      }
    })
    expect(chartState.large, '1.4 万点序列分布应启用 ECharts large 模式').toBe(true)
    expect(chartState.renderer, '1.4 万点序列分布应强制 canvas 渲染器').toBe('canvas')

    // large+canvas 模式下 tooltip 自定义字段（realY/isFail/anchor）仍可用：
    // dispatchAction showTip 触发，断言 tooltip 内容包含 PART_ID 与 PASS/FAIL 结果
    await chartInst.evaluate((el: any) => {
      el.__echartsInstance__?.dispatchAction({
        type: 'showTip', seriesIndex: 0, dataIndex: 5,
      })
    })
    await expect(wrapper)
      .toContainText(/结果: (PASS|FAIL)/, { timeout: 5_000 })
    await expect(wrapper)
      .toContainText('PART_ID')
  })

  test('Site12358-Chip12345_c（真实导出，仅 Dut_No）：序列分布回退 Dut_No 正常渲染', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, 'Site12358-Chip12345_c')
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))

    // 选一个有规格限的参数，切到序列分布
    await selectParam(page, 'KELVIN_VIN')
    await waitLoadingGone(page.locator(SINGLE))
    const respPromise = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/serial_distribution/') &&
        r.request().method() === 'POST' &&
        r.request().postData()?.includes('"param":"KELVIN_VIN"') === true,
      { timeout: 20_000 },
    )
    await page.locator('.el-radio-button').filter({ hasText: '序列分布' }).first().click()
    const resp = await respPromise
    expect(resp.status()).toBe(200)

    // 响应体：Dut_No 回退，每行一个序列点 → 共 500 点（5 Site × 100 Dut_No）
    const body = await resp.json()
    expect(body.serial_col).toBe('Dut_No')
    const totalPoints = (body.series_data || []).reduce(
      (sum: number, s: { data: unknown[] }) => sum + s.data.length, 0,
    )
    expect(totalPoints).toBe(500)

    // UI：无错误提示，序列图正常渲染
    await expect(page.locator(`${SINGLE} .serial-error-alert`)).toHaveCount(0, { timeout: 15_000 })
    await expect(page.locator(`${SINGLE} .serial-chart-wrapper`)).toBeVisible({ timeout: 15_000 })
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)
  })

  test('Site12358-Chip12345_n（Serial_No + Dut_No 并存）：优先级自动选 Serial_No', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, 'Site12358-Chip12345_n')
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))

    await selectParam(page, 'KELVIN_VIN')
    await waitLoadingGone(page.locator(SINGLE))
    const respPromise = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/serial_distribution/') &&
        r.request().method() === 'POST' &&
        r.request().postData()?.includes('"param":"KELVIN_VIN"') === true,
      { timeout: 20_000 },
    )
    await page.locator('.el-radio-button').filter({ hasText: '序列分布' }).first().click()
    const resp = await respPromise
    expect(resp.status()).toBe(200)

    // 多候选：优先级 serial > dut，自动选 Serial_No；响应携带完整候选供选择器使用
    const body = await resp.json()
    expect(body.serial_col).toBe('Serial_No')
    expect(body.serial_candidates).toEqual(['Serial_No', 'Dut_No'])
    await expect(page.locator(`${SINGLE} .serial-chart-wrapper`)).toBeVisible({ timeout: 15_000 })
  })

  test('多候选序列列选择器：Serial_No 切到 Dut_No 后图表按新序列列重渲染', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, 'Site12358-Chip12345_n')
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))

    await selectParam(page, 'KELVIN_VIN')
    await waitLoadingGone(page.locator(SINGLE))
    const firstResp = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/serial_distribution/') &&
        r.request().method() === 'POST' &&
        r.request().postData()?.includes('"param":"KELVIN_VIN"') === true &&
        !r.request().postData()?.includes('serial_col'),
      { timeout: 20_000 },
    )
    await page.locator('.el-radio-button').filter({ hasText: '序列分布' }).first().click()
    await firstResp

    // 候选 >1 → 选择器可见，当前值为自动检测的 Serial_No
    const selector = page.locator(`${SINGLE} .serial-col-selector`)
    await expect(selector).toBeVisible({ timeout: 15_000 })
    await expect(selector).toContainText('Serial_No')

    // 切换到 Dut_No → 重新请求，响应 serial_col=Dut_No。
    // 用键盘交互绕开 popper 可见性判定（页面存在多个含 Dut_No 文本的下拉项，
    // 全局 locator 可能命中隐藏的残留项；键盘作用于当前打开的 dropdown）
    const switchResp = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/serial_distribution/') &&
        r.request().method() === 'POST' &&
        r.request().postData()?.includes('"serial_col":"Dut_No"') === true,
      { timeout: 20_000 },
    )
    const sel = selector.locator('.el-select')
    await sel.click()
    // dropdown 已打开（aria-expanded）；打开时高亮 Serial_No → ArrowDown 移到 Dut_No
    await page.keyboard.press('ArrowDown')
    await page.keyboard.press('Enter')
    const resp = await switchResp
    expect(resp.status()).toBe(200)
    const body = await resp.json()
    expect(body.serial_col).toBe('Dut_No')
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)
  })

  test('序列分布：图例与 dataZoom 滑块互不重叠（不被遮挡回归）', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, 'Site12358-Chip12345_c')
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))

    await selectParam(page, 'KELVIN_VIN')
    await waitLoadingGone(page.locator(SINGLE))
    const respPromise = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/serial_distribution/') &&
        r.request().method() === 'POST' &&
        r.request().postData()?.includes('"param":"KELVIN_VIN"') === true,
      { timeout: 20_000 },
    )
    await page.locator('.el-radio-button').filter({ hasText: '序列分布' }).first().click()
    await respPromise
    await expect(page.locator(`${SINGLE} .serial-chart-wrapper`)).toBeVisible({ timeout: 15_000 })
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)

    // 几何不重叠断言：图例行与 dataZoom 滑块在垂直方向不得相交（任一层在另一层上方均可，
    // 当前布局 = 滑块在上、图例在最底）。回归形态：legend 与 dataZoom 都锚定容器底部且
    // ECharts 不自动堆叠 → 图例顶部被滑块覆盖。修复 = 显式 grid.bottom + 两层各自 bottom。
    // dataZoom 滑块定位：svg 底部 100px 内、宽 >500、高 29-45 的矩形 path 并集
    // （滑块背景 h≈30，图例背景 h≈25 即使加宽也达不到 29，可区分）。
    const geometry = await page.locator(`${SINGLE} .serial-chart-wrapper svg`).evaluate((svg) => {
      const svgRect = svg.getBoundingClientRect()
      let sliderTop = Infinity
      let sliderBottom = -Infinity
      for (const p of svg.querySelectorAll('path')) {
        const r = p.getBoundingClientRect()
        if (r.width > 500 && r.height >= 29 && r.height <= 45 && r.bottom > svgRect.bottom - 100) {
          sliderTop = Math.min(sliderTop, r.top)
          sliderBottom = Math.max(sliderBottom, r.bottom)
        }
      }
      const legendRects = [...svg.querySelectorAll('text')]
        .filter((t) => t.textContent?.trim().startsWith('Site '))
        .map((t) => t.getBoundingClientRect())
      return {
        svgBottom: svgRect.bottom,
        sliderTop,
        sliderBottom,
        legendTop: Math.min(...legendRects.map((r) => r.top)),
        legendBottom: Math.max(...legendRects.map((r) => r.bottom)),
        legendCount: legendRects.length,
      }
    })

    expect(geometry.legendCount, '图例项缺失（应为 Site1/2/3/5/8 等）').toBeGreaterThanOrEqual(3)
    expect(geometry.sliderTop, 'dataZoom 滑块未渲染').toBeLessThan(geometry.svgBottom)
    const overlapped = !(
      geometry.legendBottom <= geometry.sliderTop ||
      geometry.legendTop >= geometry.sliderBottom
    )
    expect(
      overlapped,
      `图例与 dataZoom 重叠（图例 [${geometry.legendTop}, ${geometry.legendBottom}]，滑块 [${geometry.sliderTop}, ${geometry.sliderBottom}]）`,
    ).toBe(false)
    expect(geometry.legendBottom, '图例超出图表容器底部').toBeLessThanOrEqual(geometry.svgBottom)
  })

  test('序列分布：切换参数后图例隐藏状态保持（notMerge 重置回归）', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, 'Site12358-Chip12345_c')
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))
    await selectParam(page, 'KELVIN_VIN')
    await waitLoadingGone(page.locator(SINGLE))
    await page.locator('.el-radio-button').filter({ hasText: '序列分布' }).first().click()
    const wrapper = page.locator(`${SINGLE} .serial-chart-wrapper`)
    await expect(wrapper).toBeVisible({ timeout: 15_000 })
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)

    // 读 ECharts 实例的图例交互状态（useChart 特意在容器 DOM 暴露 __echartsInstance__ 供测试）
    const readSelected = () => wrapper.locator('div[_echarts_instance_]').evaluate((el: any) => {
      const opt = el.__echartsInstance__?.getOption?.()
      return (opt?.legend?.[0]?.selected ?? {}) as Record<string, boolean>
    })

    // 点击图例 Site 1 隐藏该 series
    await wrapper.locator('svg text').filter({ hasText: /^Site 1$/ }).first().click()
    await expect.poll(readSelected).toMatchObject({ 'Site 1': false })

    // 切换参数（下一个 ▶ → KELVIN_SW），图例隐藏状态应保持
    await page.locator('.param-selector button').filter({ hasText: '下一个' }).first().click()
    await expect(wrapper).toBeVisible({ timeout: 15_000 })
    await waitLoadingGone(page.locator(SINGLE))
    const after = await readSelected()
    expect(after['Site 1'], `切参数后图例隐藏状态应保持，实际 selected=${JSON.stringify(after)}`).toBe(false)
  })

  test('无坐标列文件：晶圆图显示错误提示而非静默空白（同类裸200回归）', async ({ page }) => {
    // 上传无坐标文件
    await gotoApp(page, '/data')
    await page.locator('button').filter({ hasText: '上传文件' }).click()
    await uploadFile(page, noCoordPath)
    await expect(page.getByText(/上传成功/).first()).toBeVisible({ timeout: 60_000 })

    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, noCoordFilename)
    await expect(page.getByRole('tab', { name: /晶圆图/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))

    // 切到晶圆图 tab，点「加载晶圆图」
    await page.getByRole('tab', { name: /晶圆图/ }).click()
    const respPromise = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/wafer_map/') &&
        r.request().method() === 'POST' &&
        r.status() < 500,
      { timeout: 20_000 },
    )
    await page.locator('button').filter({ hasText: '加载晶圆图' }).click()
    const resp = await respPromise
    expect(resp.status(), '无坐标列必须返回 400（此前 200 静默空白）').toBe(400)
    const body = await resp.json()
    expect(body.error).toBe('no_coord_columns')

    // 前端展示错误提示
    const alert = page.locator('.wafer-error-alert')
    await expect(alert).toBeVisible({ timeout: 15_000 })
    await expect(alert).toContainText('坐标')
  })
})
