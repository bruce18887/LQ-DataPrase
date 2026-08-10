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
 * 序列分布：散点图 fail 数量与文件 bin 汇总颗数一致（回归钉）。
 *
 * 缺陷形态（用户报告）：fail 值远超规格限（如 Kelvin 10000 vs USL 10）时被
 * 显式 Y 轴整段裁切不可见；且 fail 判定只看当前参数是否超限，跨测试项 fail
 * 的 die 看起来像 pass。修复后：
 *  - fail 按 die 最终 bin 判定（fail_count 与 bin 汇总颗数一致），点色与
 *    站点图例一致（不标红）；
 *  - 超界值锚定到可见轴边缘（anchor=2/3），无测量值点不绘制（anchor=1，
 *    避免在 X 轴底部被误读为 0 值数据点；颗数仍计入副标题）；
 *  - 副标题显示 Pass/Fail 颗数。
 */

const SINGLE = '.single-param-tab'

/** 8 行 → 6 颗 die（KELVIN_VIN 限值 [0,2]，Y 轴 [-0.2, 2.2]）：重测对 ×2 + 跨项 fail + 无值 fail + 超高值 */
const FAIL_CSV = [
  'CTA8280F,',
  'Device Name,TEST_DEVICE,',
  '[Data]',
  'Index_No,Dut_No,Serial_No,Site_No,Dut_Pass,SW_Bin,X_COORD,Y_COORD,QR_Code,Test_Time,Data_Num,KELVIN_VIN,',
  'Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,ohm,',
  'Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,0,',
  'Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,2,',
  '1,1,1,1,TRUE,1,0,0,None,4.1,10,1.0,',
  '2,1,2,1,TRUE,5,0,0,None,4.1,10,3.0,',
  '3,1,2,1,TRUE,1,0,0,None,4.2,10,1.5,',
  '4,1,3,1,TRUE,1,0,0,None,4.1,10,0.5,',
  '5,1,3,1,TRUE,7,0,0,None,4.1,10,5000.0,',
  '6,1,4,1,TRUE,5,0,0,None,4.1,10,2.5,',
  '7,1,5,1,TRUE,5,0,0,None,4.1,10,1.0,',
  '8,1,6,1,TRUE,5,0,0,None,4.3,10,,',
  '',
].join('\n')

test.describe('序列分布：fail 数量与 bin 汇总颗数一致', { tag: ['@p1', '@analysis'] }, () => {
  let filename = ''
  let csvPath = ''

  test.beforeAll(() => {
    filename = `e2e_serial_fail_${Date.now()}.csv`
    csvPath = path.join(os.tmpdir(), filename)
    fs.writeFileSync(csvPath, FAIL_CSV, 'utf-8')
  })

  test.afterAll(() => {
    cleanupQuiet(csvPath)
  })

  test('fail 颗数一致：颗数=bin 汇总、超高值锚定、无值 die 可见', async ({ page }) => {
    // 上传
    await gotoApp(page, '/data')
    await page.locator('button').filter({ hasText: '上传文件' }).click()
    await uploadFile(page, csvPath)
    await expect(page.getByText(/上传成功/).first()).toBeVisible({ timeout: 60_000 })

    // 分析页 → 序列分布
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, filename)
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
    const body = await resp.json()

    // 响应契约：die 级 fail_count 与文件 bin 汇总一致（6 颗 die，4 颗最终 bin != 1）
    expect(body.fail_count).toBe(4)
    expect(body.pass_count).toBe(2)
    const pts = (body.series_data || []).flatMap((s: { data: unknown[] }) => s.data)
    const bySerial = new Map(pts.map((p: number[]) => [p[0], p]))
    // 重测对取最终结果：首测 fail(3.0)/复测 pass(1.5) → pass 且值取复测
    expect(bySerial.get(2)).toEqual([2, 1.5, 0, 0])
    // 复测 fail 且值 5000 远超 y_max(2.2) → is_fail=1、anchor=2（顶部锚定可见）
    expect(bySerial.get(3)).toEqual([3, 5000.0, 1, 2])
    // 跨测试项 fail：值 1.0 在限内但 bin != 1 → is_fail=1、anchor=0
    expect(bySerial.get(5)).toEqual([5, 1.0, 1, 0])
    // 无测量值 fail die → 计入 fail_count、anchor=1（响应层保留，UI 不绘制）
    expect(bySerial.get(6)).toEqual([6, null, 1, 1])

    // UI：序列图渲染 + 副标题显示颗数（与 bin 汇总一致）
    const wrapper = page.locator(`${SINGLE} .serial-chart-wrapper`)
    await expect(wrapper).toBeVisible({ timeout: 15_000 })
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)
    await expect(
      wrapper.locator('svg text').filter({ hasText: /Fail: 4/ }).first(),
    ).toBeVisible({ timeout: 15_000 })
    await expect(
      wrapper.locator('svg text').filter({ hasText: /Pass: 2/ }).first(),
    ).toBeVisible({ timeout: 15_000 })

    // 无测量值点不绘制：ECharts 实例中散点数量 = 5（6 颗 die − 1 无值），
    // 不残留锚定在 X 轴底部的幽灵点
    const pointCount = await wrapper.locator('div[_echarts_instance_]').evaluate((el: any) => {
      const opt = el.__echartsInstance__?.getOption?.()
      const series = (opt?.series ?? []).find((s: any) => s.type === 'scatter' && s.data?.length)
      return series?.data?.length ?? 0
    })
    expect(pointCount).toBe(5)
  })
})
