import { test, expect, type Page } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { waitLoadingGone } from '../helpers/charts'
import { SEEDED_FILES } from '../fixtures/test-data'

/**
 * CPK 三级阈值（系统设置 → 📐 CPK 阈值）→ 仪表板「测试项总览」的等级判定。
 *
 * 回归：A/B/C 三个阈值曾「存了没人读」——分级永远按函数默认 1.67/1.33/1.0 算，
 * 且同一行里 CpkBadge（用后端等级）与 CPK 数值标签（前端按硬编码自评）会出现两套口径。
 *
 * 设置走 API PUT + 刷新，覆盖「设置 → 后端分级 → 前端消费」整条链。
 * admin storageState 共享 → finally 必须写回**原值**（不是硬编码默认）。
 *
 * 文件必须显式选：仪表板挂载时把选中文件重置为「最新的 ready 文件」
 * （`DashboardPage.vue` reconcileSelection），而 e2e 期间别的用例会不断上传新文件
 * ——默认文件一旦换成无限值参数的残件，总览就没有 CPK 可判（实测被 `a.csv` 顶掉）。
 */

interface Thresholds { cpk_a_threshold: number; cpk_b_threshold: number; cpk_c_threshold: number }

async function readThresholds(page: Page): Promise<Thresholds | null> {
  return page.evaluate(async () => {
    const resp = await fetch('/api/v1/auth/settings/', {
      headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` },
    })
    const d = await resp.json()
    return {
      cpk_a_threshold: d?.cpk_a_threshold,
      cpk_b_threshold: d?.cpk_b_threshold,
      cpk_c_threshold: d?.cpk_c_threshold,
    }
  })
}

async function putThresholds(page: Page, t: Thresholds) {
  const status = await page.evaluate(async (value) => {
    const resp = await fetch('/api/v1/auth/settings/', {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('access_token')}`,
      },
      body: JSON.stringify(value),
    })
    return resp.status
  }, t)
  expect(status, `PUT 阈值 ${JSON.stringify(t)}`).toBe(200)
}

/** 首个「CPK 列有数值」的行 → {name, cpk, row}。 */
async function firstCpkRow(page: Page): Promise<{ name: string; cpk: number; row: string }> {
  const rows = page.locator('.overview-table .el-table__row')
  const count = await rows.count()
  for (let i = 0; i < count; i++) {
    const row = rows.nth(i)
    const tag = row.locator('.el-tag').first()
    const text = (await tag.innerText().catch(() => '')).trim()
    const cpk = Number(text)
    if (Number.isFinite(cpk) && cpk > 0) {
      const name = (await row.locator('td').first().innerText()).trim()
      return { name, cpk, row: text }
    }
  }
  throw new Error('测试项总览里没有带 CPK 数值的行')
}

function rowByName(page: Page, name: string) {
  return page.locator('.overview-table .el-table__row').filter({ hasText: name }).first()
}

/** 选中带限值参数的种子文件，并等到总览**真属于这个文件**。
 *
 * 为什么不能只等「表里出现带 CPK 的行」（原写法，2026-10-25 定性为这条红的根因）：
 * `DashboardPage.vue:29` 的数据面板是独立的 `v-if="data"`，与 :22 那条加载态
 * `v-else-if="loading"` **不在同一条 v-if 链里** ⇒ 换文件时旧行整段留在 DOM 上，
 * 直到这个文件自己的 `/summary/` 回来才替换；而 `waitLoadingGone` 找的是
 * `.el-loading-mask`，这种「有数据、在后台刷新」的形状**根本没有遮罩**，它是个空等。
 * 于是旧谓词被**上一个文件的行**满足：探针实测（`--slots=1` 独占跑）选择框已经是
 * `DA35_BPC50338_…csv`，表格却还是自动选中的那个 36 项文件、首行 `CONT_GATE`；
 * 同一次运行的 retry #1 反过来读到目标文件的 165 项 ⇒ base 与 moved 读到不同文件，
 * 「重进后应仍锁定同一行」必红，且红哪一行取决于槽库里有谁（分桶敏感的来源）。
 *
 * 现在等两件事：① 点击之前注册、点完之后收到这个文件的 `/summary/`（已选中同一文件时
 * el-select 不发 change，不会有新响应，硬等会挂死 ⇒ 走 :30s 的行存在性守卫）；
 * ② 渲染出来的行确实来自这份响应（首个带 CPK 行的「名字+两位小数」必须在响应里逐字存在，
 * 且页面所有行名都是响应行名的子集）。两道都不镜像产品的行过滤逻辑。
 */
const SUMMARY_RE = /\/api\/v1\/summary\/?\?/

async function selectedFileName(page: Page): Promise<string> {
  return (await page.locator('.dash-file-select').innerText().catch(() => '')).replace(/\s+/g, ' ')
}

