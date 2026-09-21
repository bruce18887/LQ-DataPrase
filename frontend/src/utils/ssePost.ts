/**
 * utils/ssePost — 共享 SSE 消费器
 *
 * 从 `api/sftp.ts:210-249` **逐字提取**（计划 Task 12），本文件的函数体与原实现
 * 一字符一字符相同：baseURL 拼接（Electron `file://` 兼容）、`Authorization: Bearer`
 * 头、按 `'\n\n'` 切帧且 `pop()` 保留残段、JSON.parse 失败静默跳过、AbortError 由
 * postSse 自身**不**吞（吞在调用方 catch）、非 2xx 读 `err.error` 抛错。
 *
 * 为什么单独成文件：下载主链路（`sftpApi.downloadFileStream` / `downloadDirStream`）
 * 与新的搜索流（`api/sftpSearch.ts`）要用**同一个** SSE 解析器。放在 `api/sftp.ts`
 * 里则搜索层得反向依赖下载层；而这条路径上有两个正被 e2e 钉住的下载功能，所以
 * 提取必须是纯搬运——任何「顺手优化」（改签名、改错误处理、改分帧）都在拿下载换搜索。
 *
 * 唯一必要的改动是 `export` 与两个 import 的相对路径（目录从 `api/` 换到 `utils/`）。
 */
import api from '../api/index'
import { safeGetItem } from './safeStorage'

/**
 * POST 一个 SSE 端点并逐事件回调。非 2xx：解析错误体后抛出（调用方负责
 * 提示）；流式解析与事件分发与旧 downloadDirStream 实现一致。
 *
 * signal: 可选 AbortSignal，透传给 fetch —— 修复此前无法取消进行中 SSE 流
 * 的缺陷（组件卸载后 reader 仍持有并回调更新已失效 ref → 内存泄漏 + 幽灵回调）。
 * localStorage 读取改走 safeGetItem（Electron 磁盘满/权限异常时不白屏）。
 */
export async function postSse(
  url: string,
  body: Record<string, unknown>,
  onData: (data: any) => void,
  signal?: AbortSignal,
): Promise<void> {
  const token = safeGetItem('access_token')
  // Re-use the axios base URL so this works in Electron (file://) as well as
  // the browser dev/prod builds, where absolute paths resolve incorrectly.
  const baseUrl = (api.defaults.baseURL || '/api/v1').replace(/\/$/, '')
  const response = await fetch(`${baseUrl}${url}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok) {
    const err = await response.json().catch(() => ({ error: '请求失败' }))
    throw new Error(err.error || `HTTP ${response.status}`)
  }
  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split('\n\n')
    buffer = events.pop()!
    for (const evt of events) {
      if (!evt.startsWith('data: ')) continue
      try {
        onData(JSON.parse(evt.slice(6)))
      } catch { /* skip malformed events */ }
    }
  }
}
