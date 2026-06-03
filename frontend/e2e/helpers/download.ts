import fs from 'node:fs'
import path from 'node:path'
import { expect, type Page } from '@playwright/test'
import { DOWNLOAD_DIR } from '../fixtures/test-data'

/**
 * 触发并捕获一次下载，保存到 e2e/.downloads/ 下（供后续人工比对导出内容）。
 * 仅断言文件名与非空，不校验内容细节。
 *
 * @param page  页面
 * @param trigger 触发下载的动作（如点击导出按钮）
 * @param subdir  保存子目录（按模块归类，如 'batch'、'gage'）
 * @returns 保存后的绝对路径与建议文件名
 */
export async function captureDownload(
  page: Page,
  trigger: () => Promise<void>,
  subdir = '',
): Promise<{ savedPath: string; suggestedName: string; size: number }> {
  const dir = subdir ? path.join(DOWNLOAD_DIR, subdir) : DOWNLOAD_DIR
  fs.mkdirSync(dir, { recursive: true })

  const [download] = await Promise.all([page.waitForEvent('download', { timeout: 60_000 }), trigger()])

  const suggestedName = download.suggestedFilename()
  const savedPath = path.join(dir, suggestedName)
  await download.saveAs(savedPath)

  const size = fs.statSync(savedPath).size
  expect(suggestedName, '下载文件名应非空').not.toEqual('')
  expect(size, '下载文件应非空').toBeGreaterThan(0)

  return { savedPath, suggestedName, size }
}
