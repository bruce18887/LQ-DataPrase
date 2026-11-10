import { test, expect } from '@playwright/test'
import { collectAllPages } from '../../src/utils/paging'
import { loginAs } from '../helpers/auth'
import { sidebarLink } from '../helpers/nav'

/**
 * 本 worker 创建过的用户名登记表（形状与理由逐字同 admin.spec.ts:15）。
 *
 * 为什么需要它：playwright.config.ts 是 fullyParallel: true + workers=min(6, cpus/2)，
 * 本文件的用例会散到多个 worker 进程，而 **afterAll 每个 worker 各执行一次** ——
 * 谁都不能替别人清场，只能各自回收自己建的账号。登记一律发生在创建**之前**：
 * POST 半路失败时账号可能已经在后端落库，先记名才保证它归本 worker 的 afterAll 收。
 */
const mine = new Set<string>()

/**
 * 「残留」判据的年龄地板：建号满 10 分钟才算尸体。按 `Date.now()` 现算，
 * 不用「本 worker 加载本模块的时刻」—— 那样会误删兄弟 worker 正在用的活账号，
 * 机制与实测复现见 admin.spec.ts 顶部规则 (c)（同一个坑，2026-11-10 复现过 2/4 轮）。
 */
const RESIDUE_MIN_AGE_MS = 10 * 60_000

/**
 * 操作审计页（/admin/audit）。
 *
 * 与 admin.spec.ts 同一约定：清空注入的 storageState，用 loginAs 实时登录，
 * 这样 Pinia 里的 user/isAdmin 才可信（requiresAdmin 守卫与侧栏过滤读的都是它）。
 *
 * 定位器形状的两条 EP 2.14 实测（都写在前一批的计划正文之外）：
 * - data-testid 一律挂在 el-form-item 上：ElInput 是 inheritAttrs: false 且把 attrs
 *   merge 到原生 input 自己身上，挂在 el-input 上时「[data-testid] input」反而找不到东西。
 * - 事件下拉点外层 .el-select，不点里面的 input：非 filterable 时 EP 给那个 input 的外层
 *   wrapper 恒挂 is-hidden（绝对定位 + 透明度 0 + z-index 负一），出了文档流就没有 hit-test 命得中。
 */
