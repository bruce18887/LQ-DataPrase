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
  test('页面渲染：各标签页与关键设置区块可见', async ({ page }) => {
    await gotoApp(page, '/settings')

    // 页面身份 = Topbar 面包屑末级（页头 <h2> 已删：它与面包屑、侧栏激活态三处重复）
    await expect(
      page.getByTestId('breadcrumb').locator('.el-breadcrumb__item:last-child'),
    ).toContainText('系统设置')

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

      // 进入「显示设置」标签页，修改一个安全的数值字段：图表 DPI
      await clickTab(page, '📊 显示设置')
      const dpiInput = page
        .getByText('图表 DPI')
        .locator('xpath=ancestor::*[contains(@class,"el-form-item")]')
        .getByRole('spinbutton')
      await expect(dpiInput).toBeVisible()
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
  test('点击恢复默认 → 确认对话框 → 提示已恢复，随后把账号设置原样还回', async ({ page }) => {
    await gotoApp(page, '/settings')
    // 这条会把共享 admin 账号的**全部**设置洗成出厂值。不还原就会踩掉后面所有读设置的 spec ——
    // 实测：settings.spec 跑完紧接 fonts.spec，fonts 从 0 红变 5 红（2026-10-13 夜间轮
    // 73 条稳定红的元凶之一，见 docs/reference/e2e-tier-triage.md）。
    const before = await snapshotSettings(page)
    try {
      // 触发 ElMessageBox.confirm
      await page.getByRole('button', { name: '🔄 恢复默认' }).click()

      // 确认框 teleport 到 body（.el-message-box）
      const messageBox = page.locator('.el-message-box')
      await expect(messageBox).toBeVisible()
      await expect(messageBox.getByText('确定恢复所有设置为默认值吗？')).toBeVisible()

      // 点击「确定」
      await messageBox.getByRole('button', { name: '确定' }).click()

      // 成功 ElMessage
      await expect(page.locator('.el-message').filter({ hasText: /已恢复默认|恢复/ })).toBeVisible()

      // 先证「真的被洗过」，否则后面的还原会把这条断言变成摆设
      await expect.poll(
        async () => {
          const s = await snapshotSettings(page)
          return s.chart_dpi
        },
        { timeout: 10_000 },
      ).toBe(100)
    } finally {
      await putSetting(page, before)
    }
  })
})
