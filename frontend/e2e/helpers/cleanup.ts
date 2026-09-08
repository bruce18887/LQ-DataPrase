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

/**
 * 清理 SFTP 测试导入注册的数据行（sample.csv / root.csv / big_*）。
 *
 * 为什么必须做：SFTP 下载即注册 DataFile，失败路径不执行用例末尾的清理时
 * （实测每轮失败泄漏 2-5 行），残留按 -created_at 顶到 files[0] 污染
 * 「最新文件」类断言。globalSetup 只清 e2e_ 前缀，这些名字不在其中
 * （root 库是开发数据快照 + e2e 专属，不能扩大全局 purge 名单误删真实文件）。
 *
 * 用 API 直登 + 按名单删除；失败静默（下一轮兜底再清）。
 */
export async function deleteSftpImportsQuiet(browser: import('@playwright/test').Browser): Promise<void> {
  const SFTP_IMPORTED = /^(sample|root)\.csv$|^big_/i
  try {
    const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } })
    const login = await ctx.request.post('/api/v1/auth/login/', {
      data: { username: 'admin', password: 'admin123' },
      failOnStatusCode: false,
    })
    if (login.ok()) {
      const { token } = await login.json()
      const headers = { Authorization: `Bearer ${token}` }
      const list = await ctx.request.get('/api/v1/files/?page_size=9999', { headers, failOnStatusCode: false })
      if (list.ok()) {
        const body = await list.json()
        const rows: Array<{ id: number; filename: string }> = body.results ?? body ?? []
        for (const f of rows) {
          if (SFTP_IMPORTED.test(f.filename ?? '')) {
            await ctx.request.delete(`/api/v1/files/${f.id}/`, { headers, failOnStatusCode: false })
          }
        }
      }
    }
    await ctx.close()
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn('[cleanup] SFTP 导入数据清理失败（残留测试数据）:', e)
  }
}

/**
 * 按文件名子串删除 e2e 上传产生的 DataFile 行（含磁盘文件）。
 *
 * 为什么必须做：DataFile 默认按 -created_at 排序，上传型用例（如
 * serial-no-column 的 e2e_sts8200_part_id_*）不留 DB 清理时，残留行会顶到
 * files[0]；若其 program_name 恰含其它用例的选文件子串（实测残留的
 * program_name=JAVBN281R3CYCAAV1.6.pgs 含 'BN281R3CYCAA'），pickTabFile 的
 * hasText 过滤会 .first() 选中残留文件而非目标文件 —— 晶圆图两用例的
 * 「Fail 散点 > 0」因此必挂（该残留文件唯一参数全在限内，0 Fail）。
 * 属 lessons R2③「跨套件共享 DB 状态要自建/自清」的又一实证（2026-09-08）。
 *
 * 走页面 Bearer token 调 DELETE /api/v1/files/<id>/（同时删磁盘文件）。
 * 失败静默同 deleteBatchQuiet。
 */
export async function deleteFilesByNameQuiet(page: Page, filenameSubstring: string): Promise<void> {
  try {
    const token = await page.evaluate(() => localStorage.getItem('access_token'))
    if (!token) return
    const headers = { Authorization: `Bearer ${token}` }
    const resp = await page.request.get('/api/v1/files/?page_size=9999', {
      headers, failOnStatusCode: false, timeout: 30_000,
    })
    if (!resp.ok()) return
    const body = await resp.json()
    const files: { id: number; filename: string }[] = Array.isArray(body) ? body : (body.results ?? [])
    for (const f of files) {
      if (!f.filename.includes(filenameSubstring)) continue
      await page.request.delete(`/api/v1/files/${f.id}/`, {
        headers, failOnStatusCode: false, timeout: 30_000,
      })
    }
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn(`[cleanup] 按名删除文件（${filenameSubstring}）失败（残留测试数据）:`, e)
  }
}
