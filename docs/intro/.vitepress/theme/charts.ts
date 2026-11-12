/* 共享 SVG 小图渲染器：颜色取 VitePress CSS 变量，双主题自动跟随 */
import { mean, sd } from './useUi'
const NS = 'http://www.w3.org/2000/svg'
export function cssVar(n: string) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim() }
export function svgEl(n: string, at: Record<string, string | number>) {
  const e = document.createElementNS(NS, n)
  for (const k in at) e.setAttribute(k, String(at[k]))
  return e
}
export interface MiniOpts { bins?: number; barwidth?: number; limits?: boolean; lo?: number | null; hi?: number | null; sigma?: Record<number, boolean>; kde?: boolean; normal?: boolean }
export function miniHist(svg: SVGSVGElement, vals: number[], opt: MiniOpts = {}) {
  while (svg.firstChild) svg.removeChild(svg.firstChild)
  const W = svg.viewBox.baseVal.width, H = svg.viewBox.baseVal.height
  const mL = 40, mR = 12, mT = 14, mB = 26, iw = W - mL - mR, ih = H - mT - mB
  const bins = opt.bins || 18
  const dmin = Math.min(...vals), dmax = Math.max(...vals)
  const pad = (dmax - dmin) * 0.05 || 1, x0 = dmin - pad, x1 = dmax + pad, bw = (x1 - x0) / bins
  const counts = new Array(bins).fill(0)
  vals.forEach(v => { counts[Math.min(bins - 1, Math.floor((v - x0) / bw))]++ })
  const maxC = Math.max(...counts)
  const X = (v: number) => mL + ((v - x0) / (x1 - x0)) * iw
  const Y = (c: number) => mT + ih - (c / maxC) * ih
  const border = cssVar('--vp-c-border'), text2 = cssVar('--vp-c-text-2'), accent = cssVar('--vp-c-brand-1')
  for (let g = 0; g <= 3; g++) {
    const cy = mT + ih - (g / 3) * ih
    svg.appendChild(svgEl('line', { x1: mL, x2: W - mR, y1: cy, y2: cy, stroke: border, 'stroke-width': 1 }))
    const tl = svgEl('text', { x: mL - 6, y: cy + 4, 'text-anchor': 'end', 'font-size': 9, fill: text2 })
    tl.textContent = String(Math.round((maxC * g) / 3)); svg.appendChild(tl)
  }
  const gap = Math.max(1, (iw / bins) * (1 - (opt.barwidth || 80) / 100))
  counts.forEach((c, b) => {
    svg.appendChild(svgEl('rect', { x: X(x0 + b * bw) + gap / 2, y: Y(c), width: Math.max(1, iw / bins - gap), height: Math.max(0, mT + ih - Y(c)), fill: accent, opacity: 0.82, rx: 1.5 }))
  })
  if (opt.limits) {
    for (const [v, lab] of [[opt.lo, 'LSL'], [opt.hi, 'USL']] as [number | null | undefined, string][]) {
      if (v == null || v < x0 || v > x1) continue
      svg.appendChild(svgEl('line', { x1: X(v), x2: X(v), y1: mT, y2: mT + ih, stroke: cssVar('--intro-err'), 'stroke-width': 1.6, 'stroke-dasharray': '5 4' }))
      const t = svgEl('text', { x: X(v), y: mT - 3, 'text-anchor': 'middle', 'font-size': 9, fill: cssVar('--intro-err'), 'font-weight': 700 })
      t.textContent = lab; svg.appendChild(t)
    }
  }
  if (opt.sigma) {
    const m = mean(vals), s = sd(vals)
    for (const k of [3, 4, 6]) {
      if (!opt.sigma[k]) continue
      for (const v of [m - k * s, m + k * s]) {
        if (v < x0 || v > x1) continue
        svg.appendChild(svgEl('line', { x1: X(v), x2: X(v), y1: mT, y2: mT + ih, stroke: cssVar('--intro-info'), 'stroke-width': 1, 'stroke-dasharray': '2 3', opacity: 0.8 }))
      }
    }
  }
  if (opt.kde || opt.normal) {
    const m2 = mean(vals), s2 = sd(vals), n = vals.length
    const h = 1.06 * s2 * Math.pow(n, -0.2) || 0.3
    const pts: string[] = []
    for (let q = 0; q <= 90; q++) {
      const xv = x0 + ((x1 - x0) * q) / 90
      let d: number
      if (opt.kde) {
        d = 0
        for (let z = 0; z < n; z++) { const u = (xv - vals[z]) / h; d += Math.exp(-0.5 * u * u) }
        d /= n * h * Math.sqrt(2 * Math.PI)
      } else {
        d = Math.exp(-0.5 * Math.pow((xv - m2) / s2, 2)) / (s2 * Math.sqrt(2 * Math.PI))
      }
      const yv = mT + ih - ((d * n * bw) / maxC) * ih
      pts.push((q ? 'L' : 'M') + X(xv).toFixed(1) + ' ' + Math.max(mT, yv).toFixed(1))
    }
    svg.appendChild(svgEl('path', { d: pts.join(''), fill: 'none', stroke: opt.kde ? cssVar('--intro-violet') : cssVar('--intro-ok'), 'stroke-width': 2, opacity: 0.9 }))
  }
  for (let tI = 0; tI <= 5; tI++) {
    const xv2 = x0 + ((x1 - x0) * tI) / 5
    const tx = svgEl('text', { x: X(xv2), y: H - 8, 'text-anchor': 'middle', 'font-size': 9, fill: text2 })
    tx.textContent = xv2.toFixed(1); svg.appendChild(tx)
  }
}