import { test, expect, type Page } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import {
  selectAnalysisFile,
  pickTabFile,
  filePicker,
  filterControl,
  pickOutlierMode,
  pickSensitivity,
  listParams,
  selectParam,
} from '../helpers/params'
import { waitLoadingGone } from '../helpers/charts'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 分析页「每个 tab 独立选文件 / 独立筛数据」（2026-09-05）。
 *
 * 改造前：页头一份全局 selectedFileId + 一组全局开关，任一 tab 改选择会静默
 * 换掉其他 tab 的数据源，勾一个开关会连带触发别的 tab 全量重算。
 * 改造后：4 个 tab 各持一份文件、参数列表与数据控件，本文件钉住「互不影响」
 * 这个新契约（请求体与控件现值都是可观察状态，见 lessons R2①）。
 *
 * 计数器一律在 gotoApp **之前**注册（R2④：页面挂载即自动选文件发请求）。
 */

const SINGLE = '.single-param-tab'
const MULTI = '.multi-file-tab'
const LOW_CPK = '仅显示低CPK项'

/** 收集发往某端点的 POST 请求体里的 file_id（按到达顺序） */
function postedFileIds(page: Page, fragment: string): number[] {
  const ids: number[] = []
  page.on('request', (req) => {
    if (req.method() !== 'POST' || !req.url().includes(fragment)) return
    try {
      const body = JSON.parse(req.postData() || '{}')
      if (typeof body.file_id === 'number') ids.push(body.file_id)
    } catch { /* 非 JSON 请求体，忽略 */ }
  })
  return ids
}

/** 收集某端点 POST 请求体里出现的片段（用于断言开关/敏感度按 tab 独立携带） */
function postedBodies(page: Page, fragment: string): string[] {
  const bodies: string[] = []
  page.on('request', (req) => {
    if (req.method() !== 'POST' || !req.url().includes(fragment)) return
    bodies.push(req.postData() || '')
  })
  return bodies
}