async function pickCpkFile(page: Page) {
  const keyword = SEEDED_FILES.CTA8280F_FT.slice(0, 12)
  const select = page.locator('.dash-file-select')
  const option = page.locator('.dp-file-select-dropdown .el-select-dropdown__item')
    .filter({ hasText: keyword }).first()
  await select.click()
  await select.locator('input').fill(keyword)

  const sameFileAlreadySelected = (await selectedFileName(page)).includes(keyword)
  const responseArrived = sameFileAlreadySelected
    ? Promise.resolve(null)
    : page.waitForResponse(
        (r) => SUMMARY_RE.test(r.url()) && r.request().method() === 'GET' && r.status() === 200,
        { timeout: 20_000 },
      )
  await option.click()
  const resp = await responseArrived

  if (!resp) {
    await expect(async () => { await firstCpkRow(page) }).toPass({ timeout: 30_000 })
    return
  }

  const items = ((await resp.json())?.test_item_overview ?? []) as
    Array<{ name: string; cpk: number | null }>
  expect(items.length, '/summary/ 响应必须带 test_item_overview（形状变了别继续自欺）')
    .toBeGreaterThan(0)
  const responseNames = new Set(items.map((i) => i.name))
  const responseCpkKeys = new Set(
    items.filter((i) => typeof i.cpk === 'number').map((i) => `${i.name}|${i.cpk!.toFixed(2)}`),
  )

  await expect(async () => {
    const shown = await firstCpkRow(page)
    if (!responseCpkKeys.has(`${shown.name}|${shown.cpk.toFixed(2)}`)) {
      throw new Error(`首个带 CPK 的行 ${shown.name}=${shown.row} 不在这份响应里（总览还是上一个文件）`)
    }
    const names = await page.locator('.overview-table .cell-param').allInnerTexts()
    if (names.length === 0 || names.some((n) => !responseNames.has(n.trim()))) {
      throw new Error(`渲染了 ${names.length} 行，但不是这份响应的行子集`)
    }
  }).toPass({ timeout: 30_000 })
}

/** 进仪表板 → 选文件 → 返回首个可判定行（reload 后必须再来一次：选中文件会被重置）。 */
async function openDashboardWithCpk(page: Page) {
  await gotoApp(page, '/dashboard')
  await waitLoadingGone(page)
  await pickCpkFile(page)
  return firstCpkRow(page)
}

test.describe('CPK 阈值设置', { tag: ['@settings'] }, () => {
  test('@p1 阈值抬到样本 CPK 之上：总览判 D 级，数值标签同色同步', async ({ page }) => {
    const base = await openDashboardWithCpk(page)
    const original = await readThresholds(page)
    const row = rowByName(page, base.name)
    try {
      // 不预设「默认阈值下该行是 A 级」——哪一行的 CPK 是多少取决于数据，
      // 只断言「阈值全部抬到该 CPK 之上 → 必然 D」这一条充要关系。
      await expect(row.locator('.cpk-badge--a, .cpk-badge--b, .cpk-badge--c, .cpk-badge--d').first())
        .toBeVisible()

      await putThresholds(page, {
        cpk_a_threshold: +(base.cpk + 1).toFixed(2),
        cpk_b_threshold: +(base.cpk + 2).toFixed(2),
        cpk_c_threshold: +(base.cpk + 3).toFixed(2),
      })
      await page.reload()
      const moved0 = await openDashboardWithCpk(page)
      expect(moved0.name, '重进后应仍锁定同一行').toBe(base.name)

      const moved = rowByName(page, base.name)
      await expect(moved.locator('.el-tag').first()).toHaveText(String(base.row))
      await expect(moved.locator('.cpk-badge--d'), '等级徽标应随阈值掉到 D').toBeVisible()
      // 数值标签必须与徽标同一套判定（此前它按硬编码 1.67/1.33 自评）
      await expect(moved.locator('.el-tag').first()).toHaveClass(/el-tag--danger/)
    } finally {
      if (original) await putThresholds(page, original)
    }
  })

  test('@p1 阈值压到样本 CPK 之下：仍判 A 级（反向不被接线破坏）', async ({ page }) => {
    const base = await openDashboardWithCpk(page)
    const original = await readThresholds(page)
    try {
      await putThresholds(page, {
        cpk_a_threshold: +(base.cpk / 2).toFixed(2),
        cpk_b_threshold: +(base.cpk / 4).toFixed(2),
        cpk_c_threshold: +(base.cpk / 8).toFixed(2),
      })
      await page.reload()
      await openDashboardWithCpk(page)

      const row = rowByName(page, base.name)
      await expect(row.locator('.cpk-badge--a')).toBeVisible()
      await expect(row.locator('.el-tag').first()).toHaveClass(/el-tag--success/)
    } finally {
      if (original) await putThresholds(page, original)
    }
  })

  test('@p1 低 CPK 警报文案内插用户 B 阈（不再写死 1.33）', async ({ page }) => {
    const base = await openDashboardWithCpk(page)
    const original = await readThresholds(page)
    try {
      const b = +(base.cpk + 2).toFixed(2)
      await putThresholds(page, {
        cpk_a_threshold: +(b + 1).toFixed(2),
        cpk_b_threshold: b,
        cpk_c_threshold: +(b - 1).toFixed(2),
      })
      await page.reload()
      await openDashboardWithCpk(page)

      const banner = page.locator('[data-testid="alert-banner"]')
      await expect(banner, '阈值抬到 CPK 之上后应出现低 CPK 警报').toBeVisible()
      // 横幅默认折叠成一行汇总（AlertBanner open=false）→ 明细文案要先展开才在 DOM 里
      await banner.locator('.banner-head').click()
      const alert = page.getByText(/个参数CPK不足/)
      await expect(alert).toBeVisible()
      // 文案里的判定线必须是用户设的 B 阈（后端用 {:g} 格式化，与 JS 数字字面量同形）
      await expect(alert).toContainText(`CPK < ${b}`)
    } finally {
      if (original) await putThresholds(page, original)
    }
  })
})
