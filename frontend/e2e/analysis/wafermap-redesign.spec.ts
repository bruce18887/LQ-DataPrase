import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { pickTabFile } from '../helpers/params'
import { expectChartRendered } from '../helpers/charts'

/**
 * 晶圆图对齐保守重设计原型（2026-09-08 spec）形态契约：
 * 着色 4 档 / 分区独立 checkbox / 左栏两表 / 自动结论条 / 参数值着色降级。
 * 文件统一用种子 CP 数据 BN281R3CYCAA（唯一带 Wafer 坐标的种子文件）。
 * 契约属性：data-wafer-color / data-wafer-stat-table / data-wafer-conclusion
 * （见 e2e/README.md 选择器契约章节）。
 */

const FILE_SUBSTR = 'BN281R3CYCAA'

async function enterWafer(page: import('@playwright/test').Page) {
  await gotoApp(page, '/analysis')
  await page.getByRole('tab', { name: /晶圆图/ }).click()
  await pickTabFile(page, 'wafer', FILE_SUBSTR)
  const loadBtn = page.locator('button').filter({ hasText: '加载晶圆图' })
  await expect(loadBtn).toBeEnabled({ timeout: 120_000 })
  const respPromise = page.waitForResponse(
    (r) => r.url().includes('/analysis/wafer_map/') && r.request().method() === 'POST',
    { timeout: 180_000 },
  )
  await loadBtn.click()
  expect((await respPromise).status()).toBe(200)
  const panel = page.getByRole('tabpanel', { name: /晶圆图/ })
  await expect(panel.locator('[data-wafer-stat-table]')).toBeVisible({ timeout: 30_000 })
  return panel
}

async function seriesNames(chart: ReturnType<import('@playwright/test').Page['locator']>) {
  return chart.evaluate((el: any) => {
    const opt = el.__echartsInstance__.getOption()
    return (opt.series as any[]).map((s) => s.name)
  })
}

test.describe('@p1 晶圆图重设计形态', { tag: ['@p1', '@analysis'] }, () => {
  test('着色 4 档：result 双系列 → bin 多分组 → param 档选参数前回落注记', async ({ page }) => {
    const panel = await enterWafer(page)
    const chart = panel.locator('div[_echarts_instance_]').first()
    await expectChartRendered(chart, 0, 60_000)

    // result 档：Pass + Fail 两系列
    let names = await seriesNames(chart)
    expect(names).toContain('Pass')
    expect(names).toContain('Fail')

    // bin 档：种子 CP 文件多 bin → 系列 > 2 且以 Bin 开头
    await panel.locator('[data-wafer-color] .el-radio-button').filter({ hasText: 'Bin' }).click()
    await page.waitForResponse(
      (r) => r.url().includes('/analysis/wafer_map/') && r.request().method() === 'POST',
    )
    await expectChartRendered(chart, 0, 60_000)
    names = await seriesNames(chart)
    const binNames = names.filter((n: string) => n.startsWith('Bin'))
    expect(binNames.length, 'CP 文件应有多个 bin 分组').toBeGreaterThan(1)

    // param 档（未选参数 = 降级契约）：回落 Pass/Fail + 注记可见
    await panel.locator('[data-wafer-color] .el-radio-button').filter({ hasText: '参数值' }).click()
    await page.waitForResponse(
      (r) => r.url().includes('/analysis/wafer_map/') && r.request().method() === 'POST',
    )
    await expectChartRendered(chart, 0, 60_000)
    names = await seriesNames(chart)
    expect(names).toContain('Pass')
    expect(names).toContain('Fail')
    await expect(panel.locator('.wafer-fallback-note')).toContainText('回落')
  })

  test('分区 checkbox：勾选 → 环带三系列，取消 → 回判定结果着色', async ({ page }) => {
    const panel = await enterWafer(page)
    const chart = panel.locator('div[_echarts_instance_]').first()
    await expectChartRendered(chart, 0, 60_000)

    const zoneCheckbox = panel.locator('.el-checkbox').filter({ hasText: '分区模式' })
    await zoneCheckbox.check()
    await expect.poll(() => seriesNames(chart)).toEqual(
      expect.arrayContaining(['中心区', '中间区', '边缘区']),
    )

    await zoneCheckbox.uncheck()
    await expect.poll(() => seriesNames(chart)).toEqual(
      expect.arrayContaining(['Pass', 'Fail']),
    )
  })

  test('左栏两表：统计表「总 die」与图 title 子文本 Total 一致（防口径漂移）', async ({ page }) => {
    const panel = await enterWafer(page)
    const chart = panel.locator('div[_echarts_instance_]').first()
    await expectChartRendered(chart, 0, 60_000)

    const titleSub = await chart.evaluate((el: any) => el.__echartsInstance__.getOption().title[0].subtext)
    const total = Number(/Total: (\d+)/.exec(titleSub)![1])
    const statTotal = await panel
      .locator('[data-wafer-stat-table] tr')
      .filter({ hasText: '总 die' })
      .locator('td.n')
      .innerText()
    expect(Number(statTotal)).toBe(total)
  })

  test('自动结论条：三区有数时出现且文案含「径向梯度」', async ({ page }) => {
    const panel = await enterWafer(page)
    // 分区数据在选文件后默认拉一次，但比晶圆图请求慢：先等空态行消失（zones 落数），
    // 再数区行（空态行本身也是一个 tr，直接 toHaveCount(3) 会把「还空着」误判成成功）
    await expect(panel.locator('[data-wafer-zone-table] .stat-empty')).toHaveCount(0, { timeout: 60_000 })
    await expect(panel.locator('[data-wafer-zone-table] tbody tr')).toHaveCount(3)
    const conclusion = panel.locator('[data-wafer-conclusion]')
    // 某区 total=0 时 yield=null → 结论条按契约不出现；种子 CP 文件三区都有 die，
    // 若环境数据漂移到空区，跳过而不是假红
    if (!(await conclusion.isVisible())) {
      const emptyZone = await panel
        .locator('[data-wafer-zone-table] tbody tr')
        .filter({ hasText: '-' })
        .count()
      test.skip(emptyZone > 0, '分区数据存在空区（环境数据漂移），结论条契约不适用')
    }
    await expect(conclusion).toContainText(/径向梯度/)
  })
})
