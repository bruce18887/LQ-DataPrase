/**
 * 页内颜色探针：把 color-mix()/rgba()/hex 计算值合成到实际底色再算对比度。
 *
 * 注意（2026-09-02）：Chrome 把 `color-mix(in srgb, var(--warn) 12%, transparent)`
 * 的计算值序列化成 `color(srgb r g b / a)` 而非 `rgba(...)`——只匹配 rgba 的探针
 * 会把 alpha 读成 0，误判「着色没生效」。
 */
export function tintContrastProbe(arg: { barSel: string; rowClasses: string[] }) {
  const parse = (s: string): { c: number[]; a: number } | null => {
    s = (s || '').trim()
    let m = s.match(/^rgba?\(([^)]+)\)$/)
    if (m) {
      const p = m[1].split(/[,\s/]+/).filter(Boolean).map(Number)
      if (p.length < 3 || p.some(Number.isNaN)) return null
      return { c: [p[0], p[1], p[2]], a: p.length > 3 ? p[3] : 1 }
    }
    m = s.match(/^color\(([\w-]+)([^)]+)\)$/)
    if (m) {
      const p = m[2].split(/[,\s/]+/).filter((x) => x && x !== 'none').map(Number)
      if (p.length < 3 || p.some(Number.isNaN)) return null
      return { c: [p[0] * 255, p[1] * 255, p[2] * 255], a: p.length > 3 ? p[3] : 1 }
    }
    m = s.match(/^#([0-9a-fA-F]{6})$/)
    if (m) {
      const h = m[1]
      return { c: [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)), a: 1 }
    }
    return null
  }
  /** 自身与祖先底色按 alpha 自下而上合成 */
  const effBg = (el: Element | null): number[] | null => {
    let cur: Element | null = el
    let acc: number[] | null = null
    while (cur) {
      const p = parse(getComputedStyle(cur).backgroundColor)
      if (p && p.a > 0) {
        acc = !acc ? p.c.slice() : p.c.map((v, i) => v * p.a + acc[i] * (1 - p.a))
        if (p.a >= 1) return acc
      }
      cur = cur.parentElement
    }
    return acc
  }
  const lum = (c: number[]) => {
    const f = (v: number) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])
  }
  const contrast = (fg: number[], bg: number[]) => {
    const hi = Math.max(lum(fg), lum(bg))
    const lo = Math.min(lum(fg), lum(bg))
    return +((hi + 0.05) / (lo + 0.05)).toFixed(2)
  }
  const textContrast = (el: Element | null) => {
    if (!el) return null
    const fg = parse(getComputedStyle(el).color)
    const bg = effBg(el)
    return fg && bg ? contrast(fg.c, bg) : null
  }

  const bar = document.querySelector(arg.barSel)
  const barBgCss = bar ? getComputedStyle(bar).backgroundColor : ''
  const rows = arg.rowClasses.map((cls) => {
    const tintTd = document.querySelector(`tr.${cls} > td.el-table__cell`)
    const tintCss = tintTd ? getComputedStyle(tintTd).backgroundColor : ''
    const normTd = tintTd?.closest('.el-table')?.querySelector(`tbody tr:not(.${cls}) > td.el-table__cell`)
    const normalCss = normTd ? getComputedStyle(normTd).backgroundColor : ''
    return {
      cls,
      found: !!tintTd,
      tintCss,
      normalCss,
      differs: !!normTd && tintCss !== normalCss,
      contrast: tintTd ? textContrast(tintTd.querySelector('*') ?? tintTd) : null,
    }
  })

  return {
    barFound: !!bar,
    barClass: bar ? (bar.getAttribute('class') || '') : '',
    barBgCss,
    barAlpha: parse(barBgCss)?.a ?? 0,
    barContrast: textContrast(bar),
    rows,
  }
}

/**
 * token 级探针：某些状态（提示条 --clip/--exclude/--ok）页面上不会同时出现，
 * 直接用一个 color: var(token) 的隐形节点让 Chrome 解析出实际 rgb，
 * 再按 percent 混到基准元素有效底色上算对比度。
 */
export function tokenTintProbe(arg: { tokens: string[]; percent: number; baseSel: string }) {
  const parse = (s: string): { c: number[]; a: number } | null => {
    s = (s || '').trim()
    let m = s.match(/^rgba?\(([^)]+)\)$/)
    if (m) {
      const p = m[1].split(/[,\s/]+/).filter(Boolean).map(Number)
      if (p.length < 3 || p.some(Number.isNaN)) return null
      return { c: [p[0], p[1], p[2]], a: p.length > 3 ? p[3] : 1 }
    }
    m = s.match(/^color\(([\w-]+)([^)]+)\)$/)
    if (m) {
      const p = m[2].split(/[,\s/]+/).filter((x) => x && x !== 'none').map(Number)
      if (p.length < 3 || p.some(Number.isNaN)) return null
      return { c: [p[0] * 255, p[1] * 255, p[2] * 255], a: p.length > 3 ? p[3] : 1 }
    }
    return null
  }
  const effBg = (el: Element | null): number[] => {
    let cur: Element | null = el
    let acc: number[] | null = null
    while (cur) {
      const p = parse(getComputedStyle(cur).backgroundColor)
      if (p && p.a > 0) {
        acc = !acc ? p.c.slice() : p.c.map((v, i) => v * p.a + acc[i] * (1 - p.a))
        if (p.a >= 1) return acc
      }
      cur = cur.parentElement
    }
    return acc ?? [255, 255, 255]
  }
  const lum = (c: number[]) => {
    const f = (v: number) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])
  }
  const contrast = (fg: number[], bg: number[]) => {
    const hi = Math.max(lum(fg), lum(bg))
    const lo = Math.min(lum(fg), lum(bg))
    return +((hi + 0.05) / (lo + 0.05)).toFixed(2)
  }

  const base = document.querySelector(arg.baseSel) ?? document.body
  const baseBg = effBg(base)
  const w = arg.percent / 100
  const host = document.createElement('span')
  host.style.cssText = 'position:absolute;left:-9999px;top:0'
  base.appendChild(host)
  const tokens = arg.tokens.map((name) => {
    host.style.color = `var(${name})`
    const fg = parse(getComputedStyle(host).color)
    if (!fg) return { name, fg: '', contrast: null as number | null }
    const mix = fg.c.map((v, i) => v * w + baseBg[i] * (1 - w))
    return { name, fg: getComputedStyle(host).color, contrast: contrast(fg.c, mix) }
  })
  host.remove()
  return { baseBgCss: baseBg.map(Math.round).join(','), tokens }
}
