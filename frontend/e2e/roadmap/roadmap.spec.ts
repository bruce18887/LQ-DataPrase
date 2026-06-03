import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'

/**
 * 功能路线图（/roadmap）。
 * 使用注入的 admin storageState（仅需 token）。纯前端静态数据，无后端依赖。
 *
 * 选择器依据：
 *  - RoadmapPage.vue 行 6：页面标题 <h1>「🗺️ ATE 指标实现路线图」
 *  - components/P1TaskManager.vue 行 14：任务网格容器 `.tasks-grid`
 *  - components/P1TaskManager.vue 行 18：任务卡片 `.task-card`（共 7 张，TODO-07~13）
 *  - 行 57：点击卡片打开详情面板 `.task-detail-panel`；行 59 `.detail-title`；
 *    行 60 关闭按钮 `.close-btn`；行 66 详情含「任务描述」小节
 */

test.describe('功能路线图', { tag: ['@p2', '@roadmap'] }, () => {
  test('@p2 页面渲染', async ({ page }) => {
    await gotoApp(page, '/roadmap')
    // 页面主标题（RoadmapPage.vue 行 6）
    await expect(page.getByRole('heading', { name: /ATE 指标实现路线图/ })).toBeVisible()
  })

  test('@p2 P1 任务管理器渲染任务卡片', async ({ page }) => {
    await gotoApp(page, '/roadmap')
    // 任务网格存在
    await expect(page.locator('.tasks-grid')).toBeVisible()
    // 至少一张任务卡片（实际 7 张：TODO-07~13）
    const cards = page.locator('.tasks-grid .task-card')
    await expect(cards.first()).toBeVisible()
    expect(await cards.count()).toBeGreaterThanOrEqual(1)
  })

  test('@p2 点击任务卡片打开详情面板', async ({ page }) => {
    await gotoApp(page, '/roadmap')
    const firstCard = page.locator('.tasks-grid .task-card').first()
    await expect(firstCard).toBeVisible()
    await firstCard.click()
    // 详情面板出现（P1TaskManager.vue 行 57）
    const panel = page.locator('.task-detail-panel')
    await expect(panel).toBeVisible()
    // 面板内含「任务描述」小节（行 66）
    await expect(panel.getByText('任务描述')).toBeVisible()
    // 关闭后面板消失（行 60 close-btn）
    await panel.locator('.close-btn').click()
    await expect(panel).toBeHidden()
  })
})
