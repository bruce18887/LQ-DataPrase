/// <reference lib="dom" />
/**
 * 复制文本到剪贴板。
 *
 * 优先用异步剪贴板 API（Electron 渲染进程 / localhost 均为安全上下文）；
 * 权限受限或旧内核失败时回退到临时 textarea + execCommand。
 * 返回是否成功，由调用方决定提示文案。
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // 继续走 DOM 回退
  }
  return copyViaTextarea(text)
}

function copyViaTextarea(text: string): boolean {
  if (typeof document === 'undefined' || !document.body) return false
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  try {
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    document.body.removeChild(textarea)
  }
}
