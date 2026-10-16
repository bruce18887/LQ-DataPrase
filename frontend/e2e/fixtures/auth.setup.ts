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
 * 为什么必须在开跑前钉：账号设置**跨轮持久**。2026-10-13 在 e2e 库（当时是仓库根那份，
 * 现在落 `test/e2e-data/db.sqlite3`；都不是 `~/LQ-DataPrase` 那个人用的库）实测到 admin 停在
 * filename_wrap=False、page_size=200、cpk_a/b/c=3.0/2.99/2.98、analysis_chart_memory=False，
 * 而写它们的地方都没有失败兜底：
 * - `data/file-list-sort-filter.spec.ts:276` 先 PUT false，`:293` 才 PUT true —— 用例在两步之间
 *   失败就永久留下 false，于是**它自己把下一轮的自己弄红**（`.batch-filename-wrap` 不渲染，
 *   `combine.spec` 跟着红）；
 * - 阈值类用例的还原写成 `if (original) put(original)`，读不到快照时直接跳过。
 *
 * 这是**兜底不是替代**：每条 mutate 账号设置的用例仍该自己 finally 还原（`settings.spec.ts` 的
 * DPI 与「恢复默认」本轮已补上）。规范集只列实测漏过的字段，刻意不含 recent_files /
 * sftp_last_* 这类用户历史 —— 没有用例依赖它们，洗掉反而会踩掉并行会话真实配下的 SFTP 主机。
 *
 * `analysis_chart_state` 原先也被当作"用户历史"排除，2026-10-13 夜实测**这个判断是错的**：
 * 库里 admin 停在 `toggles={hist,serial,qq,box 全 true}`，于是
 * ① `legend-color:27` 的 `.chart-wrapper div[_echarts_instance_]` strict mode 命中 **3** 个实例
 *    （直方图 + QQ + 箱线图）直接红；② `analysis_chart_memory=true` 会把开关写回账号，
 *    `serial-adaptive-range` 点成"开"之后，`serial-overlap` 里**逐字相同**的 `enterSerial`
 *    同一次点击变成"关" → 不发 `serial_distribution` POST → 30s 超时。
 * 钉成模型默认 `{}` 即中性态：`SingleParamTab.vue:451` 在 `state.toggles` 缺失时不套用记忆，
 * 组件自身的默认是 hist=true / serial=qq=box=false（`:286/:292/:375/:403`）。
 *
 * ⚠ 这只保证**开跑那一刻**的起点，**不解决**同一轮内的相互污染：`analysis_chart_memory`
 * 默认 true，任何用例翻动开关都会立刻写回账号。2026-10-13 全量实测证明这一点——钉了默认值
 * 之后仍有 5 条用例红，撤掉钉默认值它们照样红，**根因不在起点而在用例自己假定状态**
 * （标签是固定文案，`click()` 是「翻」不是「开」）。正解是用
 * `helpers/params.ts` 的 `ensureChartToggles` / `enableChartAndWait` 自己收敛，
 * 不要依赖这里的默认值。
 */
const CANONICAL_SETTINGS = {
  filename_wrap: true,
  page_size: 100,
  cpk_a_threshold: 1.67,
  cpk_b_threshold: 1.33,
  cpk_c_threshold: 1.0,
  analysis_chart_memory: true,
  analysis_chart_state: {},
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
