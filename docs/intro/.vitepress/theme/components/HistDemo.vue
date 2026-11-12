<script setup lang="ts">
import { ref, reactive, watch, onMounted, computed } from 'vue'
import { toast, dialog, openCtx, download, mulberry32, normalGen, mean, sd, quantile, gradeOf, useThemeRedraw } from '../useUi'
import { svgEl, cssVar, miniHist } from '../charts'
const c = reactive({ bins: 24, n: 560, out: 10, shift: 0, mult: 1.5, clip: false, limits: true, kde: true, normal: false })
const seed = ref(20261112)
const brush = ref<[number, number] | null>(null)
const svg = ref<SVGSVGElement | null>(null)
const data = computed(() => {
  const n = normalGen(mulberry32(seed.value))
  const arr: number[] = []
  for (let i = 0; i < c.n; i++) arr.push(2.2 + c.shift + 0.72 * n())
  const rng = mulberry32(seed.value ^ 0x9e37)
  for (let j = 0; j < c.out; j++) arr.push(5.6 + rng() * 3.4)
  return arr
})
const stats = computed(() => {
  const sorted = [...data.value].sort((a, b) => a - b)
  const q1 = quantile(sorted, 0.25), q3 = quantile(sorted, 0.75), iqr = q3 - q1
  const loF = q1 - c.mult * iqr, hiF = q3 + c.mult * iqr
  const used = c.clip ? data.value.filter(v => v >= loF && v <= hiF) : [...data.value]
  const m = mean(used), s = sd(used)
  return { used, removed: data.value.length - used.length, m, s, cpk: Math.min(4 - m, m - 0) / (3 * s), loF, hiF }
})
const subset = computed(() => {
  if (!brush.value) return null
  const sub = stats.value.used.filter(v => v >= brush.value![0] && v <= brush.value![1])
  if (sub.length <= 2) return { n: sub.length, tooFew: true }
  const m = mean(sub), s = sd(sub)
  return { n: sub.length, m, s, cpk: Math.min(4 - m, m - 0) / (3 * s), tooFew: false }
})
let geom = { x0: 0, x1: 1, mL: 46, iw: 698 }
function draw() {
  const el = svg.value
  if (!el) return
  while (el.firstChild) el.removeChild(el.firstChild)
  const { used, m, s } = stats.value
  const dmin = Math.min(...used), dmax = Math.max(...used)
  const pad = (dmax - dmin) * 0.04 || 1, x0 = dmin - pad, x1 = dmax + pad
  const W = 760, H = 320, mL = 46, mR = 16, mT = 18, mB = 34, iw = W - mL - mR, ih = H - mT - mB, bw = (x1 - x0) / c.bins
  geom = { x0, x1, mL, iw }
  const counts = new Array(c.bins).fill(0)
  used.forEach(v => { counts[Math.min(c.bins - 1, Math.floor((v - x0) / bw))]++ })
  const maxC = Math.max(...counts)
  const X = (v: number) => mL + ((v - x0) / (x1 - x0)) * iw
  const Y = (cc: number) => mT + ih - (cc / maxC) * ih
  const border = cssVar('--vp-c-border'), text2 = cssVar('--vp-c-text-2'), accent = cssVar('--vp-c-brand-1')
  for (let g = 0; g <= 4; g++) {
    const cy = mT + ih - (g / 4) * ih
    el.appendChild(svgEl('line', { x1: mL, x2: W - mR, y1: cy, y2: cy, stroke: border, 'stroke-width': 1 }))
    const tl = svgEl('text', { x: mL - 8, y: cy + 4, 'text-anchor': 'end', 'font-size': 10, fill: text2 })
    tl.textContent = String(Math.round((maxC * g) / 4)); el.appendChild(tl)
  }
  const gap = Math.max(1, (iw / c.bins) * 0.12)
  counts.forEach((cc, b) => el.appendChild(svgEl('rect', { x: X(x0 + b * bw) + gap / 2, y: Y(cc), width: Math.max(1, iw / c.bins - gap), height: Math.max(0, mT + ih - Y(cc)), fill: accent, opacity: 0.82, rx: 1.5 })))
  if (c.limits) for (const [v, lab] of [[0, 'LSL'], [4, 'USL']] as [number, string][]) {
    if (v < x0 || v > x1) continue
    el.appendChild(svgEl('line', { x1: X(v), x2: X(v), y1: mT, y2: mT + ih, stroke: cssVar('--intro-err'), 'stroke-width': 2, 'stroke-dasharray': '6 4' }))
    const t = svgEl('text', { x: X(v), y: mT - 4, 'text-anchor': 'middle', 'font-size': 11, fill: cssVar('--intro-err'), 'font-weight': 700 })
    t.textContent = lab; el.appendChild(t)
  }
  const curve = (kind: string) => {
    const h = 1.06 * s * Math.pow(used.length, -0.2) || 0.3
    const pts: string[] = []
    for (let q = 0; q <= 120; q++) {
      const xv = x0 + ((x1 - x0) * q) / 120
      let d: number
      if (kind === 'kde') {
        d = 0
        for (let z = 0; z < used.length; z++) { const u = (xv - used[z]) / h; d += Math.exp(-0.5 * u * u) }
        d /= used.length * h * Math.sqrt(2 * Math.PI)
      } else d = Math.exp(-0.5 * Math.pow((xv - m) / s, 2)) / (s * Math.sqrt(2 * Math.PI))
      const yv = mT + ih - ((d * used.length * bw) / maxC) * ih
      pts.push((q ? 'L' : 'M') + X(xv).toFixed(1) + ' ' + Math.max(mT, yv).toFixed(1))
    }
    el.appendChild(svgEl('path', { d: pts.join(''), fill: 'none', stroke: kind === 'kde' ? cssVar('--intro-violet') : cssVar('--intro-ok'), 'stroke-width': 2.2, opacity: 0.9 }))
  }
  if (c.kde) curve('kde')
  if (c.normal) curve('normal')
  for (let tI = 0; tI <= 6; tI++) {
    const xv2 = x0 + ((x1 - x0) * tI) / 6
    const tx = svgEl('text', { x: X(xv2), y: H - 10, 'text-anchor': 'middle', 'font-size': 10, fill: text2 })
    tx.textContent = xv2.toFixed(1); el.appendChild(tx)
  }
  if (brush.value) {
    const bx0 = X(Math.max(x0, brush.value[0])), bx1 = X(Math.min(x1, brush.value[1]))
    el.appendChild(svgEl('rect', { x: Math.min(bx0, bx1), y: mT, width: Math.abs(bx1 - bx0), height: ih, fill: cssVar('--intro-violet'), opacity: 0.16, stroke: cssVar('--intro-violet'), 'stroke-width': 1.4, 'stroke-dasharray': '4 3' }))
  }
}
watch([c, seed, brush], () => draw(), { deep: true })
onMounted(draw)
useThemeRedraw(draw)
defineExpose({ redraw: draw })
let drag: number | null = null
let rect: SVGRectElement | null = null
function px(e: PointerEvent) {
  const r = svg.value!.getBoundingClientRect()
  return ((e.clientX - r.left) / r.width) * 760
}
function down(e: PointerEvent) {
  if (e.button !== 0) return
  drag = px(e)
  try { svg.value!.setPointerCapture(e.pointerId) } catch { /* 合成事件无活跃 pointer */ }
  rect = svgEl('rect', { y: 18, height: 268, fill: cssVar('--intro-violet'), opacity: 0.16, stroke: cssVar('--intro-violet'), 'stroke-width': 1.4, 'stroke-dasharray': '4 3' }) as SVGRectElement
  svg.value!.appendChild(rect)
}
function move(e: PointerEvent) {
  if (drag == null || !rect) return
  const x = px(e)
  rect.setAttribute('x', String(Math.min(drag, x)))
  rect.setAttribute('width', String(Math.abs(x - drag)))
}
function up(e: PointerEvent) {
  if (drag == null) return
  const x = px(e), a = Math.min(drag, x), b = Math.max(drag, x)
  drag = null
  if (rect) { rect.remove(); rect = null }
  if (b - a < 6) { brush.value = null; return }
  brush.value = [geom.x0 + ((a - geom.mL) / geom.iw) * (geom.x1 - geom.x0), geom.x0 + ((b - geom.mL) / geom.iw) * (geom.x1 - geom.x0)]
}
function ctx(e: MouseEvent) {
  e.preventDefault()
  openCtx(e.clientX, e.clientY, [
    { label: '新建子集直方图', fn: () => {
      if (!brush.value) { toast('先按住左键拖框选择区间', 'warn'); return }
      const sub = data.value.filter(v => v >= brush.value![0] && v <= brush.value![1])
      dialog('子集直方图', `<svg id="hd-subhist" viewBox="0 0 520 240" style="width:100%;height:auto"></svg><p>子集 N ${sub.length}（平台中子集面板独立于原图过滤口径）</p>`)
      requestAnimationFrame(() => { const el = document.getElementById('hd-subhist') as unknown as SVGSVGElement; if (el && sub.length > 2) miniHist(el, sub, { limits: true, lo: 0, hi: 4, kde: true, bins: 14 }) })
    } },
    { label: '清除选择', fn: () => { brush.value = null } },
  ])
}
function rand() { seed.value = (Math.random() * 1e9) | 0; brush.value = null; toast('已换随机种子（演示样本重生成）') }
function reset() {
  seed.value = 20261112; brush.value = null
  Object.assign(c, { bins: 24, n: 560, out: 10, shift: 0, mult: 1.5, clip: false, limits: true, kde: true, normal: false })
}
function exportSvg() {
  const clone = svg.value!.cloneNode(true) as SVGSVGElement
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  download('hist-demo.svg', clone.outerHTML, 'image/svg+xml')
  toast('当前直方图已导出 SVG（含框选与叠层状态）')
}
</script>

