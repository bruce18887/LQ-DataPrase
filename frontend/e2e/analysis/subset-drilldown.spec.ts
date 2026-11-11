import { test, expect } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { gotoApp } from '../helpers/nav'
import { uploadFile } from '../helpers/upload'
import { cleanupQuiet, deleteFilesByNameQuiet } from '../helpers/cleanup'
import { loginAs } from '../helpers/auth'
import { expectChartRendered, waitLoadingGone } from '../helpers/charts'
import { selectAnalysisFile, selectParam, ensureChartToggles } from '../helpers/params'

/**
 * 框选 → 右键 → 子集直方图面板（接线证明，组合判据在 T1）。
 * 夹具 6 颗 die：KELVIN_VIN [1,1.5,0.5,10,11,12]，限值 [0,2]。
 *  - 直方图右缘框选（触达 overflow 兜底柱）→ hi=null → 子集 {10,11,12} n=3；
 *  - 散点右上框选（锚定轴顶的超界点，D5 WYSIWYG）→ serials {4,5,6} n=3；
 *  - 切参数 → 面板清空（R5）。
 * 上传型用例：afterAll 删 DataFile 行（lessons R2③，deleteFilesByNameQuiet）。
 */

const SINGLE = '.single-param-tab'
const PREFIX = 'e2e_subset_'

const CSV = [
  'CTA8280F,',
  'Device Name,TEST_DEVICE,',
  '[Data]',
  'Index_No,Dut_No,Serial_No,Site_No,Dut_Pass,SW_Bin,X_COORD,Y_COORD,QR_Code,Test_Time,Data_Num,KELVIN_VIN,VCC,',
  'Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,ohm,V,',
  'Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,0,3,',
  'Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,2,3.6,',
  '1,1,1,1,TRUE,1,0,0,None,4.1,10,1.0,3.3,',
  '2,1,2,1,TRUE,1,0,0,None,4.1,10,1.5,3.2,',
  '3,1,3,2,TRUE,1,0,0,None,4.1,10,0.5,3.4,',
  '4,1,4,2,TRUE,1,0,0,None,4.2,10,10.0,3.3,',
  '5,1,5,2,TRUE,1,0,0,None,4.2,10,11.0,3.2,',
  '6,1,6,2,TRUE,1,0,0,None,4.2,10,12.0,3.3,',
  '',
].join('\n')

let filename = ''
let csvPath = ''

