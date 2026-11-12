<script setup lang="ts">
import { ref, computed } from 'vue'
import MockFrame from './MockFrame.vue'
import { GG_FILES } from '../data'
import { toast, mulberry32 } from '../useUi'
const slots = ref<string[]>(['DEMO_FT_LOTA.csv', 'DEMO_FT_LOTB.csv', '', '', '', '', '', ''])
const bin1 = ref(true)
const nolimit = ref(true)
const out = ref<{ site: number; file: string; m: number; s: number }[] | null>(null)
const n = computed(() => slots.value.filter(Boolean).length)
function gen() {
  out.value = slots.value.map((f, i) => ({ f, i })).filter(x => x.f).map(x => {
    const rng = mulberry32(500 + (x.i + 1) * 7)
    return { site: x.i + 1, file: x.f, m: 2.2 + (rng() - 0.5) * 0.1, s: 0.05 + rng() * 0.06 }
  })
  toast('Gage Summary 已生成（演示）· 读 Site 间 STD 差异判断量测稳定性')
}
</script>

<template>
  <MockFrame title="数据管理 · Gage Summary">
    <div class="slotgrid">
      <div v-for="(s, i) in slots" :key="i" class="slot">
        <div class="sl">_S{{ i + 1 }}</div>
        <select v-model="slots[i]" class="m-select"><option value="">（空）</option><option v-for="f in GG_FILES" :key="f" :value="f">{{ f }}</option></select>
      </div>
    </div>
    <div class="m-toolbar" style="margin-top:12px">
      <label class="m-label"><input type="checkbox" v-model="bin1"> 只选 Bin1</label>
      <label class="m-label"><input type="checkbox" v-model="nolimit"> 忽略无 Limit</label>
      <span class="grow"></span>
      <button class="m-btn pri" :disabled="n < 2" @click="gen">生成 Gage Summary</button>
      <button class="m-btn" :disabled="!out" @click="toast('下载 gage_summary.xlsx（演示）')">下载 xlsx</button>
    </div>
    <div v-if="out" class="m-table-wrap" style="margin-top:12px">
      <table class="m-table">
        <thead><tr><th>Site</th><th>文件</th><th>N</th><th>Mean</th><th>STD</th><th>极差</th></tr></thead>
        <tbody><tr v-for="r in out" :key="r.site"><td>_S{{ r.site }}</td><td>{{ r.file }}</td><td class="num">100</td><td class="num">{{ r.m.toFixed(4) }}</td><td class="num">{{ r.s.toFixed(4) }}</td><td class="num">{{ (r.s * 5.2).toFixed(4) }}</td></tr></tbody>
      </table>
    </div>
    <div class="m-foot">8 个 Site 槽位（_S1…_S8）各选一份文件（同一文件可复用到多个槽位）；≥2 个槽位有文件才可生成。</div>
  </MockFrame>
</template>