<template>
  <div class="intro-note" style="border-left-color:var(--vp-c-border);background:var(--vp-c-bg);padding:16px">
    <div class="demo-controls">
      <label>分箱数 <input type="range" min="8" max="60" v-model.number="c.bins"><span>{{ c.bins }}</span></label>
      <label>样本量 <input type="range" min="200" max="1200" step="40" v-model.number="c.n"><span>{{ c.n }}</span></label>
      <label>离群点 <input type="range" min="0" max="40" v-model.number="c.out"><span>{{ c.out }}</span></label>
      <label>均值偏移 <input type="range" min="-1" max="1" step="0.1" v-model.number="c.shift"><span>{{ c.shift.toFixed(1) }}</span></label>
      <label>敏感度 <select v-model.number="c.mult"><option :value="1.5">严格 1.5×IQR</option><option :value="3">宽松 3.0×IQR</option></select></label>
      <label><input type="checkbox" v-model="c.clip"> IQR 裁剪</label>
      <label><input type="checkbox" v-model="c.limits"> 规格限</label>
      <label><input type="checkbox" v-model="c.kde"> KDE 曲线</label>
      <label><input type="checkbox" v-model="c.normal"> 正态曲线</label>
      <button class="m-btn" @click="rand">随机种子</button>
      <button class="m-btn" @click="reset">重置</button>
      <button class="m-btn" @click="exportSvg">导出 SVG</button>
    </div>
    <svg id="hist-svg" ref="svg" viewBox="0 0 760 320" class="demo-svg" role="img" aria-label="交互演示直方图：可拖框选子集"
      @pointerdown="down" @pointermove="move" @pointerup="up" @contextmenu="ctx"></svg>
    <div class="demo-stats">
      <div class="st"><div class="v">{{ stats.used.length }}</div><div class="l">N</div></div>
      <div class="st"><div class="v">{{ stats.m.toFixed(4) }}</div><div class="l">Mean</div></div>
      <div class="st"><div class="v">{{ stats.s.toFixed(4) }}</div><div class="l">STD</div></div>
      <div class="st"><div class="v">{{ stats.cpk.toFixed(4) }}</div><div class="l">CPK</div></div>
      <div class="st"><div class="v">{{ gradeOf(stats.cpk) }} 级</div><div class="l">分级</div></div>
      <div class="st"><div class="v">{{ stats.removed }} 点</div><div class="l">裁剪剔除</div></div>
    </div>
    <div v-if="brush" class="subset-panel">
      <template v-if="subset && !subset.tooFew">
        <b>框选子集</b> [{{ brush[0].toFixed(2) }}, {{ brush[1].toFixed(2) }}] · N {{ subset.n }} · Mean {{ subset.m!.toFixed(4) }} · STD {{ subset.s!.toFixed(4) }} · CPK {{ subset.cpk!.toFixed(4) }}（{{ gradeOf(subset.cpk!) }} 级） · 规格限 [0, 4]
      </template>
      <template v-else><b>框选子集</b>：区间内样本不足（需 &gt;2）。</template>
      <button class="m-btn" style="margin-left:10px;padding:2px 10px" @click="brush = null">清除选择</button>
    </div>
    <div class="intro-note" style="margin-bottom:0">
      {{ c.clip ? `已按 ${c.mult}×IQR 裁剪：围栏 [${stats.loF.toFixed(2)}, ${stats.hiF.toFixed(2)}]，剔除 ${stats.removed} 个离群点。对比开关前后的 CPK——这就是平台「异常值处理」的口径。` : '未裁剪：离群点把 STD 拉大、CPK 压低。勾选「IQR 裁剪」看剔除后的变化；在图上拖框可框选子集（默认阈值 A≥1.67 / B≥1.33 / C≥1.0）。' }}
    </div>
  </div>
</template>