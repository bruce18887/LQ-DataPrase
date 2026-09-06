import fs from 'node:fs'
import path from 'node:path'
import { test, expect, type Page } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile } from '../helpers/params'
import { expectChartRendered, waitLoadingGone } from '../helpers/charts'
import { SAMPLE_DATA_DIR, USER_STATE } from '../fixtures/test-data'

/**
 * 单文件分析图表布局账号级记忆（系统设置 → 显示设置 → 图表布局记忆）。
 *
 * 隔离（关键）：布局/勾选按账号存后端，多 worker 共用 admin 会互相污染——
 * 本 spec 全程使用 user 账号（storageState 覆写）；seed_users 已把 e2e 账号
 * 开关置 False，每个用例开头 API 清场、结尾 finally 清场，不留状态。
 *
 * 三个用例都要独占读写同一账号的 memory 开关/state（开头清场、中途断言），
 * 并行跑会互相覆盖对方的前置状态（实测：主流程读到并行用例刚开的开关、
 * 复位分支读到并行用例的 memory:true 快照）→ 本 describe 必须串行。
 *
 * 文件自给自足：DataFile 按 owner 隔离（seed_test_data 只种 admin），user
 * 账号的分析页是「请先上传数据」空态——本 spec 以 user 身份经 API 上传一份
 * 私有小 CSV（Buyoff BPD60320_QA2，单文件分析已验证可解析的格式）供各用例
 * 分析，用例名做后缀互不冲突，finally 删除；并先清同名残留（上次硬崩遗留）。
 */

test.use({ storageState: USER_STATE })

const SINGLE = '.single-param-tab'
const LAYOUT_KEY = 'lqdp-analysis-chart-layout'
/** 种子 CSV 源（小体积、分析页已验证格式）与各用例上传名（后缀隔离并行） */
const SEED_CSV = path.join(SAMPLE_DATA_DIR, 'Buyoff', 'BPD60320_QA2.csv')
const SEED_BASE = 'e2e_chart_memory'

/** localStorage 仅同源可访问：清场/读态发生在首次导航前（about:blank）会 SecurityError，先落到应用 origin */
async function ensureOnApp(page: Page) {
  if (!page.url().startsWith('http')) await page.goto('/')
}

async function authToken(page: Page): Promise<string> {
  return page.evaluate(() => localStorage.getItem('access_token')) as Promise<string>
}

async function putSettings(page: Page, payload: Record<string, unknown>) {
  await ensureOnApp(page)
  await page.evaluate(async (body) => {
    await fetch('/api/v1/auth/settings/', {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('access_token')}`,
      },
      body: JSON.stringify(body),
    })
  }, payload)
}

async function getSettingsState(page: Page) {
  await ensureOnApp(page)
  return page.evaluate(async () => {
    const resp = await fetch('/api/v1/auth/settings/', {
      headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` },
    })
    return (await resp.json()).analysis_chart_state
  })
}

/** 清掉同名残留文件（上次运行硬崩未走 finally），只动本用例自己的名字（并行安全） */
async function purgeSeedFile(page: Page, name: string) {
  await ensureOnApp(page)
  const token = await authToken(page)
  const headers = { Authorization: `Bearer ${token}` }
  const resp = await page.request.get(
    `/api/v1/files/?search=${encodeURIComponent(name)}&page_size=999`, { headers },
  )
  if (!resp.ok()) return
  const data = (await resp.json()) as { results?: Array<{ id: number }> }
  for (const f of data.results ?? []) {
    await page.request.delete(`/api/v1/files/${f.id}/`, { headers })
  }
}

/** 以 user 身份上传种子 CSV，返回 DataFile id（解析是分析请求时按需进行的） */
async function uploadSeedFile(page: Page, name: string): Promise<number> {
  await purgeSeedFile(page, name)
  const token = await authToken(page)
  const resp = await page.request.post('/api/v1/upload/', {
    headers: { Authorization: `Bearer ${token}` },
    multipart: { files: { name, mimeType: 'text/csv', buffer: fs.readFileSync(SEED_CSV) } },
  })
  if (resp.status() !== 201) throw new Error(`种子文件上传失败: HTTP ${resp.status()}`)
  const created = (await resp.json()) as Array<{ id: number }>
  return created[0].id
}

async function deleteSeedFile(page: Page, id: number) {
  await ensureOnApp(page)
  await page.request.delete(`/api/v1/files/${id}/`, {
    headers: { Authorization: `Bearer ${await authToken(page)}` },
  })
}

function serialToggle(page: Page) {
  return page.locator(`${SINGLE} .chart-toggles .el-checkbox`).filter({ hasText: '显示序列分布' })
}

async function histRowHeight(page: Page): Promise<number> {
  return page.evaluate(() => document.querySelector('.chart-dock__row')!.getBoundingClientRect().height)
}

async function openAnalysis(page: Page, fileLabel: string) {
  await gotoApp(page, '/analysis')
  await selectAnalysisFile(page, fileLabel)
  await waitLoadingGone(page.locator(SINGLE))
  await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)
}

