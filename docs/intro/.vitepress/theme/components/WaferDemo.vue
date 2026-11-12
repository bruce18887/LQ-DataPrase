<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { WF_DIES } from '../data'
import { svgEl, cssVar } from '../charts'
import { useThemeRedraw } from '../useUi'
const mode = ref('pf')
const zone = ref(true)
const notch = ref(true)
const param = ref(0)
const svg = ref<SVGSVGElement | null>(null)
const dies = computed(() => WF_DIES.map((d, i) => ({ ...d, val: d.val + param.value * 0.15 * Math.sin(i), fail: d.fail || (param.value === 2 && d.r > 0.8 && i % 5 === 0) })))
const zones = computed(() => [['中心区', 0, 0.4], ['中间区', 0.4, 0.75], ['边缘区', 0.75, 1.01]].map(z => {
  const ds = dies.value.filter(d => d.r >= z[1] && d.r < z[2])
  const pass = ds.filter(d => !d.fail).length
  return { name: z[0], n: ds.length, pass, y: ds.length ? (pass / ds.length) * 100 : 0 }
}))
const insight = computed(() => {
  const ys = zones.value.map(z => z.y)
  const range = Math.max(...ys) - Math.min(...ys)
  const total = dies.value.length, pass = dies.value.filter(d => !d.fail).length
  return `${total} die / ${pass} Pass / 良率 ${((pass / total) * 100).toFixed(1)}% · 三环带良率 ${Math.min(...ys).toFixed(1)}% ~ ${Math.max(...ys).toFixed(1)}%，极差 ${range.toFixed(1)} 个百分点 → ${range > 10 ? '存在径向梯度，可按环带下钻' : '环带分布均匀'}`
})
function color(d: { fail: boolean; site: number; bin: number; val: number }) {
  if (mode.value === 'pf') return d.fail ? cssVar('--intro-err') : cssVar('--intro-ok')
  if (mode.value === 'site') return [cssVar('--vp-c-brand-1'), cssVar('--intro-info'), cssVar('--intro-violet'), cssVar('--intro-warn')][d.site - 1]
  if (mode.value === 'bin') return d.bin === 1 ? cssVar('--intro-ok') : d.bin === 2 ? cssVar('--intro-err') : d.bin === 3 ? cssVar('--intro-warn') : cssVar('--intro-violet')
  const t = Math.max(0, Math.min(1, (d.val - 1.8) / 1.8))
  return `color-mix(in srgb, ${cssVar('--intro-err')} ${Math.round(t * 100)}%, ${cssVar('--vp-c-brand-1')})`
}
function draw() {
  const el = svg.value
  if (!el) return
  while (el.firstChild) el.removeChild(el.firstChild)
  if (notch.value) {
    el.appendChild(svgEl('circle', { cx: 160, cy: 160, r: 146, fill: 'none', stroke: cssVar('--vp-c-text-2'), 'stroke-width': 1.4 }))
    el.appendChild(svgEl('path', { d: 'M152 306 L160 296 L168 306 Z', fill: cssVar('--vp-c-text-2') }))
  }
  if (zone.value) for (const t of [0.4, 0.75]) el.appendChild(svgEl('circle', { cx: 160, cy: 160, r: 138 * t, fill: 'none', stroke: cssVar('--vp-c-text-2'), 'stroke-width': 1, 'stroke-dasharray': '4 4', opacity: 0.7 }))
  for (const d of dies.value) el.appendChild(svgEl('rect', { x: d.x - 5.5, y: d.y - 5.5, width: 11, height: 11, rx: 2, fill: color(d), opacity: 0.92 }))
}
watch([mode, zone, notch, param], draw)
onMounted(draw)
useThemeRedraw(draw)
defineExpose({ redraw: draw })
</script>

<template>
  <div class="intro-note" style="border-left-color:var(--vp-c-border);background:var(--vp-c-bg);padding:16px">
    <div class="demo-controls">
      <label>着色 <select v-model="mode"><option value="pf">判定结果</option><option value="site">Site</option><option value="bin">Bin</option><option value="val">参数值</option></select></label>
      <label><input type="checkbox" v-model="zone"> 三环分区</label>
      <label><input type="checkbox" v-model="notch"> 边界圆 + Notch</label>
      <label>参数 <select v-model.number="param"><option :value="0">RCONT_01</option><option :value="1">VREF_TRIM</option><option :value="2">IBIAS_TRIM</option></select></label>
    </div>
    <div class="wafer-flex">
      <svg ref="svg" viewBox="0 0 320 320" class="demo-svg" role="img" aria-label="交互演示晶圆图"></svg>
      <div>
        <div class="m-table-wrap">
          <table class="m-table">
            <thead><tr><th>环带</th><th>die</th><th>Pass</th><th>良率</th></tr></thead>
            <tbody><tr v-for="z in zones" :key="z.name"><td>{{ z.name }}</td><td class="num">{{ z.n }}</td><td class="num">{{ z.pass }}</td><td class="num">{{ z.y.toFixed(1) }}%</td></tr></tbody>
          </table>
        </div>
        <div class="intro-note" style="margin-top:12px"><b>{{ insight }}</b></div>
        <div class="m-foot">数据筛选不影响晶圆图：它始终画全部 die；未选参数时按全部测试项限值判 Fail。切换着色与参数观察图案变化（合成 die 阵）。</div>
      </div>
    </div>
  </div>
</template>