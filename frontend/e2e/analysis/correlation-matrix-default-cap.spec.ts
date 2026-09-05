import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { pickTabFile } from '../helpers/params'
import { waitLoadingGone } from '../helpers/charts'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 相关性矩阵默认选择上限。
 *
 * 矩阵是 N×N：默认全选时 N=40 就是 1600 个带文字标签的 heatmap 单元，首屏要卡数秒。
 * 改为默认只取前 12 项（144 格），其余靠「全选」按钮由用户显式加压。
 *
 * 总数与已选数都从页头「选择参数（已选 N/M）」读，不用参数下拉 ——
 * 该下拉属于单文件 tab，切到相关性对比后并不在 DOM 里。
 */

const HEADER = '.matrix-param-header .section-label'

function parseChosenTotal(text: string | null) {
  const m = (text || '').match(/已选\s*(\d+)\s*\/\s*(\d+)/)
  return m ? { chosen: Number(m[1]), total: Number(m[2]) } : null
}

test.describe('@p2 相关性矩阵默认选择', { tag: ['@p2', '@analysis'] }, () => {
  test('参数多于 12 个时默认只选 12 项', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await page.getByRole('tab', { name: /相关性对比/ }).click()
    // 矩阵参数来自相关性 tab 自己的文件与参数列表
    await pickTabFile(page, 'correlation', RECOMMENDED.analysis)
    await page.locator('.el-radio-button').filter({ hasText: '相关性矩阵' }).first().click()

    const label = page.locator(HEADER)
    await expect(label).toBeVisible({ timeout: 10_000 })
    await waitLoadingGone(page)

    const raw = await label.textContent()
    const parsed = parseChosenTotal(raw)
    expect(parsed, `标签应形如「已选 N/M」，实际：${raw}`).not.toBeNull()
    test.skip(parsed!.total <= 12, `该文件仅 ${parsed!.total} 个参数，不足以验证 12 项上限`)

    expect(parsed!.chosen, '默认选择应压到 12 项上限').toBe(12)
    // 上限不止改了标签：计算按钮的项数同步，点击就按 12 项请求
    await expect(page.getByRole('button', { name: /计算相关性矩阵（12 项/ })).toBeVisible()
  })
})
