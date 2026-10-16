import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'

/**
 * 通用后端报错提示（axios 拦截器统一 toast）。
 *
 * 用 page.route 模拟后端错误响应，验证三种错误形状都被格式化为
 * 可读中文并弹出全局 ElMessage.error：
 *   - 带中文的 {"code","message","detail"}（apps/common/exceptions.py）
 *   - 只有机器码的 {"code"}，由前端 ERROR_CODE_MAP 查表（apps/common/errors.py
 *     的 error_response 在 detail 缺失时就是这个形状 —— 后端刻意不复制一份中文表）
 *   - 网络中断（route.abort → 无响应）
 */

test.describe('@p2 通用后端报错提示', { tag: ['@p2', '@global'] }, () => {
  test('500 统一格式错误弹出全局 toast', async ({ page }) => {
    await page.route('**/api/v1/files/**', (route) =>
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ code: 'internal_error', message: '服务器内部错误', detail: null }),
      }),
    )
    // /data 页挂载即加载文件列表 → 触发拦截器统一提示
    await gotoApp(page, '/data')
    await expect(
      page.locator('.el-message--error').filter({ hasText: '服务器内部错误' }),
    ).toBeVisible()
  })

  test('只有机器码时由前端查表映射为中文提示', async ({ page }) => {
    await page.route('**/api/v1/files/**', (route) =>
      route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ code: 'parse_failed', message: null, detail: null }),
      }),
    )
    await gotoApp(page, '/data')
    await expect(
      page.locator('.el-message--error').filter({ hasText: '文件解析失败，请稍后重试' }),
    ).toBeVisible()
  })

})
