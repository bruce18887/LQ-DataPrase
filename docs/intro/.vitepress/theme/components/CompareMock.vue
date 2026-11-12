<script setup lang="ts">
import { ref, computed, reactive } from 'vue'
import MockFrame from './MockFrame.vue'
import { FC_FILES, FC_BASE } from '../data'
import { toast, mulberry32 } from '../useUi'
const f1 = ref(0)
const f2 = ref(3)
const thr = ref(3)
const seq = ref(10)
const rule = ref('C')
const chg = ref(30)
const ignNoLimit = ref(true)
const ignNoData = ref(true)
const view = ref('val')
const rows = computed(() => {
  const rng = mulberry32(900 + f1.value * 17 + f2.value * 31)
  return FC_BASE.map((b, i) => {
    const diffs: number[] = []
    for (let s = 0; s < (seq.value || 10); s++) diffs.push((rng() - 0.42) * 8)
    const ate = 2.2 + i * 0.3
    return { name: String(b[0]), lslA: Number(b[1]), uslA: Number(b[2]), lslB: Number(b[3]), uslB: Number(b[4]), unit: String(b[5]), diffs, ate, bench: ate * (1 + diffs[0] / 100) }
  }).filter(r => !ignNoLimit.value || (r.lslA != null && r.lslB != null))
})
const judged = computed(() => rows.value.map(r => {
  const failN = r.diffs.filter(d => Math.abs(d) > thr.value).length
  const dl = Math.abs(r.lslB - r.lslA) / Math.max(Math.abs(r.lslA), 1e-6) * 100
  const du = Math.abs(r.uslB - r.uslA) / Math.max(Math.abs(r.uslA), 1e-6) * 100
  const lf = rule.value === 'A' ? (r.lslB !== r.lslA || r.uslB !== r.uslA) : rule.value === 'B' ? (r.lslB > r.lslA || r.uslB < r.uslA) : (dl > chg.value || du > chg.value)
  return { ...r, failN, dl, du, lf, d: r.bench - r.ate, pd: ((r.bench - r.ate) / r.ate) * 100 }
}))
const sum = computed(() => {
  const units = judged.value.reduce((a, r) => a + r.diffs.length, 0)
  const over = judged.value.reduce((a, r) => a + r.failN, 0)
  const limFail = judged.value.filter(r => r.lf).length
  return { items: judged.value.length, units, over, limFail, rate: units ? (1 - over / units) * 100 : 100 }
})
</script>

<template>
  <MockFrame title="数据管理 · 文件对比（ATE vs Bench）">
    <div class="m-toolbar">
      <select v-model="f1" class="m-select"><option v-for="(f, i) in FC_FILES" :key="i" :value="i">{{ f }}</option></select>
      <span class="m-label">VS</span>
      <select v-model="f2" class="m-select"><option v-for="(f, i) in FC_FILES" :key="i" :value="i">{{ f }}</option></select>
      <label class="m-label">误差阈值 <input v-model.number="thr" type="number" min="0" max="50" class="m-input" style="width:64px"> %</label>
      <label class="m-label">对比序列 <input v-model.number="seq" type="number" min="1" max="50" class="m-input" style="width:64px"></label>
    </div>
    <div class="m-toolbar">
      <label class="m-label">Limit Diff 规则
        <select v-model="rule" class="m-select"><option value="A">A · Diff 必须为 0</option><option value="B">B · B 的 Limit 不更紧</option><option value="C">C · 变化 ≤ x%</option></select>
      </label>
      <label class="m-label">变化容差 <input v-model.number="chg" type="number" min="0" max="100" class="m-input" style="width:64px"> %</label>
      <label class="m-label"><input type="checkbox" v-model="ignNoLimit"> Ignore No Limit</label>
      <label class="m-label"><input type="checkbox" v-model="ignNoData"> Ignore No Data</label>
      <span class="grow"></span>
      <button class="m-btn" :class="{ pri: view === 'val' }" @click="view = 'val'">测试值视图</button>
      <button class="m-btn" :class="{ pri: view === 'lim' }" @click="view = 'lim'">Limit 对比视图</button>
      <button class="m-btn pri" @click="toast('对比分析完成（演示）· 判定口径见汇总卡')">分析</button>
      <button class="m-btn" @click="toast('导出对比结果 Excel（演示）')">导出 Excel</button>
    </div>
    <div class="m-strip">
      <div class="sc"><div class="v">{{ sum.items }}</div><div class="l">测试项</div></div>
      <div class="sc"><div class="v">{{ sum.units }}</div><div class="l">对比单元</div></div>
      <div class="sc"><div class="v">{{ sum.over }}</div><div class="l">超差单元</div></div>
      <div class="sc"><div class="v">{{ sum.limFail }}</div><div class="l">Limit Diff Fail</div></div>
      <div class="sc"><div class="v">{{ sum.rate.toFixed(2) }}%</div><div class="l">总体通过率</div></div>
    </div>
    <div class="m-table-wrap">
      <table class="m-table">
        <thead v-if="view === 'val'"><tr><th>Parameters</th><th>LSL A</th><th>USL A</th><th>Unit</th><th>判定</th><th>ATE</th><th>Bench</th><th>Delta</th><th>%Diff</th></tr></thead>
        <thead v-else><tr><th>Parameters</th><th>LSL A</th><th>LSL B</th><th>USL A</th><th>USL B</th><th>ΔLSL%</th><th>ΔUSL%</th><th>Limit 判定</th></tr></thead>
        <tbody>
          <tr v-for="r in judged" :key="r.name">
            <template v-if="view === 'val'">
              <td>{{ r.name }}</td><td class="num">{{ r.lslA }}</td><td class="num">{{ r.uslA }}</td><td>{{ r.unit }}</td>
              <td><span class="tag" :class="r.failN ? 'err' : 'ok'">{{ r.failN ? '超差 ' + r.failN : '通过' }}</span></td>
              <td class="num">{{ r.ate.toFixed(4) }}</td><td class="num">{{ r.bench.toFixed(4) }}</td><td class="num">{{ r.d.toFixed(4) }}</td><td class="num">{{ r.pd.toFixed(2) }}%</td>
            </template>
            <template v-else>
              <td>{{ r.name }}</td><td class="num">{{ r.lslA }}</td><td class="num">{{ r.lslB }}</td><td class="num">{{ r.uslA }}</td><td class="num">{{ r.uslB }}</td>
              <td class="num">{{ r.dl.toFixed(1) }}%</td><td class="num">{{ r.du.toFixed(1) }}%</td>
              <td><span class="tag" :class="r.lf ? 'err' : 'ok'">{{ r.lf ? 'Limit Diff Fail' : '通过' }}</span></td>
            </template>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="m-foot">改阈值 / 规则 / 容差即时重算。规则 C 为双侧容差——LSL 与 USL 各自的变化百分比都要 ≤ 容差。</div>
  </MockFrame>
</template>