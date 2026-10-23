import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'

/**
 * 系统设置页（/settings）— 左侧竖排标签页布局（SettingsPage.vue）。
 * 仅需登录态（项目级注入 admin storageState，不清空）。
 * 关键交互：加载设置（GET /auth/settings/）、保存（PUT /auth/settings/）、恢复默认（ElMessageBox 确认）。
 *
 * 注意：admin storageState 共享 + 设置持久化，修改渲染器设置的用例必须在
 * finally 中恢复默认 svg（restoreChartRenderer 只 PUT 单字段）——否则
 * canvas 会泄漏到依赖 SVG 断言的 analysis 用例（multi-file/kde-curve 等）。
 */

const TABS = [
  { label: '📊 显示设置', content: 'ECharts 渲染器' },
  { label: '📋 表格设置', content: '默认每页行数' },
  { label: '📐 CPK 阈值', content: 'CPK A 级阈值' },
  { label: '📄 导出模板', content: '导出文件名' },
  { label: '🔌 SFTP 设置', content: 'SFTP 下载超时' },
  // 批 4 新增：浏览器形态下没有 electronAPI，连接 tab 应显示「由你打开的地址决定」
  // 而不是 Electron 专属的切换按钮（当前后端这一行描述项始终在）。
  { label: '🔗 连接', content: '当前后端' },
  { label: '📁 存储路径', content: '数据目录' },
]

/**
 * 已摘除的死设置：曾在设置页有控件、但前后端都无人读取（2026-09-19 批 3 移除，
 * 见 docs/tasks/todo.md「系统设置失效项整改」）。断言它们不再出现，防止有人
 * 只加回控件而不接消费链路。
 */
const REMOVED_DEAD_SETTINGS = [
  '图表渲染引擎',
  '图表高度',
  '直方图标签偏移',
  '表格高度',
  '表头字号',
  '最近文件',
  '最多保留',
]

async function clickTab(page: import('@playwright/test').Page, label: string) {
  await page.getByRole('tab', { name: label }).click()
}

/** 只 PUT 指定字段（不触碰其它设置）—— 用例改过的账号级设置都靠它复原 */
async function putSetting(page: import('@playwright/test').Page, body: Record<string, unknown>) {
  const status = await page.evaluate(async (payload) => {
    const resp = await fetch('/api/v1/auth/settings/', {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('access_token')}`,
      },
      body: JSON.stringify(payload),
    })
    return resp.status
  }, body)
  // 复原失败必须出声：共享 admin 账号上留下的脏值会踩掉后续用例的前提
  expect(status, `PUT ${JSON.stringify(body)} 应成功`).toBe(200)
}

/** 恢复渲染器为默认 svg */
async function restoreChartRenderer(page: import('@playwright/test').Page) {
  await putSetting(page, { chart_renderer: 'svg' })
}

/**
 * 账号级设置快照。GET 返回的就是 UserSettingSerializer 的那批**可写字段**，
 * 所以原样 PUT 回去是一次干净往返（不含只读键）。
 */
async function snapshotSettings(page: import('@playwright/test').Page): Promise<Record<string, unknown>> {
  return page.evaluate(async () => {
    const resp = await fetch('/api/v1/auth/settings/', {
      headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` },
    })
    return resp.json()
  })
}

