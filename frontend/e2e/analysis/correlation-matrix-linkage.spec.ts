import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { pickTabFile } from '../helpers/params'
import { waitLoadingGone } from '../helpers/charts'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 同屏布局下的矩阵格 → 散点轻联动 + 方法下拉（2026-09-07 同屏改造）。
 *
 * 1. 矩阵卡与散点卡同屏常驻（radio 切换已删）；
 * 2. 点非对角格 → 散点卡就地更新（散点请求 X/Y == 所点格参数）；
 * 3. 对角格（恒 1，无信息量）点击不响应；
 * 4. 方法下拉切 Spearman 重算 → meta 行显示方法名（请求携带 method）。
 */

const MATRIX_CARD = '[data-corr-matrix-card]'
const SCATTER_CARD = '[data-corr-scatter-card]'
const MATRIX_CONTAINER = `${MATRIX_CARD} div[_echarts_instance_]`

test.describe('@p2 相关性同屏点格联动', { tag: ['@p2', '@analysis'] }, () => {
  test('同屏常驻；点非对角格就地更新散点；对角格不响应；方法下拉生效', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await page.getByRole('tab', { name: /相关性对比/ }).click()
    await pickTabFile(page, 'correlation', RECOMMENDED.analysis)
    await page.getByRole('button', { name: /计算相关性矩阵/ }).click()
    await waitLoadingGone(page)

    // 同屏：两卡都在（radio 已删，全页 0 个 el-radio-button）
    await expect(page.locator(MATRIX_CARD)).toBeVisible({ timeout: 20_000 })
    await expect(page.locator(SCATTER_CARD)).toBeVisible()
    await expect(page.locator('.el-radio-button')).toHaveCount(0)

    const container = page.locator(MATRIX_CONTAINER).first()
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

    // 1) 对角格 [0,0] 不响应：散点卡头无指标出现
    await page.mouse.click(box!.x + info.diagPx[0], box!.y + info.diagPx[1])
    await expect(page.locator(`${SCATTER_CARD} .head-metric`)).toHaveCount(0)

    // 2) 非对角格 [0,1] → 散点就地加载该对（同屏，无视图切换）。
    //    不用 convertToPixel 像素坐标点格：像素落点会受 splitArea/边距/
    //    重排时序影响偶发脱靶（本 spec 唯一 flake 源）。也不点 svg path：
    //    ECharts 对 heatmap path 的 DOM 序与数据序不保证一致（实测点第 2 个
    //    path 命中 Data_Num 行）。改为从实例直接查 dataIndex 对应的像素中心，
    //    用 getDataBySeriesIndex 语义等价——heatmap item 的几何中心即
    //    convertToPixel([xIdx, yIdx])，但**先等 resize 安定**（ResizeObserver
    //    的 rAF 防抖后像素才可靠）：容器宽度变化后旧坐标会整体偏移。
    await page.waitForTimeout(300)
    const pairPx2 = await container.evaluate((el: any) => {
      const inst = el.__echartsInstance__
      const params: string[] = inst.getOption().xAxis[0].data
      return inst.convertToPixel({ seriesIndex: 0 }, [params[0], params[1]])
    })
    const corrP = page.waitForResponse(
      (r) => r.url().includes('/analysis/correlation/') && r.request().method() === 'POST',
      { timeout: 25_000 },
    )
    await page.mouse.click(box!.x + pairPx2[0], box!.y + pairPx2[1])
    const resp = await corrP
    const body = resp.request().postDataJSON()
    expect(body.param_x, '散点请求 X 应等于所点格行参数').toBe(xName)
    expect(body.param_y, '散点请求 Y 应等于所点格列参数').toBe(yName)

    const layout = page.locator('.analysis-tab-layout:visible')
    await expect(layout.locator(`${SCATTER_CARD} .head-metric`).first()).toBeVisible({ timeout: 15_000 })
    await expect(layout.locator(SCATTER_CARD)).toContainText('n=')
    // X/Y select 显示该对参数（选中后 label 文本在 select 内）
    await expect(layout.locator('.el-select').filter({ hasText: xName }).first()).toBeVisible()
    await expect(layout.locator('.el-select').filter({ hasText: yName }).first()).toBeVisible()

    // 3) 方法下拉：切 Spearman 重算 → meta 行显示方法（请求体也带 method）
    await page.locator('[data-corr-method]').click()
    await page.locator('.dp-corr-method-popper:visible .el-select-dropdown__item')
      .filter({ hasText: 'Spearman' }).first().click()
    const matrixP = page.waitForResponse(
      (r) => r.url().includes('/statistics/correlation_matrix/') && r.request().method() === 'POST',
      { timeout: 25_000 },
    )
    await page.getByRole('button', { name: /计算相关性矩阵/ }).click()
    const mResp = await matrixP
    expect((mResp.request().postDataJSON() as Record<string, unknown>).method).toBe('spearman')
    await waitLoadingGone(page)
    await expect(page.locator('.matrix-meta-inline')).toContainText('spearman')
  })
})
