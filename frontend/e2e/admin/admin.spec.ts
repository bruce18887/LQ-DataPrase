import { test, expect, type Page, type Locator, type Request } from '@playwright/test'
import { collectAllPages } from '../../src/utils/paging'
import { loginAs } from '../helpers/auth'
import { sidebarLink } from '../helpers/nav'

/**
 * 本 worker 创建过的用户名登记表。
 *
 * 为什么需要它：playwright.config.ts 是 fullyParallel: true + workers=min(6, cpus/2)，
 * 本文件的用例会散到多个 worker 进程，而 **afterAll 每个 worker 各执行一次**——
 * 谁都不能替别人清场，只能各自回收自己建的账号（详见 afterAll 上方那段规则）。
 * 登记一律发生在创建**之前**：POST/「添加」点击半路失败时账号可能已经在后端落库，
 * 先记名才保证它归本 worker 的 afterAll 收。
 */
const mine = new Set<string>()

/**
 * 「残留」判据的年龄地板：建号满 10 分钟才算尸体。afterAll 里按 `Date.now()` 现算，
 * 不用「本 worker 加载本模块的时刻」—— 那样会误删兄弟 worker 正在用的活账号，
 * 机制与实测复现见 afterAll 上方规则 (c)。
 */
const RESIDUE_MIN_AGE_MS = 10 * 60_000

/**
 * 添加用户表单字段定位：el-form-item 的 label 在本应用不可靠地关联为可访问名
 * （沿用 sftp.spec.ts 的既有约定），故按 .el-form-item__label 文本过滤后取内部 input。
 * 限定在 .user-management 的 el-form 内，避免与表格列头「用户名」歧义。
 */
function addUserField(page: Page, label: string): Locator {
  return page
    .locator('.user-management .el-form .el-form-item')
    .filter({ has: page.locator('.el-form-item__label', { hasText: label }) })
    .locator('input')
    .first()
}

/**
 * 用户管理（/admin/users）端到端用例。
 *
 * 角色相关：应用启动/刷新不会用 token 重新拉取 profile，
 * 故 user/isAdmin 仅在“同会话内实时 UI 登录”后有效。
 * 因此本文件整体清空 storageState，统一用 loginAs(page, role) 实时登录，
 * 并尽量用侧边栏点击（不刷新页面）保持 Pinia user 存活。
 *
 * 路由实情（src/router/index.ts beforeEach，2026-11-10 实测确认）：
 *   beforeEach 依次判 requiresAuth、/login 回访、requiresAdmin；普通用户直达
 *   /admin/users 会被 next('/dashboard') 送回仪表板（纵深防御，后端 403 是第一道）。
 *   侧栏按 v-if 过滤管理员项 ⇒ 不在 DOM 里，不是 .hidden(display:none)。
 *   断言一律取守卫跑完后的最终 URL：守卫含一次 fetchProfile 往返，
 *   抢在它之前断 goto 的目标地址会假绿（2026-11-09/10 踩实两次，见计划 Task 12）。
 */
