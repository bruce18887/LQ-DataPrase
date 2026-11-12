<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { CORR_P, CORR_M } from '../data'
import { svgEl, cssVar } from '../charts'
import { mulberry32, normalGen, mean, sd, useThemeRedraw } from '../useUi'
const sel = ref<[number, number]>([0, 7])
const scatter = ref<SVGSVGElement | null>(null)
function cellColor(r: number) {
  const t = Math.round(Math.abs(r) * 100)
  return r >= 0 ? `color-mix(in srgb, #dc2626 ${t}%, #ffffff)` : `color-mix(in srgb, #2563eb ${t}%, #ffffff)`
}
const info = computed(() => {
  const [i, j] = sel.value
  const r = CORR_M[i][j]
  return `${CORR_P[i]} × ${CORR_P[j]} · r = ${r.toFixed(2)} · ${Math.abs(r) > 0.7 ? '强联动' : Math.abs(r) > 0.4 ? '中等联动' : '弱联动'}（合成散点 + 最小二乘拟合线）`
})
import { computed } from 'vue'
function draw() {
  const el = scatter.value
  if (!el) return
  while (el.firstChild) el.removeChild(el.firstChild)
  const [i, j] = sel.value
  const r = CORR_M[i][j]
  const n = normalGen(mulberry32(1000 + i * 8 + j))
  const pts: [number, number][] = []
  for (let k = 0; k < 60; k++) { const x = n(); pts.push([x, r * x + Math.sqrt(Math.max(0, 1 - r * r)) * n()]) }
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1])
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys)
  const W = 360, H = 260, mL = 34, mB = 26, iw = W - mL - 12, ih = H - mB - 14
  const X = (v: number) => mL + ((v - x0) / (x1 - x0)) * iw
  const Y = (v: number) => 14 + ih - ((v - y0) / (y1 - y0)) * ih
  el.appendChild(svgEl('line', { x1: mL, x2: W - 12, y1: 14 + ih, y2: 14 + ih, stroke: cssVar('--vp-c-border') }))
  el.appendChild(svgEl('line', { x1: mL, x2: mL, y1: 14, y2: 14 + ih, stroke: cssVar('--vp-c-border') }))
  for (const p of pts) el.appendChild(svgEl('circle', { cx: X(p[0]), cy: Y(p[1]), r: 3, fill: cssVar('--vp-c-brand-1'), opacity: 0.75 }))
  const mx = mean(xs), my = mean(ys), slope = r * (sd(ys) / sd(xs))
  el.appendChild(svgEl('line', { x1: X(x0), y1: Y(my + slope * (x0 - mx)), x2: X(x1), y2: Y(my + slope * (x1 - mx)), stroke: cssVar('--intro-err'), 'stroke-width': 2 }))
  const lb = svgEl('text', { x: W - 16, y: 26, 'text-anchor': 'end', 'font-size': 12, 'font-weight': 700, fill: cssVar('--vp-c-text-1') })
  lb.textContent = 'r = ' + r.toFixed(2)
  el.appendChild(lb)
}
watch(sel, draw)
onMounted(draw)
useThemeRedraw(draw)
defineExpose({ redraw: draw })
</script>

<template>
  <div class="intro-note" style="border-left-color:var(--vp-c-border);background:var(--vp-c-bg);padding:16px">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px" class="corr-wrap">
      <div class="corr-grid">
        <div class="ch"></div>
        <div v-for="p in CORR_P" :key="'h' + p" class="ch">{{ p }}</div>
        <template v-for="(row, i) in CORR_M" :key="i">
          <div class="ch">{{ CORR_P[i] }}</div>
          <button v-for="(r, j) in row" :key="j" class="cc" :class="{ sel: (sel[0] === i && sel[1] === j) || (sel[0] === j && sel[1] === i) }"
            :style="{ background: cellColor(r), color: Math.abs(r) > 0.5 ? '#fff' : '#17233b' }"
            :title="`${CORR_P[i]} × ${CORR_P[j]} · r=${r.toFixed(2)}`" @click="sel = [i, j]">{{ r.toFixed(2).replace('0.', '.') }}</button>
        </template>
      </div>
      <div>
        <svg ref="scatter" viewBox="0 0 360 260" class="demo-svg" role="img" aria-label="参数对散点与拟合线"></svg>
        <div class="m-foot"><b>{{ info }}</b> · 点击左侧任意矩阵格切换参数对。</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
@media (max-width: 960px) { .corr-wrap { grid-template-columns: 1fr !important; } }
</style>