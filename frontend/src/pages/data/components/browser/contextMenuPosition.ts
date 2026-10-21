/**
 * 右键菜单落位：把「视口 px 的右键点」换算进菜单自己的坐标空间，再在视口内夹紧。
 *
 * 为什么要换算：CSS `zoom` 写在 `<html>` 上时，它会连同 Teleport 到 body 的
 * `position: fixed` 菜单一起放大；而 `MouseEvent.clientX/Y` 与 `getBoundingClientRect()`
 * 给的是**已放大的视觉 px**。把 clientX 原样写进 `left` 等于让菜单再乘一次 zoom ——
 * 偏移随「距视口左上角的距离」线性增长，1.5 档整块菜单被推出视口（2026-10-18 实测）。
 * 同一个裂缝也打偏 Element Plus 的下拉/popover，所以 2026-10-21 起浏览器档不再写 CSS zoom
 * （见 `composables/zoomMode.ts`），Electron 档走 `webContents.setZoomFactor`（坐标同源）
 * ⇒ 两档这里都读回 1，换算退化成空操作。保留它只为兜住「将来又有人往 `<html>` 写 zoom」，
 * 那条恒等式（画出来的位置 == 右键点）在两档下都成立。
 *
 * 空间约定（全部视口 px，除标注 local 者）：clientX/Y、rect 宽高、innerWidth/Height。
 * 返回值是 local px，即 `left`/`top` 该写进去的那个数。
 */
export interface ContextMenuPointInput {
  /** 右键点，视口 px */
  clientX: number
  clientY: number
  /** 菜单实测宽高，视口 px；还没渲染时传 0 表示「只换算、不夹紧」 */
  menuWidth: number
  menuHeight: number
  /** 视口宽高，视口 px */
  viewportWidth: number
  viewportHeight: number
  /** `<html>` 上生效的 CSS zoom */
  zoom: number
  /** 离视口边缘的留白，local px */
  margin?: number
}

const DEFAULT_MARGIN = 8

/** 纯函数：入参出参见文件头。判据住这里，T2 逐组合钉死，不在浏览器里点按钮。 */
export function contextMenuPoint(i: ContextMenuPointInput): { x: number; y: number } {
  const z = i.zoom > 0 ? i.zoom : 1
  const m = i.margin ?? DEFAULT_MARGIN
  // 折进 local 空间后再夹紧：视口与菜单尺寸都要除以 z，否则 8px 留白会被放大成 8*z。
  // 下限 m 保住旧行为（右键点贴左上角时收进视口），也挡住菜单比视口大时翻成负数。
  const clamp = (viewport: number, size: number, click: number) =>
    Math.max(m, Math.min(click / z, viewport / z - size / z - m))
  return {
    x: clamp(i.viewportWidth, i.menuWidth, i.clientX),
    y: clamp(i.viewportHeight, i.menuHeight, i.clientY),
  }
}

/**
 * `<html>` 上实际生效的 CSS zoom。没设过、或浏览器把 `zoom` 报成 `normal` 时按 1 算。
 * Electron 档不设 CSS zoom（走 `setZoomFactor`），这里读回来就是 1。
 */
export function documentCssZoom(): number {
  const raw = getComputedStyle(document.documentElement).zoom as string | number | undefined
  const z = typeof raw === 'number' ? raw : parseFloat(String(raw))
  return Number.isFinite(z) && z > 0 ? z : 1
}

/**
 * 读 DOM 的那层薄壳：菜单渲染前后各调一次。
 * `el` 为空（首帧还没挂载）时按零尺寸只换算空间，下一帧再拿实测宽高夹紧。
 */
export function measureContextMenu(
  el: HTMLElement | null,
  clientX: number,
  clientY: number,
): { x: number; y: number } {
  const rect = el?.getBoundingClientRect()
  return contextMenuPoint({
    clientX,
    clientY,
    menuWidth: rect?.width ?? 0,
    menuHeight: rect?.height ?? 0,
    viewportWidth: window.innerWidth,
    viewportHeight: window.innerHeight,
    zoom: documentCssZoom(),
  })
}