test.describe('用户管理 / 权限', { tag: ['@admin'] }, () => {
  // 清空注入的 storageState，强制走实时 UI 登录使 user/isAdmin 生效
  test.use({ storageState: { cookies: [], origins: [] } })

  // 清理判据（两条任一成立即删）：
  //  (a) 用户名在 `mine` 里 ⇒ 本 worker 自己建的，无条件回收。afterAll 是**每个 worker 各跑
  //      一次**（fullyParallel: true、workers = min(6, cpus/2)，playwright.config.ts:63,69），
  //      谁都不能替别人清场，所以每个人只认自己登记过的那几个名字。
  //  (b) 用户名命中四个 e2e_ 前缀之一 **且** 建号已满 RESIDUE_MIN_AGE_MS（10 分钟）⇒ 上一轮
  //      跑残的尸体（用例中途断言失败 → 末尾那句 UI 删除不执行，账号就一直跨轮留着，所以这道
  //      按前缀的兜底不能删）。前缀 ↔ 建号用例：e2e_user_ 新增并删除用户、e2e_toggle_ 禁用/
  //      启用、e2e_edit_ 编辑弹窗、e2e_reset_ 重置密码。
  //      兜底只能落在这里，因为**没有任何东西在跑测前清用户账号**：
  //      e2e/global-setup.ts:43-52 的非 slot 分支只跑 migrate / seed_users /
  //      seed_test_data --refresh，slot 模式整段跳过（同文件 :38-42）；而 seed_test_data
  //      --refresh 那句「清理 e2e_* 测试残留」删的是 DataFile 行和磁盘上的 e2e_* 文件
  //      （apps/accounts/management/commands/seed_test_data.py:136-153），不碰 User 表；
  //      seed_users 只对种子账号 get_or_create，不删任何东西。
  //  (c) 为什么 (b) 的闸是「距此刻的年龄」而不是「本 worker 的启动时刻」：模块级时间戳在每
  //      个 worker 里各求值一次（重试还会重新加载），晚起的 worker 一定看到兄弟 worker 几秒
  //      前刚建的**活账号**比自己早 ⇒ 判成残留删掉。2026-11-10 复现到的形状：全文件 4 次里
  //      2 次「8 passed + 1 flaky」，flaky 固定是编辑弹窗那条，首跑卡在下面等「已删除」那一行
  //      （:349）而行还在快照里 —— 服务端那次 DELETE 压根没执行，账号已被另一个 worker 的
  //      afterAll 扫走。年龄按 now 算，兄弟 worker 刚建的号只有几分钟大，过不了 10 分钟的闸。
  //  (d) 这道地板的可靠性要分两半看：`mine` 那半是**空气密的**（本 worker 自己记的名字，与年龄
  //      无关），10 分钟那半是**按实测下的注**，不是不变式。能被 (b) 扫到的活账号只可能是本轮刚
  //      建的，而它到 afterAll 那一刻的年龄上限是**整个文件的墙钟**（不是单条用例的 timeout ——
  //      60_000 × 2 次尝试 = 2 分钟那个数只约束一条用例，管不着「建号」与「扫场」隔了多久）。
  //      2026-11-10 实测本文件连跑 5 轮（7 条用例 + setup 那 2 条 = 每轮 9 个结果）各 26.5–27.1s，
  //      离 10 分钟差两个量级。注若失效（用例变多、后端严重劣化，文件墙钟涨过 10 分钟），症状就是
  //      (c) 已写清的那种 flaky：扫走一个兄弟 worker 正在用的**临时 e2e_ 账号**，不是用户数据。
  //      真到那天的修法是把地板抬到超过最坏文件墙钟，而不是去补 (c) 那条症状。
  test.afterAll(async ({ browser }) => {
    const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } })
    try {
      const login = await ctx.request.post('/api/v1/auth/login/', {
        data: { username: 'admin', password: 'admin123' },
      })
      if (!login.ok()) return
      const { token } = await login.json()
      const headers = { Authorization: `Bearer ${token}` }
      // 跟着 next 取全：UserManagementViewSet 没覆写 pagination_class，DRF 默认
      // PAGE_SIZE=20（config/settings/base.py:214-215），只读第一页的话，第 21 个
      // 账号起既扫不到残留、也扫不到 `mine` 里自己那条 ⇒ 清理保证直接失效。
      // 「跟着 next 走完全表」还要求后端给全表一个稳定次序，否则跨页可重复/漏行：
      // 那由 UserManagementViewSet.queryset 的 .order_by('id') 保证（2026-11-10 补，
      // 判据 test/backend/test_user_list_pagination.py）。
      const { rows: users } = await collectAllPages<{ id: number; username: string; date_joined: string }>(
        async (url) => (await ctx.request.get(url, { headers, failOnStatusCode: false })).json(),
        '/api/v1/auth/users/',
      )
      for (const u of users) {
        // 前缀 ↔ 用例的对应、以及为什么年龄闸按 now 而不是按 worker 启动时刻，
        // 见本 describe 顶部规则 (b)(c)。`u.username` 不加 `?? ''`：上面那个行类型把它
        // 声明成非空 string，后端侧它是 NOT NULL 的 CharField，序列化器恒给出字符串。
        const residue =
          /^e2e_(user|toggle|edit|reset)_/.test(u.username) &&
          Date.now() - new Date(u.date_joined).getTime() > RESIDUE_MIN_AGE_MS
        if (mine.has(u.username) || residue) {
          await ctx.request.delete(`/api/v1/auth/users/${u.id}/`, { headers, failOnStatusCode: false })
        }
      }
    } catch {
      // 清理失败静默（残留由下一轮兜底再清）
    } finally {
      await ctx.close()
    }
  })

  test('@p1 普通用户：侧边栏无“用户管理”入口，直达被守卫送回仪表板', async ({ page }) => {
    await loginAs(page, 'user')

    // Sidebar.vue 走 v-if 过滤 ⇒ 管理员项不在 DOM 里，toBeHidden 对「不存在」成立。
    await expect(sidebarLink(page, '用户管理')).toBeHidden()

    await page.goto('/admin/users')
    // 断最终落点而不是 goto 之后那一瞬的 URL：守卫里有一次 fetchProfile 往返，
    // 抢在它前面断目标地址会假绿（文件头「路由实情」记的就是这条坑，2026-11-10 踩实）。
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 })
    await expect(page.locator('.main-layout')).toBeVisible()
  })

  test('@p1 管理员：经侧边栏进入 /admin/users，用户表格渲染并含 admin', async ({ page }) => {
    await loginAs(page, 'admin')

    // 通过侧边栏点击进入（不刷新，保持实时登录的 user/isAdmin）
    const link = sidebarLink(page, '用户管理')
    await expect(link).toBeVisible()
    await link.click()
    await expect(page).toHaveURL(/\/admin\/users/)

    // 表格渲染：UserManagement.vue 使用 <el-table :data="users"> → .el-table
    const table = page.locator('.el-table')
    await expect(table).toBeVisible()

    // 已知种子账号 admin 应出现在“用户名”列
    await expect(table.getByText('admin', { exact: true })).toBeVisible({ timeout: 15_000 })
  })

  /**
   * 2026-09-20 回归：管理员禁用/删除自己会把自己永久锁在门外——登录端点对
   * 停用账号直接 403、SimpleJWT 立刻吊销 token，只能直连数据库恢复。
   * 前端把本行的「禁用」「删除」置灰（后端 _guard_lockout 是权威守卫）。
   */
  test('@p1 管理员本行的「禁用」「删除」按钮置灰，不能操作自己', async ({ page }) => {
    await loginAs(page, 'admin')
    await sidebarLink(page, '用户管理').click()
    await expect(page).toHaveURL(/\/admin\/users/)

    const table = page.locator('.el-table')
    await expect(table).toBeVisible()

    // 自己的行：按用户名单元格精确文本过滤。不用 hasText 子串匹配，
    // 免得将来出现名字含 "admin" 的账号时命中两行。
    const selfRow = table
      .locator('tbody tr')
      .filter({ has: page.getByText('admin', { exact: true }) })
    await expect(selfRow).toHaveCount(1)

    await expect(selfRow.getByRole('button', { name: '禁用', exact: true })).toBeDisabled()
    await expect(selfRow.getByRole('button', { name: '删除', exact: true })).toBeDisabled()

    // 防过度修复：「重置密码」不造成锁死，必须仍可点。
    await expect(
      selfRow.getByRole('button', { name: '重置密码', exact: true }),
    ).toBeEnabled()
  })

  test('@p2 新增并删除用户：唯一用户 → 出现 → 删除（确认框）→ 消失', async ({ page }) => {
    await loginAs(page, 'admin')

    // 经侧边栏进入，保持 admin 实时身份
    await sidebarLink(page, '用户管理').click()
    await expect(page).toHaveURL(/\/admin\/users/)

    const table = page.locator('.el-table')
    await expect(table).toBeVisible()

    // 唯一的一次性用户名，避免污染种子账号（admin/user）
    const uniqueName = `e2e_user_${Date.now()}`
    mine.add(uniqueName) // 先记名再建号：「添加」点击半路失败时账号也可能已经落库，本 worker 的 afterAll 才认它（e2e_user_ 如今也在残留表里，但那是满 10 分钟之后的跨轮兜底）

    // 添加表单（UserManagement.vue「➕ 添加用户」区块，inline el-form）：
    //   用户名 el-input / 密码 el-input(type=password) / 角色 el-select / 「添加」按钮(submit)
    await addUserField(page, '用户名').fill(uniqueName)
    await addUserField(page, '密码').fill('e2ePass123')
    // 角色默认 user，无需更改。提交。
    await page.getByRole('button', { name: '添加', exact: true }).click()

    // 添加成功提示 + 表格刷新后出现该用户
    await expect(page.getByText('用户已添加')).toBeVisible({ timeout: 15_000 })
    const newRow = table.locator('tr').filter({ hasText: uniqueName })
    await expect(newRow.getByText(uniqueName, { exact: true })).toBeVisible({ timeout: 15_000 })

    // 删除：该行内「删除」按钮（type=danger）
    await newRow.getByRole('button', { name: '删除', exact: true }).click()

    // 确认框 teleport 到 body：ElMessageBox.confirm(`确定删除用户 ${name}？`, '确认')
    // 未配置 zh locale 时默认确认按钮文本可能是 OK 而非「确定」，故点击主按钮更稳。
    const dialog = page.locator('.el-message-box')
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText(`确定删除用户 ${uniqueName}`)
    await dialog.locator('.el-message-box__btns .el-button--primary').click()

    // 删除成功提示 + 表格刷新后该用户消失
    await expect(page.getByText('已删除')).toBeVisible({ timeout: 15_000 })
    await expect(table.getByText(uniqueName, { exact: true })).toHaveCount(0, { timeout: 15_000 })
  })

  /**
   * 2026-06-07 回归：PUT /auth/users/<id>/ {is_active:false} 之前 400，
   * 因为 DRF 默认 ModelViewSet.update() 不传 partial=True。
   * 修复在 UserManagementViewSet.update() 中强制 partial=True。
   * 该用例负责：点击「禁用」按钮 → 后端 200 → 状态文案变 `disabled` → 再次点击 → `active`。
   * 状态列显示的是 statusLabel 原始值（不是中文映射），断言按此写成 `disabled`/`active`。
   */
  test('@p2 禁用 / 启用用户：单字段 PUT 200 后状态文案切换', async ({ page }) => {
    await loginAs(page, 'admin')
    await sidebarLink(page, '用户管理').click()
    await expect(page).toHaveURL(/\/admin\/users/)

    const table = page.locator('.el-table')
    await expect(table).toBeVisible()

    const uniqueName = `e2e_toggle_${Date.now()}`
    mine.add(uniqueName) // 先记名再建号：「添加」点击半路失败时账号也可能已经落库，仍归本 worker 的 afterAll 收
    await addUserField(page, '用户名').fill(uniqueName)
    await addUserField(page, '密码').fill('e2ePass123')
    await page.getByRole('button', { name: '添加', exact: true }).click()
    await expect(page.getByText('用户已添加')).toBeVisible({ timeout: 15_000 })

    const row = table.locator('tr').filter({ hasText: uniqueName })
    await expect(row).toBeVisible({ timeout: 15_000 })

    // 1) 禁用：点该行的「禁用」按钮 → 后端 200 → 状态变 disabled
    // （状态列文案 = statusLabel 的原始值 disabled/locked/active，非中文映射）
    const toggleBtn = row.getByRole('button', { name: '禁用', exact: true })
    await expect(toggleBtn).toBeVisible()
    await toggleBtn.click()
    await expect(page.getByText('状态已更新')).toBeVisible({ timeout: 15_000 })
    // 表格刷新后状态文案变 disabled，按钮文案变 启用
    await expect(row.getByText('disabled', { exact: true })).toBeVisible({ timeout: 15_000 })
    await expect(row.getByRole('button', { name: '启用', exact: true })).toBeVisible()

    // 2) 启用：点「启用」按钮 → 状态回到 active
    await row.getByRole('button', { name: '启用', exact: true }).click()
    await expect(page.getByText('状态已更新')).toBeVisible({ timeout: 15_000 })
    await expect(row.getByText('active', { exact: true })).toBeVisible({ timeout: 15_000 })
    await expect(row.getByRole('button', { name: '禁用', exact: true })).toBeVisible()

    // 清理：删除该用户
    await row.getByRole('button', { name: '删除', exact: true }).click()
    const dialog = page.locator('.el-message-box')
    await expect(dialog).toBeVisible()
    await dialog.locator('.el-message-box__btns .el-button--primary').click()
    await expect(page.getByText('已删除')).toBeVisible({ timeout: 15_000 })
  })

  test('@p1 编辑弹窗：改显示名与角色后列表即时收敛，用户名不可改', async ({ page }) => {
    // 这条钉的是「API 有、页面没有」的缺口：PUT /auth/users/<id>/ 早就支持
    // display_name/role，但管理页只有禁用/重置/删除，改名字只能直连接口。
    const username = `e2e_edit_${Date.now()}`
    mine.add(username) // 先记名再建号：「添加」点击半路失败时账号也可能已经落库，仍归本 worker 的 afterAll 收
    await loginAs(page, 'admin')
    await sidebarLink(page, '用户管理').click()
    await expect(page).toHaveURL(/\/admin\/users/)

    await addUserField(page, '用户名').fill(username)
    await addUserField(page, '密码').fill('e2ePass123')
    await page.getByRole('button', { name: '添加', exact: true }).click()
    await expect(page.getByText('用户已添加')).toBeVisible({ timeout: 15_000 })

    const row = page
      .locator('.el-table tbody tr')
      .filter({ has: page.getByText(username, { exact: true }) })
    await expect(row).toHaveCount(1)

    await row.getByRole('button', { name: '编辑', exact: true }).click()
    const dialog = page.locator('.user-edit-dialog')
    await expect(dialog).toBeVisible()

    // 用户名只读：input 必须 disabled，否则等于给管理员一条改名通路（登录身份会变）
    await expect(dialog.locator('[data-testid="edit-username"] input')).toBeDisabled()
    // 只读不等于填对：绑错字段（如 display_name）时 disabled 仍然成立，所以要连取值一起钉。
    await expect(dialog.locator('[data-testid="edit-username"] input')).toHaveValue(username)

    await dialog.locator('[data-testid="edit-display-name"] input').fill('改名后的名字')
    // 邮箱这道格式闸在前端（与 AccountDialog 同一条规则、同一句文案）：填错的邮箱不该绕一圈网络、
    // 由后端 400 弹回一句字段文案。这两句抓的是「规则根本没绑上」——删掉 el-form 的 :rules 或
    // el-form-item 的 prop，等不到文案 + 真的发出了 PUT，两条一起红。
    const putWhileInvalid = new Set<string>()
    const sniff = (req: Request) => {
      if (req.method() === 'PUT') putWhileInvalid.add(req.url())
    }
    page.on('request', sniff)
    await dialog.locator('[data-testid="edit-email"] input').fill('这不是邮箱')
    await dialog.getByRole('button', { name: '保存', exact: true }).click()
    await expect(dialog.getByText('邮箱格式不正确')).toBeVisible()
    page.off('request', sniff)
    expect([...putWhileInvalid], '前端校验没拦住：坏邮箱照样发了 PUT').toEqual([])
    // 邮箱要真进 PUT 请求体：不填这一格时，「从 PUT 里删掉 email」这种改动用例照样全绿。
    const email = `${username}@e2e.test`
    await dialog.locator('[data-testid="edit-email"] input').fill(email)
    // 角色下拉只该有两级（viewer 已删）。点 .el-select 而不是里面的 input，机制在 EP 源码里：
    // 非 filterable 的 select，input 的外层 wrapper 恒被挂上 is-hidden（element-plus
    // es/components/select/src/select2.mjs:196-200 的 nsSelect.is('hidden', !filterable || …)），
    // 对应样式 theme-chalk/src/select.scss:204-212 —— position:absolute / opacity:0 /
    // z-index:-1，源码注释原文「Out of the document flow」。input 既然出了文档流，
    // Playwright 的 hit-test 在它坐标上命中的永远是别的元素，点 input 不可能成功。
    // 点外层 .el-select 也是本仓既有写法（analysis.spec.ts:82、custom-limit-cpk.spec.ts:65）。
    await dialog.locator('[data-testid="edit-role"] .el-select').click()
    const options = page.locator('.el-select-dropdown__item:visible')
    await expect(options).toHaveCount(2)
    await options.filter({ hasText: /^管理员$/ }).first().click()

    const [resp] = await Promise.all([
      page.waitForResponse(
        (r) => r.url().includes(`/auth/users/`) && r.request().method() === 'PUT',
        { timeout: 20_000 },
      ),
      dialog.getByRole('button', { name: '保存', exact: true }).click(),
    ])
    expect(resp.status(), await resp.text()).toBe(200)
    await expect(page.getByText('账号已更新')).toBeVisible({ timeout: 15_000 })

    // 列表刷新后新显示名与**新角色**都出现在同一行：账号是新建的普通用户，
    // 若 saveEdit 漏发 role，这一行会写着「用户」而用例照样过 —— 所以要的是变了的那个取值。
    const edited = page.locator('.el-table tbody tr').filter({ hasText: '改名后的名字' })
    await expect(edited).toHaveCount(1)
    await expect(edited.first().locator('.role-cell')).toContainText('管理员')

    // 邮箱的回读走的是完整往返：列表数据来自 GET /auth/users/（UserSerializer 有 email），
    // openEdit 又从这一行预填 ⇒ PUT 少发 email 时这里必然是空串，而不是「页面自己记住了值」。
    await row.getByRole('button', { name: '编辑', exact: true }).click()
    await expect(dialog.locator('[data-testid="edit-email"] input')).toHaveValue(email)
    await dialog.getByRole('button', { name: '取消', exact: true }).click()
    await expect(dialog).toBeHidden()

    await row.getByRole('button', { name: '删除', exact: true }).click()
    const confirm = page.locator('.el-message-box')
    await confirm.locator('.el-message-box__btns .el-button--primary').click()
    await expect(page.getByText('已删除')).toBeVisible({ timeout: 15_000 })
  })

  test('@p1 重置密码：短密码就地拦住，≥8 位才提交并被后端接受', async ({ page, browser }) => {
    // 这条钉的是一个「按钮点了必失败」的缺陷：旧实现发硬编码 '123456'（6 位），
    // 而后端 apps/accounts/serializers.py:203-206 的 AdminResetPasswordSerializer.new_password
    // 是 min_length=8（同 Serializer 的强度校验见 :208-212）⇒ 重置密码功能从来没有成功过一次。
    // 既有覆盖只断过「按钮可点」（本文件「置灰」那条用例的 :183-186），
    // 没人真点过 —— 所以这条必须走到 POST 的响应码。
    const username = `e2e_reset_${Date.now()}`
    const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } })
    let userId: number | null = null
    try {
      const login = await ctx.request.post('/api/v1/auth/login/', {
        data: { username: 'admin', password: 'admin123' },
      })
      expect(login.ok(), '种子 admin 登录失败，无法建临时用户').toBe(true)
      const headers = { Authorization: `Bearer ${(await login.json()).token}` }
      mine.add(username) // 先记名再 POST：请求超时/断言抛错时号可能已经落库，本 worker 的 afterAll 才兜得住
      const created = await ctx.request.post('/api/v1/auth/users/', {
        headers,
        data: { username, password: 'e2e-initial-password', role: 'user' },
      })
      expect(created.ok(), `临时用户创建失败：${await created.text()}`).toBe(true)
      userId = (await created.json()).id

      await loginAs(page, 'admin')
      await sidebarLink(page, '用户管理').click()
      const row = page
        .locator('.el-table tbody tr')
        .filter({ has: page.getByText(username, { exact: true }) })
      await expect(row).toHaveCount(1)

      await row.getByRole('button', { name: '重置密码', exact: true }).click()
      const box = page.locator('.el-message-box')
      await expect(box).toBeVisible()
      const input = box.locator('.el-message-box__input input')

      // 1) 短密码：前置校验拦住，**不发请求**，提示就地出现
      await input.fill('12345')
      await box.getByRole('button', { name: '重置' }).click()
      await expect(box.locator('.el-message-box__errormsg')).toContainText('至少 8 位')
      await expect(box, '校验失败时弹窗必须还在（旧实现是直接发出去吃 400）').toBeVisible()

      // 2) ≥8 位：waitForResponse 注册在点击之前（R2①），断真实状态码
      const newPassword = 'e2e-new-password-8'
      await input.fill(newPassword)
      const [resp] = await Promise.all([
        page.waitForResponse(
          (r) => r.url().includes(`/auth/users/${userId}/reset_password/`) && r.request().method() === 'POST',
          { timeout: 20_000 },
        ),
        box.getByRole('button', { name: '重置' }).click(),
      ])
      expect(resp.status(), `≥8 位的新密码必须被接受，实际 ${resp.status()}：${await resp.text()}`).toBe(200)
      await expect(page.getByText(`已重置 ${username} 的密码`)).toBeVisible({ timeout: 15_000 })
    } finally {
      // 失败路径也不留尸体。这里的真兜底是 `mine`：这个名字在建号**之前**就登记了，本 worker 的
      // afterAll 按它无条件删（规则 (a)）。跨轮的按前缀那道（规则 (b)）在这里帮不上忙 —— 它要
      // 同时命中 `e2e_reset_` 前缀**且**建号满 10 分钟，本轮刚建的号过不了年龄闸；它防的是
      // 「worker 连 afterAll 都没跑成、`mine` 随进程一起没了」那种尸体留到下一轮的情形。
      if (userId != null) {
        const login = await ctx.request.post('/api/v1/auth/login/', {
          data: { username: 'admin', password: 'admin123' },
          failOnStatusCode: false,
        })
        if (login.ok()) {
          const headers = { Authorization: `Bearer ${(await login.json()).token}` }
          await ctx.request.delete(`/api/v1/auth/users/${userId}/`, { headers, failOnStatusCode: false })
        }
      }
      await ctx.close()
    }
  })
})