test.describe('框选子集直方图', { tag: ['@p1', '@analysis'] }, () => {
  // 共享夹具（beforeAll 上传一次）：必须串行，否则 fullyParallel 下多 worker 的
  // afterAll 按前缀整表删会误杀兄弟 worker 的在测夹具（同账号清理教训）。
  test.describe.configure({ mode: 'serial' })

  test.beforeAll(async ({ browser }) => {
    filename = `${PREFIX}${Date.now()}.csv`
    csvPath = path.join(os.tmpdir(), filename)
    fs.writeFileSync(csvPath, CSV, 'utf-8')
    const page = await browser.newPage()
    await gotoApp(page, '/data')
    await page.locator('button').filter({ hasText: '上传文件' }).click()
    await uploadFile(page, csvPath)
    await expect(page.getByText(/上传成功/).first()).toBeVisible({ timeout: 60_000 })
    await page.close()
  })

  test.afterAll(async ({ browser }) => {
    cleanupQuiet(csvPath)
    // storageState 必须显式清空：browser.newPage()/newContext() 会继承 P1 的
    // admin.json 登录态，token 有效期内 /login 被守卫弹回 /dashboard，loginAs
    // 找不到登录表单必挂（同 serial-no-column.spec.ts:119 的约定）。
    const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } })
    const page = await ctx.newPage()
    await loginAs(page, 'admin')
    await deleteFilesByNameQuiet(page, PREFIX)
    await ctx.close()
  })

  async function openAnalysis(page: import('@playwright/test').Page) {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, filename)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))
    await selectParam(page, 'KELVIN_VIN')
    await waitLoadingGone(page.locator(SINGLE))
  }

  /** 在容器盒内按分数坐标拖拽（起点可在标题留白，spec §5.3）。 */
  async function drag(page: import('@playwright/test').Page, sel: string,
                      fx0: number, fy0: number, fx1: number, fy1: number) {
    // dock 行高可超过视口（实测 .chart-b 高 750 > 720），不滚动时分数 y 会落到
    // 折叠线以下，鼠标事件打在 <html> 背景上 → zrender/contextmenu 都不触发。
    // 先把图滚到视口顶部再取盒，保证拖拽与右键落点可见。
    await page.locator(sel).evaluate((el) => el.scrollIntoView({ block: 'start' }))
    const box = await page.locator(sel).boundingBox()
    expect(box).not.toBeNull()
    const b = box!
    const x0 = b.x + b.width * fx0
    const y0 = b.y + b.height * fy0
    const x1 = b.x + b.width * fx1
    const y1 = b.y + b.height * fy1
    await page.mouse.move(x0, y0)
    await page.mouse.down()
    await page.mouse.move(x1, y1, { steps: 8 })
    await page.mouse.up()
    return { cx: (x0 + x1) / 2, cy: (y0 + y1) / 2 }
  }

  test('直方图框选 → 右键新建子集面板（n=3，CPK 非空）', async ({ page }) => {
    await openAnalysis(page)
    await expectChartRendered(page.locator(`${SINGLE} [data-chart-key="hist"]`))

    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/analysis/histogram/')
        && r.request().method() === 'POST'
        && r.request().postData()?.includes('"kind":"value_range"') === true
        && r.status() < 500,
      { timeout: 20_000 },
    )
    // 右缘 82%→97%：触达 overflow 兜底柱 → hi=null；lo≈1.7+ 排除限内点
    const { cx, cy } = await drag(page, `${SINGLE} [data-chart-key="hist"] .chart-b`, 0.82, 0.5, 0.97, 0.5)
    await page.mouse.click(cx, cy, { button: 'right' })
    await expect(page.locator('[data-chart-context-menu]')).toBeVisible()
    await page.locator('[data-menu-create-subset]').click()
    const resp = await respPromise
    expect(resp.request().postData()).toContain('"hi":null')

    const panel = page.locator('[data-subset-panel]')
    await expect(panel).toHaveCount(1)
    await expect(panel).toHaveAttribute('data-subset-n', '3', { timeout: 15_000 })
    await expect(panel.locator('.stat-item', { hasText: 'CPK' })).toBeVisible()
    await expect(panel.locator('.stat-item', { hasText: 'CPK' }).locator('.stat-value')).not.toHaveText('-')
  })

  test('散点矩形框选 → 右键新建子集面板（serials，n=3）', async ({ page }) => {
    await openAnalysis(page)
    // EP 原生 input.el-checkbox__original 为 0×0 隐藏态，getByRole('checkbox').check()
    // 点不到；走 helpers 的 ensureChartToggles 点可见的 .el-checkbox 标签并收敛到「开」。
    await ensureChartToggles(page, { serial: true })
    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} [data-chart-key="serial"]`))

    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/analysis/histogram/')
        && r.request().method() === 'POST'
        && r.request().postData()?.includes('"kind":"serials"') === true
        && r.status() < 500,
      { timeout: 20_000 },
    )
    // 右上矩形：x 55%→98% 覆盖 serial 4/5/6；y 从标题留白到 grid 40% 覆盖轴顶锚定点
    const { cx, cy } = await drag(page, `${SINGLE} [data-chart-key="serial"] .chart-b`, 0.55, 0.06, 0.98, 0.45)
    await page.mouse.click(cx, cy, { button: 'right' })
    await expect(page.locator('[data-chart-context-menu]')).toBeVisible()
    await page.locator('[data-menu-create-subset]').click()
    const resp = await respPromise
    const body = resp.request().postData() ?? ''
    expect(body).toContain('"kind":"serials"')
    // 钉身份：n=3  alone 不够（反选 {1,2,3} 也是 3 颗）；必须是超界的 {4,5,6}
    const sentSerials = JSON.parse(body).selection.serials as number[]
    expect([...sentSerials].sort((a, b) => a - b)).toEqual([4, 5, 6])

    const panel = page.locator('[data-subset-panel]')
    await expect(panel).toHaveCount(1)
    await expect(panel).toHaveAttribute('data-subset-n', '3', { timeout: 15_000 })
  })

  test('切参数 → 子集面板清空', async ({ page }) => {
    await openAnalysis(page)
    await expectChartRendered(page.locator(`${SINGLE} [data-chart-key="hist"]`))
    const { cx, cy } = await drag(page, `${SINGLE} [data-chart-key="hist"] .chart-b`, 0.82, 0.5, 0.97, 0.5)
    await page.mouse.click(cx, cy, { button: 'right' })
    await page.locator('[data-menu-create-subset]').click()
    await expect(page.locator('[data-subset-panel]')).toHaveCount(1)

    await selectParam(page, 'VCC')
    await waitLoadingGone(page.locator(SINGLE))
    await expect(page.locator('[data-subset-panel]')).toHaveCount(0)
  })

  test('夜间主题：右键菜单可见可读', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('theme', 'night'))
    await openAnalysis(page)
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'night')
    await expectChartRendered(page.locator(`${SINGLE} [data-chart-key="hist"]`))
    const { cx, cy } = await drag(page, `${SINGLE} [data-chart-key="hist"] .chart-b`, 0.82, 0.5, 0.97, 0.5)
    await page.mouse.click(cx, cy, { button: 'right' })
    const menu = page.locator('[data-chart-context-menu]')
    await expect(menu).toBeVisible()
    const item = menu.locator('[data-menu-create-subset]')
    await expect(item).toBeVisible()
    // night 下菜单文字不得是纯黑（var(--text) 应提亮），否则深底不可读
    const color = await item.evaluate((el) => getComputedStyle(el).color)
    expect(color).not.toBe('rgb(0, 0, 0)')
  })
})