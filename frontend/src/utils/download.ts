/**
 * 统一导出下载工具：文件名解析（Content-Disposition）+ Blob 下载。
 *
 * 后端文件名由用户模板渲染（apps/common/export_naming.py），经 Django
 * FileResponse 输出；前端一律解析响应头，不自行拼接。
 * sanitizeFilename 的规则必须与后端 sanitize_filename_part 字面一致。
 */

/** Windows 非法字符 + 控制字符（与后端 _INVALID_CHARS_RE 一致） */
const INVALID_FILENAME_CHARS = /[\\/:*?"<>|\x00-\x1f]/g

export function sanitizeFilename(name: string): string {
  return name
    .replace(INVALID_FILENAME_CHARS, '_')
    .trim()
    .replace(/[. ]+$/, '')
}

/**
 * 从 Content-Disposition 提取文件名。
 * 优先 RFC 5987 filename*=UTF-8''...（中文等非 ASCII 必须走此分支）；
 * 其次 filename="..."。decodeURIComponent 包 try/catch 防 malformed %-escape。
 */
export function extractFilenameFromContentDisposition(
  contentDisposition?: string | null,
): string | null {
  if (!contentDisposition) return null
  const star = /filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i.exec(contentDisposition)
  if (star) {
    try {
      return sanitizeFilename(decodeURIComponent(star[1].trim()))
    } catch {
      return sanitizeFilename(star[1].trim())
    }
  }
  const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(contentDisposition)
  return plain ? sanitizeFilename(plain[1].trim()) : null
}

/** 触发浏览器下载。延迟 revoke：立即 revoke 可能导致下载中断。 */
export function downloadBlob(data: Blob, filename: string): void {
  const url = URL.createObjectURL(data)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  setTimeout(() => {
    URL.revokeObjectURL(url)
    a.remove()
  }, 1000)
}
