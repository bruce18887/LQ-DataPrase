<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { WT_DEFAULT } from '../data'
import { toast, download, mean, useThemeRedraw } from '../useUi'
import { svgEl, cssVar } from '../charts'
const src = ref(WT_DEFAULT)
const showMean = ref(true)
const on = reactive<Record<string, boolean>>({})
import { reactive } from 'vue'
const groups = computed(() => {
  const re = /double\s+([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]\s*=\s*\{([^}]*)\}/g
  const out: Record<string, number[][]> = {}
  let m: RegExpExecArray | null
  while ((m = re.exec(src.value))) {
    const vals = m[3].split(',').map(s => parseFloat(s.trim())).filter(v => Number.isFinite(v))
    if (!vals.length) continue
    ;(out[m[1]] = out[m[1]] || []).push(vals)
  }
  return out
})
const names = computed(() => Object.keys(groups.value))
watch(names, ns => ns.forEach(n => { if (on[n] === undefined) on[n] = true }))
onMounted(() => names.value.forEach(n => { if (on[n] === undefined) on[n] = true }))
const seriesCount = computed(() => names.value.filter(n => on[n]).reduce((a, n) => a + groups.value[n].length, 0))
function drawCard(el: SVGSVGElement, gs: number[][]) {
  while (el.firstChild) el.removeChild(el.firstChild)
  const all = gs.flat()
  let lo = Math.min(...all), hi = Math.max(...all)
  const pad = (hi - lo) * 0.1 || 1
  lo -= pad; hi += pad
  const npts = Math.max(...gs.map(g => g.length))
  const X = (i: number) => 8 + (i / Math.max(1, npts - 1)) * 204
  const Y = (v: number) => 8 + (1 - (v - lo) / (hi - lo)) * 104
  const colors = [cssVar('--vp-c-brand-1'), cssVar('--intro-info'), cssVar('--intro-violet'), cssVar('--intro-warn')]
  const dashes = ['', '5 3', '1.5 3', '8 3 2 3']
  el.appendChild(svgEl('line', { x1: 8, x2: 212, y1: 112, y2: 112, stroke: cssVar('--vp-c-border') }))
  gs.forEach((g, si) => {
    el.appendChild(svgEl('path', { d: g.map((v, i) => (i ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(v).toFixed(1)).join(''), fill: 'none', stroke: colors[si % 4], 'stroke-width': 1.6, 'stroke-dasharray': dashes[si % 4] || 'none', opacity: 0.9 }))
  })
  if (showMean.value && gs.length) {
    const line: [number, number][] = []
    for (let i = 0; i < npts; i++) {
      const vals = gs.map(g => g[i]).filter(v => v != null)
      if (vals.length) line.push([i, mean(vals)])
    }
    el.appendChild(svgEl('path', { d: line.map((p, i) => (i ? 'L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1)).join(''), fill: 'none', stroke: cssVar('--vp-c-text-2'), 'stroke-width': 1.2, 'stroke-dasharray': '3 3' }))
  }
}
const cards = ref<Record<string, SVGSVGElement | null>>({})
function setCard(n: string) { return (el: unknown) => { cards.value[n] = el as SVGSVGElement | null; if (el) drawCard(el as SVGSVGElement, groups.value[n]) } }
watch([groups, on, showMean], () => { for (const n of names.value) if (on[n] && cards.value[n]) drawCard(cards.value[n]!, groups.value[n]) }, { deep: true })
useThemeRedraw(() => { for (const n of names.value) if (on[n] && cards.value[n]) drawCard(cards.value[n]!, groups.value[n]) })
function exportCsv() {
  const rows = ['test_item,series,code,value']
  for (const n of names.value) groups.value[n].forEach((g, si) => g.forEach((v, i) => rows.push(`${n},${si + 1},${i},${v}`)))
  download('weight-demo.csv', rows.join('\n'), 'text/csv')
  toast('权重曲线 CSV 已下载（演示导出）')
}
</script>

<template>
  <div class="intro-note" style="border-left-color:var(--vp-c-border);background:var(--vp-c-bg);padding:16px">
    <textarea v-model="src" class="m-input" spellcheck="false" aria-label="权重声明输入"></textarea>
    <div class="m-toolbar" style="margin-top:10px">
      <div class="chips">
        <button v-for="n in names" :key="n" class="chipx" :class="{ on: on[n] }" @click="on[n] = !on[n]">{{ n }}</button>
      </div>
      <span class="grow"></span>
      <label class="m-label"><input type="checkbox" v-model="showMean"> 显示均值</label>
      <button class="m-btn" @click="exportCsv">导出 CSV（演示）</button>
    </div>
    <div class="weight-grid">
      <div v-for="n in names.filter(x => on[x])" :key="n" class="wc">
        <b>{{ n }} · {{ groups[n].length }} 系列</b>
        <svg :ref="setCard(n)" viewBox="0 0 220 120"></svg>
      </div>
    </div>
    <div class="m-foot">{{ names.length ? `解析成功：${names.length} 个测试项 · ${seriesCount} 条系列曲线（同名声明自动编号）· 仅本页使用，不写入数据库` : '未解析到声明——格式：double 名称[点数] = {v1,v2,...};' }}</div>
  </div>
</template>