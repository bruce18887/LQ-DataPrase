/**
 * Shared formatting utilities used across the frontend.
 */

/**
 * Truncate a string by keeping head and tail, inserting ellipsis in the middle.
 * Useful for filenames/paths where the start and end carry the most information.
 */
export function truncateMiddle(s: string, max: number): string {
  if (!s || s.length <= max) return s
  const head = Math.ceil(max / 2) - 1
  const tail = Math.floor(max / 2) - 1
  return s.slice(0, head) + '…' + s.slice(-tail)
}

/**
 * Format a byte count into a human-readable size string.
 */
export function formatSize(val: number): string {
  if (!val) return '--'
  if (val < 1024) return val + ' B'
  if (val < 1024 * 1024) return (val / 1024).toFixed(1) + ' KB'
  return (val / 1024 / 1024).toFixed(1) + ' MB'
}

/**
 * MM-DD HH:mm 的格式化器（模块级单例）。
 *
 * `Date.prototype.toLocaleString(locale, options)` 每次调用都在内部新建一个
 * `Intl.DateTimeFormat`，而本函数被文件下拉**逐行**调用（FileSelect.vue 的 metaText，
 * 上限 5000 行/次输入）——旧写法因此每次输入要构造上千个 formatter。
 */
const TIME_FMT = new Intl.DateTimeFormat('zh-CN', {
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

/**
 * Format an ISO date string as a short locale datetime (MM-DD HH:mm).
 */
export function formatTime(val: string): string {
  if (!val) return ''
  return TIME_FMT.format(new Date(val))
}