test.describe('@p1 分析页 tab 独立文件选择', { tag: ['@p1', '@analysis'] }, () => {
  test('页头不再有全局控件，每个 tab 各有一个文件选择器', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })

    // 旧页头整块（选择数据文件 / 异常值处理 / 敏感度）不复存在
    await expect(page.locator('.analysis-file-selector')).toHaveCount(0)
    // 只挂载了单文件 tab：页面上恰好一个文件选择器，且已自动选中一个文件
    await expect(page.locator('[data-file-picker]')).toHaveCount(1)
    await expect(filePicker(page, 'single')).not.toContainText('选择数据文件', { timeout: 20_000 })
    // 异常值处理在本 tab 的「数据筛选」区内，不再是页头
    await expect(filterControl(page, 'outlier-handling')).toBeVisible()
  })

  test('单文件与晶圆图各选各的文件：请求 file_id 不同且互不覆盖', async ({ page }) => {
    const histIds = postedFileIds(page, '/analysis/histogram/')
    const waferIds = postedFileIds(page, '/analysis/wafer_map/')

    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.locator(SINGLE)).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))
    // 单文件侧的 file_id 必须在**切走之前**取：`/analysis/histogram/` 快路径是
    // 每个 tab 自己发的（晶圆图也要拉参数列表），事后再取会拿到晶圆图那一次
    const singleFileId = histIds[histIds.length - 1]
    expect(singleFileId, '单文件侧应发过 histogram 请求').toBeGreaterThan(0)

    await page.getByRole('tab', { name: /晶圆图/ }).click()
    await pickTabFile(page, 'wafer', RECOMMENDED.waferMap)
    await page.getByRole('button', { name: /加载晶圆图/ }).click()
    await expect(page.getByText('Total Dies')).toBeVisible({ timeout: 120_000 })

    // 两个 tab 的请求打在**不同文件**上：晶圆图请求的 file_id 不等于单文件侧的
    const waferFileId = waferIds[waferIds.length - 1]
    expect(waferFileId, '晶圆图应发过 wafer_map 请求').toBeGreaterThan(0)
    expect(waferFileId, '晶圆图的文件选择不应继承单文件 tab 的选择').not.toBe(singleFileId)

    // 切回单文件 tab：它的选择仍是自己那份（没被晶圆图改成 CP 文件）
    await page.getByRole('tab', { name: /单文件分析/ }).click()
    await expect(filePicker(page, 'single')).toContainText('DA35_BPC50338')
    await expect(filePicker(page, 'wafer')).toContainText('BN281R3CYCAA')
  })

  test('相关性 tab 换文件不影响单文件 tab 的文件与已选参数', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await waitLoadingGone(page.locator(SINGLE))
    const params = await listParams(page)
    expect(params.length, '单文件参数列表应非空').toBeGreaterThan(0)
    await selectParam(page, params[0])
    await waitLoadingGone(page.locator(SINGLE))

    await page.getByRole('tab', { name: /相关性对比/ }).click()
    await pickTabFile(page, 'correlation', RECOMMENDED.gage[0])
    await expect(filePicker(page, 'correlation')).toContainText('gage_m_S1')

    await page.getByRole('tab', { name: /单文件分析/ }).click()
    await expect(filePicker(page, 'single')).toContainText('DA35_BPC50338')
    await expect(page.locator(`${SINGLE} .param-selector`)).toContainText(params[0])
  })

  test('异常值处理与敏感度按 tab 独立：一边改不动另一边', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await waitLoadingGone(page.locator(SINGLE))

    // 单文件 tab 切到裁剪范围
    await pickOutlierMode(page, '裁剪范围')
    await expect(filterControl(page, 'outlier-handling')).toContainText('裁剪范围')
    await expect(filterControl(page, 'iqr-multiplier')).toBeVisible()

    // 相关性 tab 仍是默认的「不处理」——不再是同一份状态
    await page.getByRole('tab', { name: /相关性对比/ }).click()
    await expect(filterControl(page, 'outlier-handling')).toContainText('不处理')

    // 反向：相关性 tab 改档位，单文件 tab 保持裁剪范围
    await pickOutlierMode(page, '裁剪范围', 'correlation')
    await pickSensitivity(page, '宽松', 'correlation')
    await page.getByRole('tab', { name: /单文件分析/ }).click()
    await expect(filterControl(page, 'outlier-handling')).toContainText('裁剪范围')
    await expect(filterControl(page, 'iqr-multiplier')).toContainText('严格')
  })

  test('多文件分析：敏感度贯穿 multi_lot 请求（仅低 CPK 阈值，无裁剪口径）', async ({ page }) => {
    const multiBodies = postedBodies(page, '/analysis/multi_lot/')

    await gotoApp(page, '/analysis')
    await page.getByRole('tab', { name: /多文件分析/ }).click()
    const select = filePicker(page, 'multi')
    await expect(select).toBeVisible({ timeout: 20_000 })
    await select.click()
    const dropdown = page.locator('.el-select-dropdown:visible').last()
    await expect(dropdown).toBeVisible({ timeout: 10_000 })
    await select.locator('input').first().pressSequentially('BPD60320')
    for (const name of RECOMMENDED.analysisMulti) {
      const opt = dropdown.locator('.el-select-dropdown__item').filter({ hasText: name.slice(0, 12) }).first()
      await expect(opt).toBeVisible({ timeout: 10_000 })
      await opt.click()
      await page.waitForTimeout(300)
    }
    await page.keyboard.press('Escape')
    await expect(page.locator(`${MULTI} .common-hint`)).toBeVisible({ timeout: 120_000 })

    // 多文件图表不消费前端裁剪口径 → 数据筛选区里不该有「异常值处理」
    await expect(filterControl(page, 'outlier-handling')).toHaveCount(0)

    // 勾低 CPK 才出现敏感度（它在此 tab 的语义 = 低 CPK 判定阈值）
    await page.locator(`${MULTI} .filter-section .el-checkbox`).filter({ hasText: LOW_CPK }).first().click()
    await expect(filterControl(page, 'iqr-multiplier')).toBeVisible({ timeout: 20_000 })
    await pickSensitivity(page, '宽松', 'multi')

    await expect
      .poll(() => multiBodies.some((b) => b.includes('"iqr_multiplier":3')), { timeout: 120_000 })
      .toBe(true)
  })

  test('未选到有效文件时各 tab 自己出空态，不再靠页头门禁隐藏 tabs', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    // 4 个 tab 恒定可达（旧结构未选文件时整个 tabs 不渲染）
    for (const name of ['晶圆图', '多文件分析', '相关性对比']) {
      await expect(page.getByRole('tab', { name: new RegExp(name) })).toBeVisible()
    }
    // 单文件 tab 有数据即渲染图表，不因别的 tab 的选择而清空
    await waitLoadingGone(page.locator(SINGLE))
    await expect(page.locator(`${SINGLE} .chart-wrapper`).first()).toBeVisible()
    await expect(page.locator(`${SINGLE} .el-empty`)).toHaveCount(0)
  })
})
