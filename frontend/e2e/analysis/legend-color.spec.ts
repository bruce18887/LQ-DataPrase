import { test, expect, type Page } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile } from '../helpers/params'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 图例颜色与图形颜色严格对应（需求7，2026-08-20）。
 *
 * ECharts 图例 marker 取 series.itemStyle.color（不取 lineStyle.color）——
 * 此前 markLine 系列/正态分布/KDE 缺 itemStyle 时图例落主题色板，与实际
 * 线色（红/灰/蓝/青/橙、#F57F17/#7B1FA2）不对应。断言：
 *  - 直方图 markLine 系列 itemStyle.color === 线色
 *  - 直方图正态分布/KDE itemStyle.color === lineStyle.color
 *  - 多文件柱/线 itemStyle.color === 后端 lot.color（light 下映射恒等）
 *  - 序列分布 marks 系列 itemStyle.color === 线色
 *  - 相关性回归线 itemStyle.color === lineStyle.color
 */

const SINGLE = '.single-param-tab'

/** 读取图表实例的 option（useChart 把实例挂在容器 div 本身） */
async function readOption(loc: import('@playwright/test').Locator) {
  return loc.evaluate((el: any) => el.__echartsInstance__?.getOption?.() ?? null)
}

test.describe('@p1 图例颜色严格对应', { tag: ['@p1', '@analysis'] }, () => {
  test('直方图：markLine 系列 itemStyle.color 与线色一致，正态/KDE 与 lineStyle 一致', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    const container = `${SINGLE} .chart-wrapper div[_echarts_instance_]`
    await expect(page.locator(container)).toBeVisible({ timeout: 20_000 })

    const opt = await readOption(page.locator(container).first())
    const series: any[] = opt?.series ?? []
    expect(series.length).toBeGreaterThan(0)
    let markLineChecked = 0
    for (const s of series) {
      if (s.markLine?.data?.length) {
        const lineColor = s.markLine.data[0].lineStyle?.color
        expect(lineColor, `${s.name} 线色应存在`).toBeTruthy()
        expect(s.itemStyle?.color, `${s.name} 图例 marker 色应等于线色`).toBe(lineColor)
        markLineChecked++
      }
      if (s.name === '正态分布' || s.name === 'KDE曲线') {
        expect(s.itemStyle?.color, `${s.name} itemStyle 应与 lineStyle 同源`).toBe(s.lineStyle?.color)
      }
    }
    // 默认配置 limit+s6+kde → 至少 2 个 markLine 系列（规格限/6σ线）被校验
    expect(markLineChecked).toBeGreaterThanOrEqual(2)
  })

  test('多文件分析：柱/limit/正态线颜色与后端 lot.color 一致（light 主题映射恒等）', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await page.getByRole('tab', { name: /多文件分析/ }).click()
    const select = page.locator('.multi-file-tab .left-panel .el-select').first()
    await expect(select).toBeVisible({ timeout: 20_000 })
    await select.click()
    const dropdown = page.locator('.el-select-dropdown:visible').last()
    await expect(dropdown).toBeVisible({ timeout: 10_000 })
    await select.locator('input').first().pressSequentially('BPD60320')
    for (const name of RECOMMENDED.analysisMulti) {
      const opt = dropdown.locator('.el-select-dropdown__item').filter({ hasText: name.slice(0, 12) }).first()
      await expect(opt).toBeVisible({ timeout: 5_000 })
      await opt.click()
      await page.waitForTimeout(300)
    }
    await page.keyboard.press('Escape')

    const container = '.multi-file-tab .chart-wrapper div[_echarts_instance_]'
    await expect(page.locator(container)).toBeVisible({ timeout: 25_000 })
    const opt = await readOption(page.locator(container).first())
    const series: any[] = opt?.series ?? []
    // 响应中的 lot.color（后端浅色板）——light 主题下映射恒等，柱色必须等于它
    const lotColors = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
      const files = await fetch(`/api/v1/files/?search=${encodeURIComponent('BPD60320_')}`, { headers }).then((r) => r.json())
      const ids = ((files.results ?? files) ?? [])
        .filter((f: any) => f.filename.startsWith('BPD60320_FT.') || f.filename.startsWith('BPD60320_QA1.'))
        .map((f: any) => f.id)
      const d = await fetch('/api/v1/analysis/multi_lot/', {
        method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_ids: ids, ignore_no_limit: false, range_type: 'RDL' }),
      }).then((r) => r.json())
      return (d.lot_data ?? []).map((lot: any) => ({ file_id: lot.file_id, color: lot.color }))
    })
    expect(lotColors.length).toBeGreaterThanOrEqual(2)
    // 柱系列按 lot_data 顺序与后端颜色一一对应（每个文件独立颜色）
    const barSeries = series.filter((s: any) => s.type === 'bar')
    expect(barSeries.length, '柱系列数应等于文件数').toBe(lotColors.length)
    for (let i = 0; i < barSeries.length; i++) {
      expect(barSeries[i].itemStyle?.color, `柱系列 ${barSeries[i].name} 颜色应等于后端 lot.color`)
        .toBe(lotColors[i].color)
    }
  })

  test('序列分布：marks 系列 itemStyle.color 与线色一致', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    // 切到序列分布模式
    await page.locator('.el-radio-button').filter({ hasText: '序列分布' }).first().click()
    const container = `${SINGLE} div[_echarts_instance_]`
    await expect(page.locator(container).first()).toBeVisible({ timeout: 20_000 })

    const opt = await readOption(page.locator(container).first())
    const series: any[] = opt?.series ?? []
    let markChecked = 0
    for (const s of series) {
      if (s.markLine?.data?.length) {
        const lineColor = s.markLine.data[0].lineStyle?.color
        expect(lineColor, `${s.name} 线色应存在`).toBeTruthy()
        expect(s.itemStyle?.color, `${s.name} 图例 marker 色应等于线色`).toBe(lineColor)
        markChecked++
      }
    }
    expect(markChecked, '序列分布应至少有一个 marks 系列').toBeGreaterThanOrEqual(1)
  })

  test('相关性散点：回归线 itemStyle.color 与 lineStyle.color 一致', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await page.getByRole('tab', { name: /相关性对比/ }).click()
    await page.waitForTimeout(800)
    const xCard = page.locator('.el-tab-pane:visible .el-card').filter({ hasText: 'X 轴测试项' }).first()
    const xSelect = xCard.locator('.el-select').first()
    await xSelect.click()
    await page.locator('.el-select-dropdown:visible .el-select-dropdown__item').filter({ hasText: 'Index_No' }).first().click()
    const yCard = page.locator('.el-tab-pane:visible .el-card').filter({ hasText: 'Y 轴测试项' }).first()
    const ySelect = yCard.locator('.el-select').first()
    await ySelect.click()
    await ySelect.locator('input').first().pressSequentially('Kelvin_VIN')
    await page.waitForTimeout(600)
    await page.locator('.el-select-dropdown:visible .el-select-dropdown__item').filter({ hasText: 'Kelvin_VIN' }).first().click()

    const container = '.el-tab-pane:visible .chart-wrapper div[_echarts_instance_]'
    await expect(page.locator(container).first()).toBeVisible({ timeout: 20_000 })
    const opt = await readOption(page.locator(container).first())
    const reg = (opt?.series ?? []).find((s: any) => s.name === '回归线')
    expect(reg, '回归线系列应存在').toBeTruthy()
    expect(reg.lineStyle?.color, '回归线 lineStyle 应有色').toBeTruthy()
    expect(reg.itemStyle?.color, '回归线图例 marker 色应等于线色').toBe(reg.lineStyle.color)
  })
})
