import { test as setup, expect } from '@playwright/test'
import fs from 'node:fs'
import { ACCOUNTS, ADMIN_STATE, USER_STATE, AUTH_DIR, type Role } from './test-data'
import { uiLogin } from '../helpers/auth'

/**
 * 登录态准备（在所有业务用例之前运行一次）。
 *
 * 通过真实 UI 登录获取 JWT，并把 localStorage(token) 导出为 storageState，
 * 供后续“仅需登录”的功能用例直接复用，避免每条用例重复登录。
 *
 * 注意：App 启动不会重新拉取用户 profile（见 tasks/todo.md），
 * storageState 仅恢复 token，不恢复角色。角色相关用例请用 loginAs() 实时登录。
 */
setup.beforeAll(() => {
  fs.mkdirSync(AUTH_DIR, { recursive: true })
})

async function persist(role: Role, statePath: string, page: import('@playwright/test').Page) {
  await uiLogin(page, ACCOUNTS[role].username, ACCOUNTS[role].password)
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 })
  await canonicalize(page)
  await page.context().storageState({ path: statePath })
}

/**
 * e2e 的规范账号态：把「有用例会改、且改了不一定还得回来」的字段在开跑前钉回模型默认值。
 *
 * 为什么必须在开跑前钉：账号设置**跨轮持久**。2026-10-13 在 e2e 库（`data_dir` = 项目根那份，
 * 不是 `~/LQ-DataPrase` 那个人用的库）实测到 admin 停在
 * filename_wrap=False、page_size=200、cpk_a/b/c=3.0/2.99/2.98、analysis_chart_memory=False，
 * 而写它们的地方都没有失败兜底：
 * - `data/file-list-sort-filter.spec.ts:276` 先 PUT false，`:293` 才 PUT true —— 用例在两步之间
 *   失败就永久留下 false，于是**它自己把下一轮的自己弄红**（`.batch-filename-wrap` 不渲染，
 *   `combine.spec` 跟着红）；
 * - 阈值类用例的还原写成 `if (original) put(original)`，读不到快照时直接跳过。
 *
 * 这是**兜底不是替代**：每条 mutate 账号设置的用例仍该自己 finally 还原（`settings.spec.ts` 的
 * DPI 与「恢复默认」本轮已补上）。规范集只列实测漏过的字段，刻意不含 recent_files /
 * analysis_chart_state / sftp_last_* 这类用户历史 —— 没有用例依赖它们，把它们洗掉反而会把
 * 「恢复默认」那条用例的语义测窄，也会踩掉并行会话真实配下的 SFTP 主机。
 */
const CANONICAL_SETTINGS = {
  filename_wrap: true,
  page_size: 100,
  cpk_a_threshold: 1.67,
  cpk_b_threshold: 1.33,
  cpk_c_threshold: 1.0,
  analysis_chart_memory: true,
}

async function canonicalize(page: import('@playwright/test').Page) {
  const status = await page.evaluate(async (body) => {
    const resp = await fetch('/api/v1/auth/settings/', {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('access_token')}`,
      },
      body: JSON.stringify(body),
    })
    return resp.status
  }, CANONICAL_SETTINGS)
  // 失败要出声：规范态没写进去 = 这一轮的绿灯/红灯都不可解释
  expect(status, `PUT 规范账号态应成功（实际 ${status}）`).toBe(200)
}

setup('authenticate as admin', async ({ page }) => {
  await persist('admin', ADMIN_STATE, page)
})

setup('authenticate as user', async ({ page }) => {
  await persist('user', USER_STATE, page)
})
