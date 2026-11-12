import { reactive, onMounted, onUnmounted } from 'vue'

export interface Toast { id: number; msg: string; kind: string; act?: { label: string; fn: () => void } }
export interface CtxItem { label?: string; sep?: boolean; fn?: () => void }

export const ui = reactive({
  toasts: [] as Toast[],
  dialog: null as null | { title: string; body: string; buttons: { label: string; cls?: string; fn?: () => void }[] },
  ctx: null as null | { x: number; y: number; items: CtxItem[] },
  lightbox: null as null | { src: string; cap: string },
})

let seq = 0
export function toast(msg: string, kind = '', act?: { label: string; fn: () => void }) {
  const t: Toast = { id: ++seq, msg, kind, act }
  ui.toasts.push(t)
  setTimeout(() => { ui.toasts = ui.toasts.filter((x) => x.id !== t.id) }, 4600)
}
export function dialog(title: string, body: string, buttons: { label: string; cls?: string; fn?: () => void }[] = [{ label: '关闭' }]) {
  ui.dialog = { title, body, buttons }
}
export function closeDialog() { ui.dialog = null }
export function openCtx(x: number, y: number, items: CtxItem[]) {
  ui.ctx = { x: Math.min(x, window.innerWidth - 210), y: Math.min(y, window.innerHeight - 40 * items.length - 16), items }
}
export function closeCtx() { ui.ctx = null }
export function openLightbox(src: string, cap: string) { ui.lightbox = { src, cap } }
export function closeLightbox() { ui.lightbox = null }

export function download(name: string, text: string, mime = 'text/plain') {
  const b = new Blob([text], { type: mime })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(b)
  a.download = name
  document.body.appendChild(a)
  a.click()
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove() }, 400)
}
export function mulberry32(a: number) {
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
export const mean = (a: number[]) => a.reduce((x, y) => x + y, 0) / a.length
export const sd = (a: number[]) => { const m = mean(a); return Math.sqrt(a.reduce((x, y) => x + (y - m) * (y - m), 0) / (a.length - 1)) }
export const cpkOf = (a: number[], lo: number, hi: number) => Math.min(hi - mean(a), mean(a) - lo) / (3 * sd(a))
export const gradeOf = (c: number, th: number[] = [1.67, 1.33, 1.0]) => (c >= th[0] ? 'A' : c >= th[1] ? 'B' : c >= th[2] ? 'C' : 'D')
export function normalGen(rng: () => number) {
  return () => { let u = 0, v = 0; while (!u) u = rng(); while (!v) v = rng(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v) }
}
export function quantile(sorted: number[], q: number) {
  const pos = (sorted.length - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos)
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo)
}

/* VitePress 主题切换是内部行为：SVG 演示取 CSS 变量着色，必须监听 html.class 重画 */
export function useThemeRedraw(fn: () => void) {
  let mo: MutationObserver | null = null
  onMounted(() => {
    mo = new MutationObserver(() => fn())
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
  })
  onUnmounted(() => mo?.disconnect())
}