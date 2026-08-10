import fs from 'node:fs'

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