test.describe('@p1 系统设置页', { tag: ['@p1', '@settings'] }, () => {
  /**
   * Task 6b Step 7 的计数判据（设置页这一侧）。档位选择依据 `scripts/affected-rules.mjs:36`：
   * `frontend/src/pages/settings/` → `['settings']`，本批被保护的站点正是 SettingsPage.vue
   * （改前 @74cc4c6 的 `:90` 自己裸 GET、`:122` 无脏追踪地把 defaults 的 **12 个键**整对象 PUT
   * ⇒ 生产实测一次会话 32 次 PUT；行号只在那一版成立，认函数名 loadSettings/saveSettings 别认行号）。
   * 收敛后设置页不再自己 GET：守卫那次（router/index.ts:178 → store.ensure()）就是唯一一次，
   * `loadSettings()` 里的 `ensure()` 命中「已结算」直接返回。
   * ⚠ 计数器同样必须装在 goto 之前（lessons R2④）；只算 GET，PUT 由下面两条交互用例自证。
   * ⚠ 精确长度判据的已知假红：axios 401 拦截器会**重放**原 GET（api/index.ts:226-231），
   *   长夜跑里 access token 一过期这条就变 2 条 ⇒ 先查 LQDP_ACCESS_TOKEN_MINUTES 再判回归。
   */
  test('@p1 进设置页只发一次 GET /auth/settings/（读设置走单一 store）', async ({ page }) => {
    const hits: string[] = []
    page.on('request', (r) => {
      if (r.method() === 'GET' && /\/auth\/settings\//.test(r.url())) hits.push(r.url())
    })

    await gotoApp(page, '/settings')
    await expect(page.getByTestId('page-identity')).toContainText('系统设置')
    await expect(page.getByRole('button', { name: '💾 保存设置' })).toBeVisible()
    // 留 2s：loadSettings 若仍在自取，第 2 条会在这段时间落地
    await page.waitForTimeout(2_000)

    expect(hits, `一次导航到 /settings 发出了 ${hits.length} 条 GET /auth/settings/，应为 1 条`).toHaveLength(1)
  })

  test('页面渲染：各标签页与关键设置区块可见', async ({ page }) => {
    await gotoApp(page, '/settings')

    // 页面身份 = 顶栏 [data-testid=page-identity]（页头 <h2> 已删：它与面包屑、侧栏激活态三处重复）
    await expect(page.getByTestId('page-identity')).toContainText('系统设置')

    // 各 tab 标签（清单 = TABS；加新 tab 必须同步登记，否则「切换各标签页」那条不覆盖它）
    for (const tab of TABS) {
      await expect(page.getByRole('tab', { name: tab.label })).toBeVisible()
    }

    // 操作按钮（全局，不随 tab 切换）
    await expect(page.getByRole('button', { name: '💾 保存设置' })).toBeVisible()
    await expect(page.getByRole('button', { name: '🔄 恢复默认' })).toBeVisible()
  })

  test('死设置控件不再出现（曾「存了没人读」，2026-09-19 批 3 摘除）', async ({ page }) => {
    await gotoApp(page, '/settings')
    for (const tab of TABS) {
      await clickTab(page, tab.label)
    }
    for (const label of REMOVED_DEAD_SETTINGS) {
      await expect(page.getByText(label, { exact: true }), `应已移除：${label}`).toHaveCount(0)
    }
    // 承载死设置的「最近文件」tab 整体摘除
    await expect(page.getByRole('tab', { name: '🕐 最近文件' })).toHaveCount(0)
  })

  test('切换各标签页 → 对应设置内容可见', async ({ page }) => {
    await gotoApp(page, '/settings')

    for (const tab of TABS) {
      await clickTab(page, tab.label)
      await expect(page.getByText(tab.content).first()).toBeVisible()
    }
  })

  test('修改设置项并保存 → PUT 请求体带上改动字段且出现成功提示', async ({ page }) => {
    try {
      await gotoApp(page, '/settings')
      // 前置自建：不先把账号钉在 100，下面填 200 就可能是「填了个当前值」⇒ 不脏、不发 PUT，
      // 这条会红在 waitForResponse 上，看着像保存通路坏了（2026-10-23 实测：账号被
      // 同文件 :200 漏下的 200 踩中过一次）。finally 洗回 100，两边对称。
      await putSetting(page, { chart_dpi: 100 })
      await page.reload()

      // 进入「显示设置」标签页，修改一个安全的数值字段：图表 DPI
      await clickTab(page, '📊 显示设置')
      const dpiInput = page
        .getByText('图表 DPI')
        .locator('xpath=ancestor::*[contains(@class,"el-form-item")]')
        .getByRole('spinbutton')
      await expect(dpiInput).toBeVisible()
      // 前置可见证据：填的 200 与账号当前值不同（红在这里＝前置没落，别去查保存通路）
      await expect(dpiInput, '前置：reload 后 UI 应显示账号值 100').toHaveValue('100', { timeout: 15_000 })
      await dpiInput.fill('200')
      // 触发 el-input-number 的 change（失焦提交值）
      await dpiInput.blur()

      // 点保存并断言「改动真的发出去了」。
      // 只断 method 是同义反复（predicate 已经按 PUT 过滤），且并行 project 的 PUT
      // 会被错抓（见上面渲染器用例的同类处理）—— 所以判据落在请求体上。
      const [response] = await Promise.all([
        page.waitForResponse(
          (resp) =>
            /\/auth\/settings\//.test(resp.url()) &&
            resp.request().method() === 'PUT' &&
            /"chart_dpi":\s*200/.test(resp.request().postData() ?? ''),
        ),
        page.getByRole('button', { name: '💾 保存设置' }).click(),
      ])
      expect(response.status(), '保存应返回 200').toBe(200)

      // 成功 ElMessage — 限定 .el-message 避免命中标题/按钮文本
      await expect(page.locator('.el-message').filter({ hasText: /保存|成功/ })).toBeVisible()
    } finally {
      // DPI 住在共享 admin 账号上，不复位会把 200 漏给后续用例（渲染相关断言按 100 估）
      await putSetting(page, { chart_dpi: 100 })
    }
  })

  /**
   * 脏基线在保存后必须复位（2026-10-23 收口评审 D 项）。
   *
   * 缺陷形状：`SettingsPage.vue` 的 `loaded`（脏判定读的快照）原先是**非响应式**的
   * `let loaded: SettingsData`，而读它的是 computed（`dirtyKeys`）⇒ 保存成功后那句
   * `loaded = snapshot(...)` 重赋值不进依赖表，computed 不失效 ⇒ 脏键列表停在保存前那一份：
   * 按钮继续可用、「没有需要保存的改动」永不出现、再点一次把同一批键再 PUT 一遍
   * （PUT 载荷本身是对的，坏的是判定，所以只有请求条数与 UI 状态能看出来）。
   *
   * 判据是四段转移，缺任一段都退化成空断言：
   * ① 进页面＝干净 ⇒ 置灰 + 提示在；② 改一个字段＝脏 ⇒ 可用 + 提示消失；
   * ③ 保存成功 ⇒ 回到 ①；④ 全程 PUT 只有一发（第二次点击在置灰的按钮上根本发不出去）。
   * ① 同时是 Task 6b 脏追踪的入口锚点：若某个子表单在挂载时就规范化出一个不等的值，
   * 这条会先红在 ①，那才是它该报的事。
   *
   * ⚠ 精确长度判据的已知假红同本文件上面那条 GET 计数（axios 401 拦截器重放原请求，
   *   见 docs/tasks/todo.md「三条计数守卫继承 401 重放的假红风险」）⇒ 变红先查
   *   LQDP_ACCESS_TOKEN_MINUTES，别先改判据。
   */
  test('@p1 保存后脏基线复位 dirty：按钮置灰、提示回来且只 PUT 一次', async ({ page }) => {
    const puts: string[] = []
    page.on('request', (r) => {
      if (r.method() === 'PUT' && /\/auth\/settings\//.test(r.url())) puts.push(r.postData() ?? '')
    })

    await gotoApp(page, '/settings')
    try {
      // 前置自建（与 :144 同因）：② 填的 200 必须**不等于**账号当前值，否则脏判定不成立。
      await putSetting(page, { chart_dpi: 100 })
      await page.reload()
      // 上面那发自建的 PUT 也算进 `puts`（监听器装在 goto 之前）⇒ 清零，
      // 让 ④ 量的仍是「本次交互期间产品发出的 PUT 条数」，判据不被前置污染。
      puts.length = 0
      const saveBtn = page.getByRole('button', { name: '💾 保存设置' })
      const hint = page.getByText('没有需要保存的改动')
      await expect(saveBtn).toBeVisible()

      // ① 进页面：settings 与 loaded 同一份 ⇒ 干净
      await expect(saveBtn, '无改动时保存按钮应置灰（Task 6b 脏追踪）').toBeDisabled()
      await expect(hint).toBeVisible()

      // ② 改一个字段 ⇒ 脏（DPI 是本文件其它用例同款的安全数值字段）
      await clickTab(page, '📊 显示设置')
      const dpiInput = page
        .getByText('图表 DPI')
        .locator('xpath=ancestor::*[contains(@class,"el-form-item")]')
        .getByRole('spinbutton')
      await expect(dpiInput).toBeVisible()
      // 前置可见证据（与 :144 同款）：② 要填的 200 必须不等于账号当前值
      await expect(dpiInput, '前置：reload 后 UI 应显示账号值 100').toHaveValue('100', { timeout: 15_000 })
      await dpiInput.fill('200')
      await dpiInput.blur()
      await expect(saveBtn, '改过之后按钮必须可用').toBeEnabled()
      await expect(hint, '脏状态下不该再显示「没有需要保存的改动」').toHaveCount(0)

      // ③ 保存成功后回到干净
      const [response] = await Promise.all([
        page.waitForResponse(
          (resp) =>
            /\/auth\/settings\//.test(resp.url()) &&
            resp.request().method() === 'PUT' &&
            /"chart_dpi":\s*200/.test(resp.request().postData() ?? ''),
        ),
        saveBtn.click(),
      ])
      expect(response.status(), '保存应返回 200').toBe(200)
      await expect(page.locator('.el-message').filter({ hasText: /保存|成功/ })).toBeVisible()
      await expect(
        saveBtn,
        '保存后脏基线没复位 ⇒ 按钮仍可用（旧写法 loaded 非响应式，computed 不失效）',
      ).toBeDisabled({ timeout: 5_000 })
      await expect(hint, '保存后应重新出现「没有需要保存的改动」').toBeVisible()

      // ④ 整段只发过一发 PUT（再点一次就发第二发）
      await page.waitForTimeout(1_000)
      expect(puts, `本次交互发出了 ${puts.length} 发 PUT /auth/settings/，应为 1 条`).toHaveLength(1)
    } finally {
      // ③ 那发 PUT 走的是产品保存通路，`chart_dpi=200` 是**真存进共享 admin 账号**的
      // （不像 :144 那条可以只断请求体）⇒ 必须复位，否则漏给后续用例。
      // 实测踩掉的就是同文件下面的「恢复默认」：它按「账号停在出厂值」这个空转前提成立，
      // 200 一漏就稳定红（2026-10-23 收口池 :200 先跑、:288 后红）。
      await putSetting(page, { chart_dpi: 100 })
    }
  })

  test('渲染器保存持久化：改为 Canvas → 保存 → 后端回显 canvas；结束后恢复 SVG', async ({ page }) => {
    try {
      // 先注册 GET 等待再导航，确保 loadSettings 完成后才交互（避免慢响应覆盖点击）
      const getResp = page.waitForResponse(
        (resp) => /\/auth\/settings\//.test(resp.url()) && resp.request().method() === 'GET',
      )
      await gotoApp(page, '/settings')
      await getResp

      // 显示设置 tab 为默认激活；el-radio 的 input 视觉隐藏，
      // 点击 label 文本触发选中，用 toBeChecked 断言状态（属性级，不要求可见）
      await page.getByText(/Canvas（大数据量时性能更好）/).click()
      await expect(page.getByRole('radio', { name: /Canvas/ })).toBeChecked()

      // 保存并断言后端回显 canvas —— 回归断言：旧后端缺少该字段，
      // PUT 静默丢弃未知键、响应无 chart_renderer，刷新后回退 SVG。
      // predicate 用 postData 过滤请求体，避免并行 project（Edge/P1）捕获
      // 对方实例的 PUT（含 finally 里的 svg 恢复）。
      const [response] = await Promise.all([
        page.waitForResponse((resp) => {
          const isPut = /\/auth\/settings\//.test(resp.url()) && resp.request().method() === 'PUT'
          return isPut && resp.request().postData()?.includes('"chart_renderer":"canvas"')
        }),
        page.getByRole('button', { name: '💾 保存设置' }).click(),
      ])
      expect(response.status()).toBe(200)
      const body = (await response.json()) as Record<string, unknown>
      expect(body.chart_renderer).toBe('canvas')
      await expect(page.locator('.el-message').filter({ hasText: /保存|成功/ })).toBeVisible()
      // 同一页面内 UI 仍为选中态
      await expect(page.getByRole('radio', { name: /Canvas/ })).toBeChecked()
    } finally {
      await restoreChartRenderer(page)
    }
  })
})

test.describe('@p2 恢复默认', { tag: ['@p2', '@settings'] }, () => {
  /**
   * 「恢复默认」只改本地，落库要再点一次保存 —— 产品文案写的就是这个
   * （`SettingsPage.vue` 的 `resetDefaults()`：`settings.value = {...defaults}` + 提示
   * 「已恢复默认设置（请点击保存以持久化）」，全程不发请求）。
   *
   * 2026-10-23 重写。旧写法点完「确定」直接按**后端**断 `chart_dpi === 100`，而产品根本不 PUT
   * ⇒ 它只在「账号此刻恰好是出厂值」时成立（前一条 DPI 用例的 finally 刚洗回 100 ⇒ 空转绿）；
   * 一旦别的用例漏下 200 就稳定红 —— 那次的正确归因是**漏值的那条没自清**，不是这条断到了回归。
   *
   * 现在的三段各自承重：
   * ① 前置自己把账号推离出厂值（200）并 reload ⇒ 「恢复后显示 100」不再是空转；
   * ② 确认后 UI 回 100 且**后端仍是 200** ⇒ 钉住「不落库」这半边契约；
   * ③ 再点保存，后端才变 100 ⇒ 钉住「保存才落库」那半边。
   * finally 原样还回 `before`：这条会把账号的**全部**设置洗成出厂值，不还原就踩后续读设置的 spec
   * （实测：settings.spec 跑完紧接 fonts.spec，fonts 从 0 红变 5 红，2026-10-13 夜间轮
   * 73 条稳定红的元凶之一，见 docs/reference/e2e-tier-triage.md）。
   */
  test('恢复默认只改本地，点保存才落库；结束后把账号设置原样还回', async ({ page }) => {
    await gotoApp(page, '/settings')
    const before = await snapshotSettings(page)
    try {
      await putSetting(page, { chart_dpi: 200 })
      await page.reload()
      await clickTab(page, '📊 显示设置')
      const dpiInput = page
        .getByText('图表 DPI')
        .locator('xpath=ancestor::*[contains(@class,"el-form-item")]')
        .getByRole('spinbutton')
      await expect(dpiInput, '前置：账号应先停在非默认值 200').toHaveValue('200', { timeout: 15_000 })

      // 触发 ElMessageBox.confirm（teleport 到 body，.el-message-box）
      await page.getByRole('button', { name: '🔄 恢复默认' }).click()
      const messageBox = page.locator('.el-message-box')
      await expect(messageBox).toBeVisible()
      await expect(messageBox.getByText('确定恢复所有设置为默认值吗？')).toBeVisible()
      await messageBox.getByRole('button', { name: '确定' }).click()
      await expect(page.locator('.el-message').filter({ hasText: /已恢复默认/ })).toBeVisible()

      // ② UI 回到出厂值，后端没动
      await expect(dpiInput, '确认后输入框应显示默认 100').toHaveValue('100')
      expect(
        (await snapshotSettings(page)).chart_dpi,
        '没点保存就落库 ⇒ 与提示文案「请点击保存以持久化」矛盾',
      ).toBe(200)

      // ③ 保存才落库
      await page.getByRole('button', { name: '💾 保存设置' }).click()
      await expect
        .poll(async () => (await snapshotSettings(page)).chart_dpi, { timeout: 10_000 })
        .toBe(100)
    } finally {
      await putSetting(page, before)
    }
  })
})
