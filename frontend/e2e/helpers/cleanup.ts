import fs from 'node:fs'
import type { Page } from '@playwright/test'

/**
 * 尽力删除临时文件。Edge 浏览器在 setInputFiles 后可能短暂持有文件句柄
 * （Windows EPERM 文件锁），删除失败仅残留 os.tmpdir 下的临时文件，
 * 不影响测试结果——统一静默忽略。
 */
export function cleanupQuiet(p: string): void {
  try {
    fs.rmSync(p, { force: true, maxRetries: 3, retryDelay: 300 })
  } catch {
    // 清理失败可忽略（临时文件残留）
  }
}

/**
 * 删除 e2e 上传产生的批次（磁盘目录 + DataFile 行），防止残留污染共享 DB。
 *
 * 为什么必须做：批次/文件行按 -created_at 排序，分析页与仪表板会自动选中
 * 「最新文件」。zip-upload 造的 root.csv / below.csv / a.csv / b.csv 只有
 * 2 行 2 列（col1/col2）且**无 Site 列**，一旦被自动选中，
 * POST /statistics/site_stats/ 就返回 400 no_site_column，P0 冒烟的
 * 「无控制台错误」断言随之失败；而且每跑一轮 e2e 就累积一批（实测
 * db.sqlite3 从 88 行涨到 120 行）。属 lessons R2③「跨套件共享 DB 状态
 * 要自建/自清」的典型场景。
 *
 * 用页面已有的 Bearer token 调 DELETE /api/v1/batch-dirs/<name>/（该端点
 * 同时删磁盘目录与 DataFile 行）。走相对 URL → 命中 vite 的 /api 代理，
 * 与页面其余请求同一条链路。
 *
 * 失败静默：清理属于 teardown，不应把已经通过的用例弄红（例如 token 已
 * 过期、或页面已导航走）。但失败会留下残留，所以打一条 console 便于排查。
 */
export async function deleteBatchQuiet(page: Page, batchName: string): Promise<void> {
  try {
    const token = await page.evaluate(() => localStorage.getItem('access_token'))
    if (!token) return
    await page.request.delete(`/api/v1/batch-dirs/${encodeURIComponent(batchName)}/`, {
      headers: { Authorization: `Bearer ${token}` },
      failOnStatusCode: false,
      timeout: 30_000,
    })
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn(`[cleanup] 删除批次 ${batchName} 失败（残留测试数据）:`, e)
  }
}
