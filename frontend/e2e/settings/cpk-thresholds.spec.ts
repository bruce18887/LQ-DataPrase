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

/** 选中带限值参数的种子文件，并等到总览真出现可判定的 CPK 行。 */
async function pickCpkFile(page: Page) {
  const keyword = SEEDED_FILES.CTA8280F_FT.slice(0, 12)
  const select = page.locator('.dash-file-select')
  await select.click()
  await select.locator('input').fill(keyword)
  await page.locator('.dp-file-select-dropdown .el-select-dropdown__item')
    .filter({ hasText: keyword }).first().click()
  await expect(async () => { await firstCpkRow(page) }).toPass({ timeout: 30_000 })
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
