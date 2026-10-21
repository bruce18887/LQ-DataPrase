/**
 * 缩放归谁做 —— 只有 Electron 档由应用接管。
 *
 * 浏览器档**不再**往 `<html>` 写 CSS `zoom`：zoom 会连同 teleport 到 body 的
 * `position:absolute` 浮层（Element Plus 的下拉/popover/tooltip）一起放大，而
 * `getBoundingClientRect()` 给的是已放大的视觉坐标，floating-ui（@floating-ui/dom
 * 1.7.6，不支持 CSS zoom）把它原样写进 `left/top` ⇒ 浮层再乘一次 zoom，
 * 偏移 = reference 坐标 ×(zoom−1)（2026-10-21 实测 125%/150% 两档逐字吻合）。
 * 浏览器的原生页面缩放没有这个坐标系裂缝，手势直接让给浏览器。
 */
export type ZoomRuntime = 'electron' | 'browser'

export function detectZoomRuntime(hasElectronApi: boolean): ZoomRuntime {
  return hasElectronApi ? 'electron' : 'browser'
}

/** 应用是否接管缩放手势与缩放值；false = 不绑监听、不写 CSS zoom */
export function shouldOwnZoom(runtime: ZoomRuntime): boolean {
  return runtime === 'electron'
}