test.describe('@p1 图表布局账号记忆', { tag: ['@p1', '@settings'] }, () => {
  test.describe.configure({ mode: 'serial' })

  test('主流程：UI 开记忆 → 布局+勾选跨刷新保持 → finally 清场', async ({ page }) => {
    test.setTimeout(120_000)
    const seedName = `${SEED_BASE}_main.csv`
    let seedId: number | null = null
    try {
      await putSettings(page, { analysis_chart_memory: false, analysis_chart_state: {} })
      seedId = await uploadSeedFile(page, seedName)
      await gotoApp(page, '/settings')
      await page.getByRole('tab', { name: '📊 显示设置' }).click()
      const memorySwitch = page.getByTestId('chart-memory-switch')
      await expect(memorySwitch).toBeVisible()
      await expect(memorySwitch).not.toHaveClass(/is-checked/)
      await memorySwitch.click()
      await expect(memorySwitch).toHaveClass(/is-checked/)
      const [resp] = await Promise.all([
        page.waitForResponse((r) => /\/auth\/settings\//.test(r.url()) && r.request().method() === 'PUT'),
        page.getByRole('button', { name: '💾 保存设置' }).click(),
      ])
      expect(resp.status()).toBe(200)

      await openAnalysis(page, seedName)
      await serialToggle(page).click()
      await expect(page.locator('.chart-panel[data-chart-key="serial"]')).toBeVisible({ timeout: 20_000 })
      await waitLoadingGone(page.locator(SINGLE))

      // 拖第一根行间条改行占比（套用/持久化的载体）。
      // 方向：rowbar 拖拽语义是「条随手走」——向上拖 → 条上移 → 直方图行变矮
      // （onRowDown: a = a0 + dPct，向下拖则首行变高）；默认 58/42，上拖 120px
      // 后 ≈45/55，远离 200px 单行下限，无 clamp 干扰。
      const beforeDrag = await histRowHeight(page)
      const bar = page.locator('.chart-dock__rowbar').first()
      await bar.scrollIntoViewIfNeeded()
      const b = (await bar.boundingBox())!
      const cx = b.x + b.width / 2
      const cy = b.y + b.height / 2
      await page.mouse.move(cx, cy)
      await page.mouse.down()
      await page.mouse.move(cx, cy - 120, { steps: 8 })
      await page.mouse.up()
      await expect.poll(async () => histRowHeight(page), { timeout: 8_000 }).toBeLessThan(beforeDrag)
      const afterDrag = await histRowHeight(page)

      // 等最后一次改动的防抖 PUT（≤800ms）落库后再刷新：pagehide 冲刷与新页面
      // 的 GET /auth/settings/ 存在到达顺序竞态，先落库让「刷新恢复」可确定断言
      await page.waitForResponse(
        (r) => /\/auth\/settings\//.test(r.url()) && r.request().method() === 'PUT',
        { timeout: 5_000 },
      )

      // 刷新：文件需重选；勾选与布局自动恢复
      await page.reload()
      await openAnalysis(page, seedName)
      await expect(serialToggle(page)).toHaveClass(/is-checked/, { timeout: 20_000 })
      await expect(page.locator('.chart-panel[data-chart-key="serial"]')).toBeVisible({ timeout: 20_000 })
      await expect(page.locator('.chart-dock__row')).toHaveCount(2)
      await expect(page.locator('.chart-dock__rowbar')).toHaveCount(1)
      await expect
        .poll(async () => Math.abs((await histRowHeight(page)) - afterDrag), { timeout: 8_000 })
        .toBeLessThanOrEqual(12)
    } finally {
      await putSettings(page, { analysis_chart_memory: false, analysis_chart_state: {} })
      if (seedId != null) await deleteSeedFile(page, seedId)
    }
  })

  test('推送分支：记忆开 + 账号 state 空 → 分析页改动后勾选/布局上报账号', async ({ page }) => {
    test.setTimeout(120_000)
    const seedName = `${SEED_BASE}_push.csv`
    let seedId: number | null = null
    try {
      await putSettings(page, { analysis_chart_memory: true, analysis_chart_state: {} })
      seedId = await uploadSeedFile(page, seedName)
      await openAnalysis(page, seedName)
      await serialToggle(page).click()
      await expect(page.locator('.chart-panel[data-chart-key="serial"]')).toBeVisible({ timeout: 20_000 })

      // 防抖 800ms 后 PUT（pagehide 兜底）；轮询账号侧 state
      await expect
        .poll(async () => (await getSettingsState(page))?.toggles?.serial, { timeout: 15_000 })
        .toBe(true)
      const state = await getSettingsState(page)
      expect(state.layout?.rows?.flat()).toContain('serial')
    } finally {
      await putSettings(page, { analysis_chart_memory: false, analysis_chart_state: {} })
      if (seedId != null) await deleteSeedFile(page, seedId)
    }
  })

  test('关闭复位分支：记忆关 + 本机残留布局 → 进分析页回默认并清本机', async ({ page }) => {
    test.setTimeout(120_000)
    const seedName = `${SEED_BASE}_reset.csv`
    let seedId: number | null = null
    try {
      await putSettings(page, { analysis_chart_memory: false, analysis_chart_state: {} })
      seedId = await uploadSeedFile(page, seedName)
      // 预置脏本机布局（4 行），再刷新让单例读到
      await gotoApp(page, '/analysis')
      await page.evaluate((key) => {
        localStorage.setItem(
          key,
          JSON.stringify({
            v: 1,
            rows: [['hist'], ['serial'], ['qq'], ['box']],
            rowPcts: [40, 20, 20, 20],
            colPcts: [[100], [100], [50, 50], [100]],
          }),
        )
      }, LAYOUT_KEY)
      await page.reload()
      await openAnalysis(page, seedName)

      // 记忆关：不套用残留 → 默认单行布局，且本机键被清除
      await expect(page.locator('.chart-dock__row')).toHaveCount(1)
      await expect(page.locator('.chart-dock__rowbar')).toHaveCount(0)
      await expect.poll(async () => page.evaluate((key) => localStorage.getItem(key), LAYOUT_KEY)).toBeNull()
    } finally {
      if (seedId != null) await deleteSeedFile(page, seedId)
    }
  })
})
