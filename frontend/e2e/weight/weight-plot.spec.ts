/**
 * 权重画图的 T3 接线证明：选文件 → 真实渲染出图与表 → 整组开关生效 → 均值展开 → 导出触发下载。
 * 系列数、轴范围、线型这些「option 里算得出来」的判据全在 T2（weightChartOption.spec.ts），
 * 这里一律不重复（testing-gates §2 冲突裁决：T1/T2 能表达的不在浏览器里点）。
 * 也不戳 ECharts 实例：页面只暴露 data-* 契约，测试按 DOM 断言。
 */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'
import { gotoApp } from '../helpers/nav'

// e2e 是 ESM（package.json type=module）：`__dirname` 在此作用域不存在，
// 直接用会在注册用例前就把整个文件崩掉，而 Playwright 会报 "No tests found" 且**退出码 0**。
const __dirname = path.dirname(fileURLToPath(import.meta.url))

const FIXTURE = path.join(__dirname, '..', '..', '..', 'test', 'fixtures', 'weight', 'trim_weight_ci.csv')
const BAD = path.join(__dirname, 'fixtures', 'bad-length.csv')

test.describe('@p1 权重画图', { tag: ['@p1'] }, () => {
  test('14 组渲染、整组开关不删表行、均值展开到 70 行、xlsx 能下载', async ({ page }) => {
    // 收集而不是在事件回调里抛：回调里的 throw 会变成 unhandled，测不出「无控制台错误」。
    const consoleErrors: string[] = []
    page.on('console', (m) => {
      if (m.type() === 'error') consoleErrors.push(m.text())
    })

    await gotoApp(page, '/weight')
    await expect(page.getByTestId('weight-empty-hint')).toBeVisible()   // 空态真实存在

    await page.locator('input[type="file"]').first().setInputFiles(FIXTURE)
    // 每个测试项一张图：14 组 = 14 个容器，第一张的标题属于 WT0001
    await expect(page.getByTestId('weight-chart')).toHaveCount(14)
    await expect(page.getByTestId('weight-chart').first()).toBeVisible()
    await expect(page.getByTestId('weight-chart').first()).toHaveAttribute('data-group', 'WT0001')
    // 真实渲染证据：容器里有 canvas **或** svg 且可见 —— canvas 档下没有 svg，只找 svg 会假绿（R2⑤）
    const painted = page.locator('[data-testid="weight-chart"] canvas, [data-testid="weight-chart"] svg').first()
    await expect(painted).toBeVisible()
    await expect(page.locator('.weight-chip')).toHaveCount(14)
    const rows = page.locator('[data-testid="weight-rows"] .el-table__row')
    await expect(rows).toHaveCount(70)                     // 均值默认打开：56 + 14 条均值行
    // 文本断言必须收窄到表格：图例里也有同名文本（SVG 渲染时进 DOM），全局 getByText 会 strict 冲突。
    await expect(rows.getByText('WT0001_1', { exact: true })).toBeVisible()
    await expect(rows.getByText('WT0001_Avg', { exact: true })).toBeVisible()

    await page.locator('.weight-chip').first().click()
    // 源稿 §6 规则：未勾选组的**表格行保留**，只是不进图 —— 所以行数仍 70、图少一张
    await expect(rows).toHaveCount(70)
    await expect(page.getByTestId('weight-chart')).toHaveCount(13)
    await expect(page.getByTestId('weight-chart').first()).toHaveAttribute('data-group', 'WT0002')
    // 选中态按本仓既有写法断 class（e2e/analysis/kde-curve.spec.ts:54 同形）
    await expect(page.locator('.weight-chip').first()).not.toHaveClass(/is-checked/)
    await expect(painted).toBeVisible()

    await page.locator('.weight-chip').first().click()
    await expect(page.locator('.weight-chip').first()).toHaveClass(/is-checked/)
    await expect(page.getByTestId('weight-chart')).toHaveCount(14)

    await page.getByRole('button', { name: '隐藏均值' }).click()
    await expect(rows).toHaveCount(56)                     // 70 → 56：收回 14 条均值行
    await expect(rows.getByText('WT0001_Avg', { exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: '均值' }).click()
    await expect(rows).toHaveCount(70)                     // 文案随状态翻转，且真能加回
    await expect(rows.getByText('WT0001_Avg', { exact: true })).toBeVisible()

    // waitForEvent 必须注册在触发之前（R2①）；这里不 .catch(() => null)：下载没发生就是红
    const dl = page.waitForEvent('download', { timeout: 30_000 })
    await page.getByRole('button', { name: '导出 Excel' }).click()
    expect((await dl).suggestedFilename()).toMatch(/^Weight_Plot_trim_weight_ci_\d{8}\.xlsx$/)

    expect(consoleErrors, consoleErrors.join('\n')).toEqual([])
  })

  test('解析失败保留现图，并把行号显示出来', async ({ page }) => {
    await gotoApp(page, '/weight')
    await page.locator('input[type="file"]').first().setInputFiles(FIXTURE)
    await expect(page.locator('.weight-chip')).toHaveCount(14)
    await page.locator('input[type="file"]').first().setInputFiles(BAD)
    await expect(page.getByTestId('weight-error')).toContainText('第 2 行')
    await expect(page.locator('.weight-chip')).toHaveCount(14)           // 现图与状态没被清掉
    await expect(page.getByTestId('weight-chart')).toHaveCount(14)
  })
})
