import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import {
  pickOptionByKeyword,
  elSelectByPlaceholder,
  popperOf,
  CORR_X_POPPER,
  CORR_Y_POPPER,
} from '../helpers/elplus'
import { expectWindowRows, windowItems, MAX_WINDOW_ROWS } from '../helpers/selectV2'
import { pickTabFile } from '../helpers/params'
import { RECOMMENDED, SEEDED_FILES } from '../fixtures/test-data'

/**
 * 相关性 tab 切文件后必须清空旧文件的散点/指标（回归钉，2026-09-05 审查 H1）。
 *
 * 缺陷形态：localX/localY 是组件本地 ref，切文件时 useTabFileParams 只清参数
 * 列表，X/Y 选择与 corrResult/matrixData 无人重置——散点图、Pearson r、回归
 * 方程无限期显示上一个文件的结果；新文件恰有同名参数时是静默错误数据。
 * 修复后 watch(fileId) 统一清空，界面回到「选择 X/Y 轴参数以分析相关性」空态。
 */

test.describe('@p1 相关性 tab 切文件清空旧结果', { tag: ['@p1', '@analysis'] }, () => {
  test('选好 X/Y 后切文件 → 散点与指标卡清空、X/Y 回到占位符', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await page.getByRole('tab', { name: /相关性对比/ }).click()
    await pickTabFile(page, 'correlation', RECOMMENDED.analysis)

    const layout = page.locator('.analysis-tab-layout:visible')
    await expect(layout).toBeVisible({ timeout: 10_000 })

    /*
     * 哨兵：X/Y 仍是**虚拟窗口**，不是 v1 的全量 option（批4 刀五a 终审，2026-11-21）。
     *
     * 缺口形态：迁移后 X/Y 在 DOM 上的形状（`.el-select` 容器 / 内部 `input` /
     * `.el-select-dropdown__item` 选项行）与 v1 的 `el-select + v-for` **完全同形**
     * ⇒ 把组件改回 v1、把参数全量挂成 option，本文件与其兄弟 spec 照样全绿。
     * 唯一能分辨两种实现的 DOM 事实是「面板打开后到底挂了几行」：v2 只挂窗口那几行
     * （≈8-11），v1 会挂**全部参数**（本夹具实测 180）。所以这里裸开 X/Y 下拉
     * （**不输入关键词**，输入关键词会把候选筛到窗口以下、判据就失去牙齿）、数窗口行、
     * 再按 Escape 收起 —— 不点任何选项，后面的 X/Y 按关键词选不受影响。
     *
     * 前提（候选数 > 窗口界）按下面「选择参数（已选 M/N）」那段文案取 N：它是 X/Y 同一个
     * `params` 源，且**不是**数 DOM 来的（数 DOM 正是本条要防的东西）；前提失败的消息里
     * 带实测值，届时改挑别的夹具而不是放宽界。
     */
    const paramCountLabel = layout.locator('.section-label').filter({ hasText: '选择参数' }).first()
    // 参数列表是异步到的（layout 先可见、`params` 后落地）⇒ 先轮询 N 落地。
    // 不轮询就读到 `0/0`，前提判据等于拿空列表在比 —— 2026-11-21 首跑实测就是这么假红的。
    await expect
      .poll(
        async () => Number(/已选 \d+\/(\d+)/.exec((await paramCountLabel.textContent()) ?? '')?.[1] ?? 0),
        { message: '相关性的参数列表应已落地（已选 M/N 的 N > 0）' },
      )
      .toBeGreaterThan(0)
    const paramTotal = Number(
      /已选 \d+\/(\d+)/.exec((await paramCountLabel.textContent()) ?? '')?.[1] ?? 0,
    )
    expect(
      paramTotal,
      '夹具的参数数须严格大于窗口界，否则下面的窗口行数判据没有牙齿',
    ).toBeGreaterThan(MAX_WINDOW_ROWS)
    await elSelectByPlaceholder(layout, '选择 X 轴参数').first().click()
    const xPopper = popperOf(page, CORR_X_POPPER)
    await expect(xPopper).toBeVisible()
    const xRows = await expectWindowRows(
      windowItems(page, CORR_X_POPPER),
      paramTotal,
      '相关性 X 下拉（未输入关键词时的虚拟窗口）',
    )
    expect(xRows, '虚拟窗口里至少得有可见行，否则计数没意义').toBeGreaterThan(0)
    test.info().annotations.push({
      type: '虚拟窗口实测',
      description: `相关性 X 下拉未输入关键词：DOM ${xRows} 行 / 候选 ${paramTotal} 项 / 界 ${MAX_WINDOW_ROWS}`,
    })
    await page.keyboard.press('Escape')
    await expect(xPopper).toBeHidden()

    await elSelectByPlaceholder(layout, '选择 Y 轴参数').first().click()
    const yPopper = popperOf(page, CORR_Y_POPPER)
    await expect(yPopper).toBeVisible()
    const windowRows = await expectWindowRows(
      windowItems(page, CORR_Y_POPPER),
      paramTotal,
      '相关性 Y 下拉（未输入关键词时的虚拟窗口）',
    )
    expect(windowRows, '虚拟窗口里至少得有可见行，否则计数没意义').toBeGreaterThan(0)
    test.info().annotations.push({
      type: '虚拟窗口实测',
      description: `相关性 Y 下拉未输入关键词：DOM ${windowRows} 行 / 候选 ${paramTotal} 项 / 界 ${MAX_WINDOW_ROWS}`,
    })
    await page.keyboard.press('Escape') // 空关键词 ⇒ EP 真的收起面板（非空时 handleEsc 只清 query）
    await expect(yPopper).toBeHidden()

    // 选 X/Y 触发自动 correlation 请求（无「分析相关性」按钮）
    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/analysis/correlation/') && r.request().method() === 'POST' && r.status() < 500,
      { timeout: 25_000 },
    )
    await pickOptionByKeyword(page, '选择 X 轴参数', 'KELVIN_VIN', layout, CORR_X_POPPER)
    // X 下拉关闭动画与 Y 下拉打开重叠会导致选项瞬时不稳定，间隔后再选 Y
    await page.waitForTimeout(600)
    // KELVIN_SW 在参数表里排得靠后，v2 虚拟窗口初始不含它 ⇒ 先输入关键词再点
    await pickOptionByKeyword(page, '选择 Y 轴参数', 'KELVIN_SW', layout, CORR_Y_POPPER)
    const resp = await respPromise
    expect(resp.status()).toBe(200)

    // 旧文件结果已展示（同屏改造后指标在散点卡头一行）
    await expect(layout.locator('.head-metric').first()).toBeVisible({ timeout: 15_000 })
    await expect(layout.locator('.scatter-chart-inner')).toBeVisible()

    // 切到另一个文件：等新文件自己的参数列表请求（fast-path 携带筛选开关，
    // 不带 params 键——waitForNextHistogramCompute 匹配的是计算请求，这里用不上）
    const listP = page.waitForResponse(
      (r) => r.url().includes('/analysis/histogram/') &&
        r.request().method() === 'POST' &&
        (r.request().postData() || '').includes('"ignore_no_limit"'),
      { timeout: 20_000 },
    )
    await pickTabFile(page, 'correlation', SEEDED_FILES.GAGE_S1)
    await listP

    // 指标与散点清空，回到空态提示
    await expect(layout.locator('.head-metric')).toHaveCount(0)
    await expect(layout.locator('.scatter-chart-inner')).toHaveCount(0)
    await expect(
      layout.locator('.el-empty').filter({ hasText: '选择 X/Y 轴参数或点击矩阵格以分析相关性' }),
    ).toBeVisible()
    // X/Y 选择回到占位符（本地选择已被重置，不是滞留旧文件的参数名）
    await expect(layout.locator('.el-select').filter({ hasText: '选择 X 轴参数' })).toBeVisible()
    await expect(layout.locator('.el-select').filter({ hasText: '选择 Y 轴参数' })).toBeVisible()
  })
})
