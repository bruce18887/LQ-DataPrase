<script setup lang="ts">
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import MockFrame from './MockFrame.vue'
import { EX_PARAMS } from '../data'
import { toast, mulberry32, normalGen, useThemeRedraw } from '../useUi'
import { miniHist } from '../charts'
const step = ref(0)
const q = ref('')
const sel = reactive<Record<string, boolean>>({ RCONT_01: true, VREF_TRIM: true, IBIAS_TRIM: true, OSC_CAL: true, DAC_GAIN: true, ADC_OFF: true })
import { reactive } from 'vue'
const cfg = reactive({ limit: true, s3: false, s4: false, s6: true, normal: false, kde: true, nolimit: false, barwidth: 80 })
const sigma = ref(6)
const job = ref(0)
const jobLabel = ref('空闲')
const jobKind = ref('')
let timer: ReturnType<typeof setInterval> | null = null
const selList = computed(() => EX_PARAMS.filter(p => sel[p]))
const visParams = computed(() => EX_PARAMS.filter(p => !q.value || p.toLowerCase().includes(q.value.toLowerCase())))
const preview = ref<SVGSVGElement | null>(null)
function drawPreview() {
  if (!preview.value) return
  const n = normalGen(mulberry32(20261112))
  const vals: number[] = []
  for (let i = 0; i < 400; i++) vals.push(2.2 + 0.72 * n())
  miniHist(preview.value, vals, { bins: 22, barwidth: cfg.barwidth, limits: cfg.limit, lo: 0, hi: 4, sigma: { 3: cfg.s3, 4: cfg.s4, 6: cfg.s6 }, kde: cfg.kde, normal: cfg.normal && !cfg.kde })
}
watch([step, cfg], () => { if (step.value === 1) nextTick(drawPreview) }, { deep: true })
onMounted(() => { if (step.value === 1) drawPreview() })
useThemeRedraw(() => { if (step.value === 1) drawPreview() })
const sigRows = computed(() => selList.value.slice(0, 5).map((p, i) => {
  const m = 2.2 + i * 0.35, s = 0.5 + i * 0.07
  return { p, m, s, lo: m - sigma.value * s, hi: m + sigma.value * s }
}))
function runJob(kind: string) {
  if (timer) return
  jobKind.value = kind
  jobLabel.value = kind + ' 作业运行中…'
  job.value = 0
  timer = setInterval(() => {
    job.value = Math.min(100, job.value + 7 + Math.random() * 9)
    if (job.value >= 100) {
      clearInterval(timer!); timer = null
      jobLabel.value = kind + ' 完成 · 可下载'
      toast(`${kind} 后台作业完成（演示）· ${selList.value.length} 张直方图`)
    }
  }, 160)
}
function dl() { toast('下载产物（演示）· 真实应用为 xlsx / pptx 文件'); job.value = 0; jobLabel.value = '空闲' }
</script>

<template>
  <MockFrame title="数据管理 · 导出工具（三步向导）">
    <div class="m-toolbar">
      <button v-for="(t, i) in ['1 选择参数', '2 图表配置', '3 导出']" :key="i" class="chipx" :class="{ on: step === i }" @click="step = i">{{ t }}</button>
    </div>
    <div v-if="step === 0">
      <div class="m-toolbar">
        <input v-model="q" class="m-input" placeholder="搜索测试项" style="width:200px">
        <button class="m-btn" @click="EX_PARAMS.forEach(p => sel[p] = true)">全选</button>
        <button class="m-btn" @click="Object.keys(sel).forEach(k => sel[k] = false)">清空</button>
        <span class="grow"></span><span class="m-label">已选 {{ selList.length }} / 共 {{ EX_PARAMS.length }} 个</span>
      </div>
      <div class="chips">
        <button v-for="p in visParams" :key="p" class="chipx" :class="{ on: sel[p] }" @click="sel[p] = !sel[p]">{{ p }}<span v-if="sel[p]" style="opacity:.6;font-weight:700">×</span></button>
      </div>
    </div>
    <div v-if="step === 1">
      <div class="demo-controls">
        <label><input type="checkbox" v-model="cfg.limit"> Limit</label>
        <label><input type="checkbox" v-model="cfg.s3"> 3σ</label>
        <label><input type="checkbox" v-model="cfg.s4"> 4σ</label>
        <label><input type="checkbox" v-model="cfg.s6"> 6σ</label>
        <label><input type="checkbox" v-model="cfg.normal"> 正态曲线</label>
        <label><input type="checkbox" v-model="cfg.kde"> KDE</label>
        <label><input type="checkbox" v-model="cfg.nolimit"> 忽略无 Limit</label>
        <label>柱宽 <input type="range" min="10" max="100" v-model.number="cfg.barwidth"><span>{{ cfg.barwidth }}%</span></label>
      </div>
      <svg ref="preview" viewBox="0 0 760 240" class="demo-svg" role="img" aria-label="导出图表配置实时预览"></svg>
      <div class="m-foot">预览即导出口径：叠层开关与柱宽实时反映到批量导出的每张直方图。</div>
    </div>
    <div v-if="step === 2">
      <div class="m-toolbar">
        <label class="m-label">Sigma 范围
          <select v-model.number="sigma" class="m-select"><option :value="3">3σ</option><option :value="4">4σ</option><option :value="6">6σ</option></select>
        </label>
        <span class="m-label">导出 Sigma Limit 同步写入 xlsx</span>
      </div>
      <div class="m-table-wrap" style="margin-bottom:12px">
        <table class="m-table">
          <thead><tr><th>参数</th><th>Mean</th><th>STD</th><th>{{ sigma }}σ Low</th><th>{{ sigma }}σ High</th></tr></thead>
          <tbody><tr v-for="r in sigRows" :key="r.p"><td>{{ r.p }}</td><td class="num">{{ r.m.toFixed(4) }}</td><td class="num">{{ r.s.toFixed(4) }}</td><td class="num">{{ r.lo.toFixed(4) }}</td><td class="num">{{ r.hi.toFixed(4) }}</td></tr></tbody>
        </table>
      </div>
      <div class="m-toolbar">
        <button class="m-btn pri" :disabled="!!timer" @click="runJob('Excel')">批量导出 Excel</button>
        <button class="m-btn pri" :disabled="!!timer" @click="runJob('PPT')">批量导出 PPT</button>
        <div class="jobbar"><i :style="{ width: job + '%' }"></i></div>
        <span class="m-label">{{ jobLabel }}</span>
        <button class="m-btn" :disabled="job < 100" @click="dl">下载产物</button>
      </div>
      <div class="m-foot">真实应用中作业在后台队列执行，进度以 JobProgressChip 显示在按钮旁，页面可继续操作；<b>没有独立的「导出中心」页面</b>。</div>
    </div>
    <div style="display:flex;justify-content:space-between;margin-top:16px">
      <button class="m-btn" :disabled="step === 0" @click="step--">上一步</button>
      <button class="m-btn" :disabled="step === 2" @click="step++">下一步</button>
    </div>
  </MockFrame>
</template>