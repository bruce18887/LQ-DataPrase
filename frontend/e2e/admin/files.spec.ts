import { test, expect, type APIRequestContext } from '@playwright/test'
import { loginAs } from '../helpers/auth'
import { sidebarLink } from '../helpers/nav'

/**
 * 管理员跨用户只读文件页（/admin/files）。
 *
 * 只在这里留「接线证明」：契约本身（``?owner_id=`` 只放开 list、普通用户 403、
 * ``/admin/files/users/`` 的形状与 usage 三段）由 T1 的
 * ``test/backend/test_admin_files_api.py`` 逐条钉着。testing-gates §2 的冲突裁决
 * 要求同一判据 T1/T3 都能表达时 T1 写全组合、浏览器只留一条走得通的路 —— 所以
 * 本文件证的是三件浏览器外不可判的事：
 *  ① 侧栏「全部文件」→ 选用户 → 那一行确实来自 ``/files/?owner_id=<选中的 id>``；
 *  ② 这一页没有查看/下载/删除/编辑按钮（只读承诺的界面侧）；
 *  ③ 普通用户既看不到入口，直达 ``/admin/files`` 也被守卫送回 /dashboard。
 *
 * 清空注入的 storageState、用 loginAs 实时登录：requiresAdmin 守卫与侧栏过滤读的
 * 都是 Pinia 里的 user/isAdmin，硬刷新一次就拿不到了（同 admin.spec.ts 文件头）。
 */
test.describe('全部文件 / 管理员跨用户只读', { tag: ['@admin'] }, () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  /**
   * 以种子账号 user 身份上传一个只属于它的临时 CSV，返回 id 与 token（清理用）。
   *
   * 为什么必须造一行真数据：种子的 11 份 SampleData 全归 admin，直接选 admin 也是
   * 「有行」——但那样「把 owner_id 写成当前登录人」这种错实现照样全绿，而本页的全部
   * 意义就是跨用户。合成 CSV 只为拿到一行文件名唯一的记录（解析成 Unknown 也没关系：
   * ``/files/`` 的清单不按 status 过滤），不上传大夹具。
   */
  async function uploadAsUser(ctx: APIRequestContext, fileName: string) {
    const login = await ctx.post('/api/v1/auth/login/', {
      data: { username: 'user', password: 'user123' },
      failOnStatusCode: false,
    })
    expect(login.ok(), `user 登录失败：${await login.text()}`).toBe(true)
    const { token } = (await login.json()) as { token: string }
    const resp = await ctx.post('/api/v1/upload/', {
      headers: { Authorization: `Bearer ${token}` },
      multipart: {
        files: {
          name: fileName,
          mimeType: 'text/csv',
          buffer: Buffer.from('TestFile,Result\nPAR0001,1\n'),
        },
      },
      failOnStatusCode: false,
    })
    expect(resp.status(), await resp.text()).toBe(201)
    const created = (await resp.json()) as Array<{ id: number }>
    return { id: created[0].id, token }
  }

  test('@p1 管理员：从侧栏选用户后列出其文件，页面没有查看/下载/删除/编辑按钮', async ({
    page,
    browser,
  }) => {
    const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } })
    const fileName = `e2e_adminfiles_${Date.now()}.csv`
    let uploaded: { id: number; token: string } | null = null
    try {
      uploaded = await uploadAsUser(ctx.request, fileName)
      await loginAs(page, 'admin')

      // 用户清单由页面挂载时自己发；waitForResponse 必须先于触发动作注册（lessons R2）。
      const [usersResp] = await Promise.all([
        page.waitForResponse(
          (r) => r.url().includes('/admin/files/users/') && r.request().method() === 'GET',
          { timeout: 20_000 },
        ),
        sidebarLink(page, '全部文件').click(),
      ])
      expect(usersResp.status(), await usersResp.text()).toBe(200)
      await expect(page).toHaveURL(/\/admin\/files/)
      const usersBody = (await usersResp.json()) as {
        results: Array<{ id: number; username: string }>
      }
      const target = usersBody.results.find((u) => u.username === 'user')
      expect(target, '用户清单里没有种子账号 user').toBeTruthy()

      // 未选用户 ≠ 该用户没文件：两种空态必须有区别，否则管理员读不出「还没选」。
      const table = page.locator('.admin-files-table')
      await expect(table.getByText('请先选择一个用户')).toBeVisible()

      // filterable 下拉点外层 .el-select：非 filterable 时里面的 input 被排出文档流，
      // hit-test 命不中（audit.spec.ts 文件头同款实测）。
      await page.locator('[data-testid="admin-files-user"] .el-select').click()
      const popper = page.locator('.el-popper[aria-hidden="false"] .el-select-dropdown')
      await expect(popper, '同时有两个开着的下拉 ⇒ 这一眼挑不出是谁').toHaveCount(1)
      const [listResp] = await Promise.all([
        page.waitForResponse(
          (r) =>
            r.url().includes('/api/v1/files/') &&
            r.request().method() === 'GET' &&
            r.url().includes('owner_id='),
          { timeout: 20_000 },
        ),
        popper
          .locator('.el-select-dropdown__item')
          .filter({ hasText: 'user（普通用户）' })
          .click(),
      ])
      expect(listResp.status(), await listResp.text()).toBe(200)
      expect(
        decodeURIComponent(listResp.request().url()),
        '选中的用户没进 owner_id（写死当前登录人时这里会红）',
      ).toContain(`owner_id=${target!.id}`)

      const rows = table.locator('tbody tr')
      await expect(rows.filter({ hasText: fileName }).first()).toBeVisible({ timeout: 15_000 })

      // 三颗 KPI 的标签与「一个数」的形状（usage 为 null 时 usageBytesText 给 '--'）。
      const kpis = page.locator('.admin-files-kpis')
      for (const label of ['数据体积', '作业产物体积', '总占用']) {
        await expect(kpis).toContainText(label)
      }
      await expect(page.locator('[data-testid="admin-files-total-bytes"]')).toHaveText(/^(\d|--)/)

      // 只读承诺：整页无写操作/详情入口，行内也没有 action 列。
      for (const name of ['查看', '下载', '删除', '编辑']) {
        await expect(
          page.getByRole('button', { name, exact: true }),
          `页面上出现了「${name}」按钮`,
        ).toHaveCount(0)
      }
      await expect(rows.first().locator('button')).toHaveCount(0)
    } finally {
      if (uploaded) {
        await ctx.request.delete(`/api/v1/files/${uploaded.id}/`, {
          headers: { Authorization: `Bearer ${uploaded.token}` },
          failOnStatusCode: false,
        })
      }
      await ctx.close()
    }
  })

  test('@p1 普通用户：侧栏无「全部文件」，直达被守卫送回仪表板', async ({ page }) => {
    await loginAs(page, 'user')
    // 侧栏按 v-if 过滤 ⇒ 链接不在 DOM 里，toBeHidden 对「不存在」成立（admin.spec.ts 同形）。
    await expect(sidebarLink(page, '全部文件')).toBeHidden()

    await page.goto('/admin/files')
    // 断守卫跑完后的最终 URL：守卫里还有一次 fetchProfile 往返（admin.spec.ts 文件头）。
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 })
    await expect(page.locator('.main-layout')).toBeVisible()
  })
})
