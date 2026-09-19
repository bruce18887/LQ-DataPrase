import { test, expect, type Page } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { SEEDED_FILES } from '../fixtures/test-data'

/**
 * 默认每页行数（系统设置 → 📋 表格设置）→「查看数据」表格的服务端分页块大小。
 *
 * 回归：该项曾「存了没人读」——DataBrowserAgGrid 的 IRM 块大小恒为常量 100。
 * 设置走 API PUT 而非 UI：绕开设置页，直接验「存的值 → 真发出去的请求」这条链路。
 *
 * 收尾必须写回**原值**而非硬编码默认：admin storageState 是共享账号，写死 100
 * 会把别人账号里的设置改掉（见 lessons 2026-09-19）。
 */

async function readPageSize(page: Page): Promise<number | null> {
  return page.evaluate(async () => {
    const resp = await fetch('/api/v1/auth/settings/', {
      headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` },
    })
    const data = await resp.json()
    return typeof data?.page_size === 'number' ? data.page_size : null
  })
}

async function putPageSize(page: Page, value: number) {
  const status = await page.evaluate(async (v) => {
    const resp = await fetch('/api/v1/auth/settings/', {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('access_token')}`,
      },
      body: JSON.stringify({ page_size: v }),
    })
    return resp.status
  }, value)
  expect(status, `PUT page_size=${value}`).toBe(200)
}

/** 文件列表服务端搜索定位 → 点「查看」进「查看数据」tab。 */
async function openViewTab(page: Page, filename: string) {
  await gotoApp(page, '/data')
  const searchInput = page.locator('input[placeholder="按文件名/程序名/标签搜索"]')
  await searchInput.fill(filename.slice(0, 15))
  const row = page
    .locator('.el-table .el-table__row')
    .filter({ hasText: filename.slice(0, 12) })
    .first()
  await expect(row).toBeVisible({ timeout: 30_000 })
  await row.locator('button').filter({ hasText: '查看' }).click()
  await expect(page.locator('.ag-root').first()).toBeVisible({ timeout: 30_000 })
}

test.describe('每页行数设置', { tag: ['@settings'] }, () => {
  test('@p1 账号设为 200：「查看数据」分页请求块大小跟随，且 ag-grid 与页码算式一致', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    const original = await readPageSize(page)
    try {
      await putPageSize(page, 200)

      // 监听必须装在触发动作之前（lessons R2④：goto 后再注册有几百 ms 漏窗）
      const firstBrowse = page.waitForRequest(
        (req) => /\/api\/v1\/browse\//.test(req.url()) && req.method() === 'GET',
      )
      await openViewTab(page, SEEDED_FILES.CTA8280F_FT)

      const url = new URL((await firstBrowse).url())
      expect(url.searchParams.get('page_size'), '块大小应跟随设置').toBe('200')
      expect(url.searchParams.get('page')).toBe('1')

      // 第二块必须落在校正的页码上：前端用 floor(startRow / 设置值) 反推页码，
      // 若 ag-grid 自己的 cacheBlockSize 没跟着改成 200（仍按 100 前进 startRow），
      // 第二次请求会是 page=1 → 下面等 page=2 超时。这条断言同时守住「两端一致」。
      const secondBrowse = page.waitForRequest(
        (req) => /\/api\/v1\/browse\//.test(req.url())
          && new URL(req.url()).searchParams.get('page') === '2',
        { timeout: 30_000 },
      )
      // 垂直滚动驱动 .ag-body-vertical-scroll-viewport（本仓既有用例的既有做法，如
      // view-data.spec.ts 的 ensureRowRendered）：实测给它赋 scrollTop 能触发 IRM 续块请求，
      // 而给 .ag-center-cols-viewport 赋 scrollTop 等不到第二次请求（机制未查证，见 e2e/README）。
      // 滚到第 220 行（30px/行）= 落在 200 行块的第二块里，而不是滚到底翻到最后一页。
      await page.locator('.ag-body-vertical-scroll-viewport')
        .evaluate((el) => { el.scrollTop = 220 * 30 })

      const url2 = new URL((await secondBrowse).url())
      expect(url2.searchParams.get('page_size'), '续取块大小也必须跟随设置').toBe('200')
    } finally {
      await putPageSize(page, original ?? 100)
    }
  })

  test('@p1 默认 100 不被接线破坏：账号为 100 时 browse 请求仍是 100', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    const original = await readPageSize(page)
    try {
      await putPageSize(page, 100)
      const firstBrowse = page.waitForRequest(
        (req) => /\/api\/v1\/browse\//.test(req.url()) && req.method() === 'GET',
      )
      await openViewTab(page, SEEDED_FILES.CTA8280F_FT)

      const url = new URL((await firstBrowse).url())
      expect(url.searchParams.get('page_size')).toBe('100')
    } finally {
      await putPageSize(page, original ?? 100)
    }
  })
})
