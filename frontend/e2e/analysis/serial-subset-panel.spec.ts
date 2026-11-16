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
 * serial 高亮 → 右键「打开子集直方图」的接线证明（A 案）。
 * 语义：菜单对「当前高亮集合」开子图，不是「刚刚框的那一下」。
 * 组合判据在 T1/T2；这里只钉真实渲染 + 菜单接线 + 请求体身份。
 */
const SINGLE = '.single-param-tab'
const PREFIX = 'e2e_serial_subset_'

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

test.describe('serial 高亮开子集直方图', { tag: ['@p1', '@analysis'] }, () => {
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
    // admin.json 登录态，token 有效期内 /login 被守卫弹回 /dashboard（同
    // subset-drilldown.spec.ts:68-75 的约定）。
    const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } })
    const page = await ctx.newPage()
    await loginAs(page, 'admin')
    await deleteFilesByNameQuiet(page, PREFIX)
    await ctx.close()
  })

  async function openSerial(page: import('@playwright/test').Page) {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, filename)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))
    await selectParam(page, 'KELVIN_VIN')
    await waitLoadingGone(page.locator(SINGLE))
    await ensureChartToggles(page, { serial: true })
    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} [data-chart-key="serial"]`))
  }

  /** 在容器盒内按分数坐标拖拽；先滚到视口顶部，避免 y 落到折叠线以下。 */
  async function drag(page: import('@playwright/test').Page, sel: string,
                      fx0: number, fy0: number, fx1: number, fy1: number) {
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

  /** 读 serial 图高亮叠加系列的真实序列号。 */
  function highlightSerials(host: import('@playwright/test').Locator) {
    return host.evaluate((el: any) => {
      const series = el.__echartsInstance__?.getOption?.()?.series ?? []
      return series.filter((s: any) => s.name === '高亮芯片')
        .flatMap((s: any) => s.data ?? [])
        .map((p: any) => p.realSerial) as (number | string)[]
    })
  }

  test('框选高亮 → 右键打开子集直方图（n=3，高亮保持）', async ({ page }) => {
    await openSerial(page)
    const chartB = `${SINGLE} [data-chart-key="serial"] .chart-b`
    // 与 subset-drilldown.spec.ts:219 同一块已知矩形：右上覆盖 serial 4/5/6，
    // mouseup 立即消费为高亮。
    await drag(page, chartB, 0.55, 0.06, 0.98, 0.45)
    const host = page.locator(`${SINGLE} .serial-chart-wrapper div[_echarts_instance_]`)
    await expect.poll(async () => (await highlightSerials(host)).length,
      { timeout: 15_000 }).toBe(3)
    expect([...(await highlightSerials(host))].sort((a, b) => Number(a) - Number(b)))
      .toEqual([4, 5, 6])

    // 右键只开 highlight 菜单；R2①：waitForResponse 必须在触发点击之前注册。
    await page.locator(chartB).evaluate((el) => el.scrollIntoView({ block: 'start' }))
    const box = await page.locator(chartB).boundingBox()
    expect(box).not.toBeNull()
    const requery = page.waitForResponse(
      (r) => r.url().includes('/analysis/histogram/')
        && r.request().method() === 'POST'
        && r.request().postData()?.includes('"kind":"serials"') === true
        && r.request().postData()?.includes('"serials":[4,5,6]') === true,
      { timeout: 20_000 },
    )
    await page.mouse.click(box!.x + box!.width * 0.75, box!.y + box!.height * 0.25,
      { button: 'right' })
    const menu = page.locator('[data-chart-context-menu]')
    await expect(menu).toBeVisible({ timeout: 20_000 })
    await expect(page.locator('[data-menu-create-subset]')).toHaveCount(0)
    const openItem = page.locator('[data-menu-open-subset]')
    await expect(openItem).toBeVisible()
    await openItem.click()
    await expect(menu).toHaveCount(0)

    const resp = await requery
    expect(resp.status()).toBe(200)
    const panel = page.locator('[data-subset-panel]')
    await expect(panel).toHaveCount(1)
    await expect(panel).toHaveAttribute('data-subset-n', '3', { timeout: 15_000 })
    const title = panel.locator('.subset-panel__title')
    await expect(title).toContainText('KELVIN_VIN 子集')
    await expect(title).toContainText('3 颗序列')
    // 面板展示即贡献高亮（并集语义）；开子图后高亮不得丢。
    await expect.poll(async () => (await highlightSerials(host)).length,
      { timeout: 15_000 }).toBeGreaterThanOrEqual(3)
  })
})