test.describe('操作审计', { tag: ['@admin'] }, () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  // 清理判据（两条任一成立即删，与 admin.spec.ts 同规则；本文件的残留表只管自己这一族）：
  //  (a) 用户名在 `mine` 里 ⇒ 本 worker 自己建的，无条件回收。
  //  (b) 用户名命中本文件的残留前缀 **且** 建号已满 RESIDUE_MIN_AGE_MS ⇒ 上一轮跑残的尸体。
  //      前缀 ↔ 用例：e2e_audit_ = 下面第一条用例（重置密码后取证）。
  //      这道按前缀的兜底不能删：没有任何通路在开跑时清用户账号（global-setup 的
  //      seed_test_data --refresh 只删 DataFile 行），而 `mine` 只活在单个 worker 的内存里。
  //  (c) 年龄闸按 now 而不是按 worker 启动时刻：晚起的 worker（含重试时重新加载的）一定
  //      看到兄弟 worker 几秒前刚建的活账号比自己早，判成残留就误删 —— 这个 flaky 形状的
  //      实测记录在计划文件 docs/superpowers/plans/2026-11-09-account-role-audit-implementation.md
  //      的 Task 10 Step 4.5 第 4 条（改前 3 flaky / 6 passed，复审加「距模块加载时刻」的闸后
  //      仍复现 2/4 次）；本仓 admin.spec.ts:70-75 的规则 (c) 记的是同一次实测收下来的形状。
  //  (d) 跟着 next 取全：本 ViewSet 未覆写 pagination_class，全局 PAGE_SIZE=20，只读第一页
  //      的话第 21 个账号起既扫不到残留、也扫不到 `mine` 里自己那条 ⇒ 清理保证静默失效。
  test.afterAll(async ({ browser }) => {
    const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } })
    try {
      const login = await ctx.request.post('/api/v1/auth/login/', {
        data: { username: 'admin', password: 'admin123' },
      })
      if (!login.ok()) return
      const { token } = await login.json()
      const headers = { Authorization: `Bearer ${token}` }
      const { rows: users } = await collectAllPages<{ id: number; username: string; date_joined: string }>(
        async (url) => (await ctx.request.get(url, { headers, failOnStatusCode: false })).json(),
        '/api/v1/auth/users/',
      )
      for (const u of users) {
        const residue =
          /^e2e_(audit)_/.test(u.username) &&
          Date.now() - new Date(u.date_joined).getTime() > RESIDUE_MIN_AGE_MS
        if (mine.has(u.username) || residue) {
          await ctx.request.delete(`/api/v1/auth/users/${u.id}/`, { headers, failOnStatusCode: false })
        }
      }
    } catch {
      // 清理失败静默（残留由下一轮按 (b) 兜底再清）
    } finally {
      await ctx.close()
    }
  })

  test('@p1 重置密码后审计页出现该记录，按目标账号筛选命中', async ({ page, browser }) => {
    const username = `e2e_audit_${Date.now()}`
    const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } })
    let userId: number | null = null
    try {
      const login = await ctx.request.post('/api/v1/auth/login/', {
        data: { username: 'admin', password: 'admin123' },
      })
      const headers = { Authorization: `Bearer ${(await login.json()).token}` }
      mine.add(username) // 先记名再建号：POST 半路失败时账号也可能已经落库，本 worker 的 afterAll 才认它
      const created = await ctx.request.post('/api/v1/auth/users/', {
        headers,
        data: { username, password: 'e2e-initial-password', role: 'user' },
      })
      expect(created.ok(), `临时账号建不出来：${await created.text()}`).toBe(true)
      userId = (await created.json()).id

      await loginAs(page, 'admin')
      await sidebarLink(page, '用户管理').click()
      const row = page
        .locator('.el-table tbody tr')
        .filter({ has: page.getByText(username, { exact: true }) })
      await row.getByRole('button', { name: '重置密码', exact: true }).click()
      const box = page.locator('.el-message-box')
      await box.locator('.el-message-box__input input').fill('e2e-audited-password')
      const [resetResp] = await Promise.all([
        page.waitForResponse(
          (r) => r.url().includes(`/auth/users/${userId}/reset_password/`),
          { timeout: 20_000 },
        ),
        box.getByRole('button', { name: '重置' }).click(),
      ])
      expect(resetResp.status(), await resetResp.text()).toBe(200)

      await sidebarLink(page, '操作审计').click()
      await expect(page).toHaveURL(/\/admin\/audit/)
      const table = page.locator('.audit-table')
      await expect(table).toBeVisible()
      const rows = table.locator('tbody tr')
      // 不带任何条件的那一眼留着一个：默认挂载真发出了一次列表请求并拿回行 —— 否则下面的筛选腿
      // 就成了「在一个从来没成功加载过的表格上等一段文案」，红字会指错方向。
      await expect(rows.first()).toBeVisible({ timeout: 15_000 })

      // 按目标账号筛：只剩这个账号的事件。
      //
      // 这里**不再**断「不带筛选的倒序第一屏就得有这条」：默认一屏 50 条，而 fullyParallel 的兄弟
      // worker 每一秒都在往同一张 audit_event 里写（登录、建号、锁定全是审计行），那条断言于是
      // 变成「赌本轮没有人写得比我晚」—— 池里迟早输。倒序本身有 T1 判据（test_audit_api.py::
      // AccessAndShapeTests::test_shape_and_newest_first），本腿要证的是「UI 点一次重置密码，
      // 审计页按账号搜得到它，且事件列给的是中文标签」，这两样都不受并发写入摆布。
      const keyword = page.locator('[data-testid="audit-username"] input')
      await keyword.fill(username)
      const [listResp] = await Promise.all([
        page.waitForResponse(
          (r) => r.url().includes('/auth/audit-events/') && r.request().method() === 'GET',
          { timeout: 20_000 },
        ),
        page.getByRole('button', { name: '查询', exact: true }).click(),
      ])
      expect(listResp.status(), await listResp.text()).toBe(200)
      expect(decodeURIComponent(listResp.request().url()), '筛选条件没进请求 URL').toContain(
        `username=${username}`,
      )
      await expect(rows.first()).toContainText(username)
      const count = await rows.count()
      for (let i = 0; i < count; i += 1) {
        await expect(rows.nth(i)).toContainText(username)
      }
      // 断的是**中文标签**而不是码：页面若直出 row.event，这里就是一行 `password_reset`。
      // 这个账号一共两笔（API 建号 + UI 重置），所以标签出现一次且只有重置那条出现；
      // 重置严格晚于建号，倒序（`-created_at, -id`）下它必定是第一行 —— 两样都是本文件内闭合的判据。
      await expect(rows.filter({ hasText: '管理员重置密码' })).toHaveCount(1)
      await expect(rows.first()).toContainText('管理员重置密码')
    } finally {
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

  test('@p1 普通用户：侧栏无审计入口，直达被守卫送回仪表板', async ({ page }) => {
    // 侧栏对非管理员是 v-if 过滤（Sidebar.vue 的 visibleMenuItems）⇒ 链接根本不在 DOM 里，
    // toBeHidden 对「不存在」成立，这是本仓既有写法（admin.spec.ts:127 同形）。
    await loginAs(page, 'user')
    await expect(sidebarLink(page, '操作审计')).toBeHidden()
    await page.goto('/admin/audit')
    // 守卫读 meta.requiresAdmin 并 next('/dashboard')（router/index.ts 的 beforeEach），
    // 而守卫里还有一次 fetchProfile 往返，所以要断**最终** URL 而不是跳转前的那一个。
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 })

    const denied = await page.request.get('/api/v1/auth/audit-events/')
    expect(denied.status()).toBe(401) // 未带凭据；user→403 那条权限判据在 T1
  })

  test('@p2 筛选与重置：条件清空后回到全量，空结果显示空态不报错', async ({ page }) => {
    await loginAs(page, 'admin')
    await sidebarLink(page, '操作审计').click()
    await expect(page).toHaveURL(/\/admin\/audit/)

    const keyword = page.locator('[data-testid="audit-username"] input')
    await keyword.fill('zzz-不存在-zzz')
    await page.getByRole('button', { name: '查询', exact: true }).click()
    await expect(page.getByText('暂无符合条件的审计记录')).toBeVisible({ timeout: 15_000 })

    await page.getByRole('button', { name: '重置', exact: true }).click()
    await expect(keyword).toHaveValue('')
    await expect(page.locator('.audit-table tbody tr').first()).toBeVisible({ timeout: 15_000 })
  })

  /**
   * 四个交互控件的判据（复审点出来的缺口：这四处此前只出现在模板里，0 例碰过）。
   * 每条断的是**真正出得去的那一眼**或**真正贴出来的那段字**，不是「组件渲染出来了」：
   *  - 事件下拉的 v-model 接到死 ref ⇒ 红在 ① 的 `event=`；格式化器恒返回空串 ⇒ 红在 ④ 的原文。
   *  - 日期清空后的 null 若没在纯层收成「不发」，② 的 `not.toContain('date_from')` 当场红；
   *    「null 递进 buildAuditQuery 的 .trim() 会抛、抛被 load() 的 catch 咽掉」这一记，
   *    判据的家在 T2（test/unit/audit.spec.ts 的 null 腿）—— 浏览器侧只能看见「一个请求都没发」，
   *    那是同一条线的**症状**而不是**原因**，所以这里刻意用「重置」拿那一一眼，不去戳 EP 的 clear 图标：
   *    图标要 hover 才出现（picker.vue 的 showClearBtn），hover 本身是另一条不稳定的判据。
   *  - ③ 判得出「用户看得见的候选数字」与「发得出去的 page_size=100」，但**判不出**把
   *    AUDIT_PAGE_SIZE_DEFAULT / AUDIT_PAGE_SIZE_MAX 换成等值字面量 [20, 50, 100] 这一记：
   *    那记今天每个可观测量都一样，浏览器侧无从区分。罩得住它的是 T2 的源码扫描
   *    （test/unit/auditFormat.spec.ts 的「审计页绑的是常量」那一族，剥注释后正反向各一条），
   *    不是本文件 —— 本腿只保证页面挑了 100 条/页时那个数真发得出去。
   */
  test('@p2 筛选控件与展开行：事件、日期、每页条数都进请求，展开行给原始 JSON', async ({ page }) => {
    await loginAs(page, 'admin')
    await sidebarLink(page, '操作审计').click()
    await expect(page).toHaveURL(/\/admin\/audit/)
    const table = page.locator('.audit-table')
    const rows = table.locator('tbody tr')
    await expect(rows.first()).toBeVisible({ timeout: 15_000 })

    // 造一条 detail 可预期的登录失败：库里没有的账号走 views.py 的 unknown_user 分支，
    // 那句写的是 detail={'reason': 'unknown_user'}，不碰任何账号的失败计数（不牵连并行 worker）。
    // 探针打在**不存在的账号**上，所以后端既不建 User 行也不动任何账号的锁定/失败计数
    // （views.py 的 `User.objects.filter(username).first()` 为 None ⇒ 只写一条审计行就返回），
    // 本文件因此没有东西需要回收，afterAll 里也就没有它这一族。
    const probe = `zzz-audit-nobody-${Date.now()}`
    // 刻意**不**断这条 POST 的状态码：登录限流是按 IP 计的（apps/accounts/views.py:100-101 只有
    // `ScopedRateThrottle` + `throttle_scope='login'`，全仓没有覆写 get_ident/get_cache_key ⇒
    // 命中键就是 DRF SimpleRateThrottle 的 REMOTE_ADDR），e2e 档给的是 200/min
    // （config/settings/e2e_slot.py:38），一个 slot 里 6 个 worker 共用同一个回环 IP，
    // 于是这里随时可能被兄弟 worker 的 loginAs 挤成 429。401 那一记的判据在 T1（登录契约），
    // 本腿要的是那行 unknown_user 审计记录 —— 它由末尾 ④ 的 `toHaveCount(1)` 与 JSON 原文兜住，
    // 真被限流挡了会先红在那里（0 行），而不是红在一个跟本功能无关的状态码上。
    await page.request.post('/api/v1/auth/login/', {
      data: { username: probe, password: 'zzz-not-a-password' },
      failOnStatusCode: false,
    })

    const query = page.getByRole('button', { name: '查询', exact: true })
    const keyword = page.locator('[data-testid="audit-username"] input')
    const dateFrom = page.locator('[data-testid="audit-date-from"] input')
    // 只认列表请求：登录那条 POST 也在同一张网络上跑，判据带上方法与路径才不会等错眼。
    const nextList = () =>
      page.waitForResponse(
        (r) => r.url().includes('/auth/audit-events/') && r.request().method() === 'GET',
        { timeout: 20_000 },
      )
    /**
     * 挑「当前开着的那个下拉」—— 本机的实测结论是：**别用 `:visible`**。
     * 2026-11-10 现量：这个页面上常驻 4 个 `.el-select-dropdown` 节点（含一张 87 项的文件下拉，
     * 是仪表板那次渲染留下的），关掉的都还留在 DOM 里。EP 收起下拉走的是 Vue 的 leave 过渡，
     * `display:none` 要等过渡结束才落下，而 `aria-hidden` 是绑在 visible 上的、**同一拍就翻成
     * true**。所以在「刚点开下一个下拉」那一刻，`:visible` 会同时数到上一个（正在播退出动画的）
     * 和这一个；而 `.el-select-dropdown:visible` 配上「先数到 1」恰恰会在上一颗还没收干净时
     * 先判到 1 并挑中它 —— 于是把 10 个事件标签当成了 3 个每页条数候选。实测形状：连跑 4 轮
     * 红 2 轮，红字收到的数组长度是 10、每项抠不出数字。
     * `aria-hidden="false"` 是 EP 自己那份「谁开着」的事实，不受动画影响；仍然数到 1，
     * 真出现两个同时开着就响，不靠 `.last()` 猜。
     */
    const openPopper = async () => {
      const popper = page.locator('.el-popper[aria-hidden="false"] .el-select-dropdown')
      await expect(popper, '同时有两个开着的下拉 ⇒ 这一眼挑不出是谁').toHaveCount(1)
      return popper
    }

    // ① 事件下拉：点外层 .el-select（非 filterable 时里面的 input 被排出文档流，见文件头）。
    await page.locator('[data-testid="audit-event"] .el-select').click()
    const eventPopper = await openPopper()
    // 点 li.el-select-dropdown__item 而不是里面的 span：getByText 会同时命中两者，
    // 这一格只该有一个可点目标，取 li 才不给 strict mode 留歧义。
    await eventPopper
      .locator('.el-select-dropdown__item')
      .filter({ hasText: '登录失败' })
      .click()
    const [byEvent] = await Promise.all([nextList(), query.click()])
    expect(decodeURIComponent(byEvent.request().url()), '事件条件没进请求 URL').toContain(
      'event=login_failure',
    )
    // 第 3 列是事件（1 展开、2 时间）：每一格都得是中文标签，一格里出现码名就是标签表没接上。
    const eventCells = rows.locator('td:nth-child(3)')
    const cellCount = await eventCells.count()
    expect(cellCount, '按事件筛完一行都没有').toBeGreaterThan(0)
    for (let i = 0; i < cellCount; i += 1) {
      await expect(eventCells.nth(i)).toContainText('登录失败')
    }
    // layout 里的 total（'total, sizes, prev, pager, next'）：只断那格有数字，文案本地化不管。
    await expect(page.locator('.el-pagination__total')).toContainText(/\d/)

    // ② 日期填上 ⇒ 进请求；「重置」清空后（EP 交回的是 null）⇒ 从请求里消失，且另一半照常发。
    await dateFrom.fill('2026-01-01')
    const [withDate] = await Promise.all([nextList(), query.click()])
    expect(decodeURIComponent(withDate.request().url()), '起日期没进请求 URL').toContain(
      'date_from=2026-01-01',
    )
    const [cleared] = await Promise.all([
      nextList(),
      page.getByRole('button', { name: '重置', exact: true }).click(),
    ])
    const clearedUrl = decodeURIComponent(cleared.request().url())
    expect(clearedUrl, '清空后仍发 date_from= 就是把条件悄悄留着').not.toContain('date_from')
    expect(clearedUrl, '重置把 username 之外的键一起吞了（page/page_size 得一直在）').toContain('page_size=')
    // waitForResponse 那句本身就把「请求压根没发出去」那一半抓住了（超时即红）；
    // 这两句再补上另一半：回来的不是空态，清日期不会把结果清没。
    await expect(rows.first()).toBeVisible({ timeout: 15_000 })
    await expect(table.locator('.el-empty')).toHaveCount(0)
    expect(await dateFrom.inputValue(), '重置后日期格没清空').toBe('')

    // ③ 每页条数：候选就是 pageSizes 那三个数（20 是 DRF 全局 PAGE_SIZE，50/100 由常量推出）。
    //    只抠数字比较，文案是 EP 本地化的（「20条/页」还是「20/page」）不归本判据管。
    await page.locator('.el-pagination__sizes .el-select').click()
    const sizePopper = await openPopper()
    const sizeItems = sizePopper.locator('.el-select-dropdown__item')
    const sizeTexts = await sizeItems.allTextContents()
    expect(sizeTexts.map((t) => t.replace(/\D/g, '')), '每页条数候选不是 20/50/100').toEqual([
      '20',
      '50',
      '100',
    ])
    const [bySize] = await Promise.all([nextList(), sizeItems.nth(2).click()])
    expect(decodeURIComponent(bySize.request().url()), '每页条数没进请求 URL').toContain(
      'page_size=100',
    )

    // ④ 展开行：贴的是原始 detail 的 JSON 树本身（未打码、未折行、不是摘要那一行的形状）。
    //    这一条断的是「展开格给的是整份原文」；「原文里不该有口令」不归这里管，那道闸在写路径
    //    （test/unit/audit.spec.ts 的 detail 键名 describe），reason 这个键名本来也不命中启发式。
    await keyword.fill(probe)
    const [rowResp] = await Promise.all([nextList(), query.click()])
    expect(rowResp.status(), await rowResp.text()).toBe(200)
    await expect(rows).toHaveCount(1)
    await rows.first().locator('.el-table__expand-icon').click()
    const pre = table.locator('.el-table__expanded-cell .detail-json')
    await expect(pre).toBeVisible({ timeout: 15_000 })
    const raw = (await pre.textContent()) ?? ''
    expect(raw, '展开格没贴出原始键名').toContain('"reason"')
    expect(JSON.parse(raw), '展开格贴的不是可解析的 JSON 原文').toEqual({ reason: 'unknown_user' })
  })

  /**
   * 失败的那一眼必须长成「失败了」，不能长成「这个条件下没有记录」。
   *
   * 后端对 `date_from >= date_to` 抛 400（apps/accounts/views.py 的 AuditEventListView，
   * 同一天不算倒置：date_to 已经是次日零点），axios 拦截器弹一条 toast，组件把行集清空。
   * 这里盯的是第三件事：空态文案有没有跟着换成「加载失败可重试」。留着「暂无符合条件的
   * 审计记录」是在告诉管理员「系统查过了，这条件底下没有案子」—— 取证页上这句谎比空表格
   * 坏得多，而且一次网络抖动就会说到它。条件保留是同一判据的另一半：清空条件等于把
   * 管理员刚敲进去的那一眼也一起扔了，他得从默认视图重头再来。
   */
  test('@p2 日期倒置被后端拒：错误提示 + 「加载失败」空态，筛选条件不被清空', async ({ page }) => {
    await loginAs(page, 'admin')
    await sidebarLink(page, '操作审计').click()
    await expect(page).toHaveURL(/\/admin\/audit/)
    const table = page.locator('.audit-table')
    await expect(table.locator('tbody tr').first()).toBeVisible({ timeout: 15_000 })

    const dateFrom = page.locator('[data-testid="audit-date-from"] input')
    const dateTo = page.locator('[data-testid="audit-date-to"] input')
    await dateFrom.fill('2026-03-05')
    await dateTo.fill('2026-03-01')
    const [resp] = await Promise.all([
      page.waitForResponse(
        (r) => r.url().includes('/auth/audit-events/') && r.request().method() === 'GET',
        { timeout: 20_000 },
      ),
      page.getByRole('button', { name: '查询', exact: true }).click(),
    ])
    expect(resp.status(), await resp.text()).toBe(400)

    // toast 三条里排第一：ElMessage 默认 3 秒自毁，后面的空态与输入框都是常驻的。
    // 用 .first() 是刻意的 —— api/index.ts 顶部记的「两条同族 toast 会顶成 strict mode 歧义」。
    await expect(page.locator('.el-message--error').first()).toBeVisible()
    await expect(
      table.getByText('审计记录加载失败，请调整条件后重试'),
    ).toBeVisible({ timeout: 15_000 })
    await expect(table.getByText('暂无符合条件的审计记录')).toHaveCount(0)

    await expect(dateFrom).toHaveValue('2026-03-05')
    await expect(dateTo).toHaveValue('2026-03-01')
  })
})
