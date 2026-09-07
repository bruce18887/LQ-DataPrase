import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { pickTabFile } from '../helpers/params'
import { waitLoadingGone } from '../helpers/charts'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 矩阵格 → 散点轻联动 + 方法下拉（2026-09-06 参照原型补能力批次）。
 *
 * 1. 矩阵模式点击非对角格 → 自动切到散点视图并选中该对参数（复用既有
 *    watch([localX, localY]) 自动加载），KPI 卡出现且含 p 值卡；
 * 2. 对角格（恒 1，无信息量）点击不响应，停留矩阵视图；
 * 3. 方法下拉切 Spearman 重算 → meta 行显示方法名（请求携带 method，
 *    后端 correlation_matrix 校验 pearson/spearman/kendall）。
 */

const MATRIX_RADIO = '.el-radio-button'
const CONTAINER = '.el-tab-pane:visible .chart-wrapper div[_echarts_instance_]'

test.describe('@p2 相关性矩阵点格联动散点', { tag: ['@p2', '@analysis'] }, () => {
  test('点非对角格切散点选中该对；对角格不响应；方法下拉生效', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await page.getByRole('tab', { name: /相关性对比/ }).click()
    await pickTabFile(page, 'correlation', RECOMMENDED.analysis)
    await page.locator(MATRIX_RADIO).filter({ hasText: '相关性矩阵' }).first().click()
    await page.getByRole('button', { name: /计算相关性矩阵/ }).click()
    await waitLoadingGone(page)

    const container = page.locator(CONTAINER).first()
    await expect(container).toBeVisible({ timeout: 20_000 })

    // 从实例读坐标轴目录与格心像素（convertToPixel 对类目轴吃类目名）
    const info = await container.evaluate((el: any) => {
      const inst = el.__echartsInstance__
      const params: string[] = inst.getOption().xAxis[0].data
      return {
        params,
        diagPx: inst.convertToPixel({ seriesIndex: 0 }, [params[0], params[0]]),
        pairPx: inst.convertToPixel({ seriesIndex: 0 }, [params[0], params[1]]),
      }
    })
    const [xName, yName] = [info.params[0], info.params[1]]
    expect(xName, '矩阵应至少有 2 个参数').toBeTruthy()
    expect(yName).toBeTruthy()
    const box = await container.boundingBox()
    expect(box, '矩阵容器应有布局尺寸').not.toBeNull()

    // 1) 对角格 [0,0] 不响应：仍停留矩阵视图
    await page.mouse.click(box!.x + info.diagPx[0], box!.y + info.diagPx[1])
    await expect(
      page.locator('.el-radio-button.is-active').filter({ hasText: '相关性矩阵' }),
    ).toBeVisible()
    await expect(page.locator(CONTAINER).first()).toBeVisible()

    // 2) 非对角格 [0,1] → 切散点并选中该对（联动复用自动加载，等该请求落地）
    const corrP = page.waitForResponse(
      (r) => r.url().includes('/analysis/correlation/') && r.request().method() === 'POST',
      { timeout: 25_000 },
    )
    await page.mouse.click(box!.x + info.pairPx[0], box!.y + info.pairPx[1])
    const resp = await corrP
    const body = resp.request().postDataJSON()
    expect(body.param_x, '散点请求 X 应等于所点格行参数').toBe(xName)
    expect(body.param_y, '散点请求 Y 应等于所点格列参数').toBe(yName)

    await expect(
      page.locator('.el-radio-button.is-active').filter({ hasText: '散点图' }),
    ).toBeVisible()
    const layout = page.locator('.analysis-tab-layout:visible')
    await expect(layout.locator('.metric-card').first()).toBeVisible({ timeout: 15_000 })
    await expect(layout.locator('.metric-card').filter({ hasText: 'p 值' })).toBeVisible()
    // X/Y select 显示该对参数（选中后 label 文本在 select 内）
    await expect(layout.locator('.el-select').filter({ hasText: xName }).first()).toBeVisible()
    await expect(layout.locator('.el-select').filter({ hasText: yName }).first()).toBeVisible()

    // 3) 方法下拉：切 Spearman 重算 → meta 行显示方法（请求体也带 method）
    await page.locator(MATRIX_RADIO).filter({ hasText: '相关性矩阵' }).first().click()
    // data-corr-method 契约选择器：卡内还有参数多选，按 .el-select 顺序会点错
    await page.locator('.el-tab-pane:visible [data-corr-method]').click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: 'Spearman' }).first().click()
    const matrixP = page.waitForResponse(
      (r) => r.url().includes('/statistics/correlation_matrix/') && r.request().method() === 'POST',
      { timeout: 25_000 },
    )
    await page.getByRole('button', { name: /计算相关性矩阵/ }).click()
    const mResp = await matrixP
    expect((mResp.request().postDataJSON() as Record<string, unknown>).method).toBe('spearman')
    await waitLoadingGone(page)
    await expect(page.locator('.el-tab-pane:visible .matrix-meta')).toContainText('spearman')
  })
})
