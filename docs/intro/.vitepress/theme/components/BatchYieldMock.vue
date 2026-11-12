<script setup lang="ts">
import { ref, computed, reactive } from 'vue'
import MockFrame from './MockFrame.vue'
import { BT_DATA } from '../data'
import { toast } from '../useUi'
const batch = ref(0)
const stages = reactive<Record<string, boolean>>({ FT: true, QA1: true, QA2: true })
const open = reactive<Record<string, boolean>>({})
const cur = computed(() => BT_DATA[batch.value])
const agg = computed(() => {
  let rows = 0, pass = 0, qaHave = 0, n = 0
  for (const k of ['FT', 'QA1', 'QA2']) {
    if (!stages[k]) continue
    n++
    rows += cur.value.phases[k].rows; pass += cur.value.phases[k].pass
    if (k !== 'FT' && cur.value.phases[k].files.length) qaHave++
  }
  return { rows, pass, qaHave, n, y: rows ? (pass / rows) * 100 : 0 }
})
function load() { toast('报表已加载（演示）· 阶段胶囊可全局过滤') }
</script>

<template>
  <MockFrame title="仪表板 · 批次良率">
    <div class="m-toolbar">
      <select v-model="batch" class="m-select"><option v-for="(b, i) in BT_DATA" :key="i" :value="i">{{ b.name }}</option></select>
      <button class="m-btn" @click="load">加载报表</button>
      <span class="grow"></span>
      <button class="m-btn" @click="toast('导出 Excel：整批结论 xlsx（演示）')">导出 Excel</button>
      <button class="m-btn" @click="toast('导出 HTML：单文件离线报表（演示）')">导出 HTML</button>
    </div>
    <div class="m-toolbar">
      <button v-for="k in ['FT', 'QA1', 'QA2']" :key="k" class="chipx" :class="{ on: stages[k] }" @click="stages[k] = !stages[k]">{{ k }} 阶段</button>
    </div>
    <div class="qchips">
      <span class="qchip" :class="agg.qaHave === 2 ? 'ok' : 'warn'">QA 数量校验 {{ agg.qaHave }}/2 通过</span>
      <span class="qchip" :class="agg.y < 90 ? 'warn' : 'ok'">{{ agg.y < 90 ? `整批良率 ${agg.y.toFixed(2)}%（目标 ≥90%）` : '整批良率达标' }}</span>
    </div>
    <div class="m-strip">
      <div class="sc"><div class="v">{{ agg.rows }}</div><div class="l">整批记录</div></div>
      <div class="sc"><div class="v">{{ agg.pass }}</div><div class="l">Pass</div></div>
      <div class="sc"><div class="v">{{ agg.rows - agg.pass }}</div><div class="l">Fail</div></div>
      <div class="sc"><div class="v">{{ agg.y.toFixed(2) }}%</div><div class="l">Yield</div></div>
      <div class="sc"><div class="v">{{ agg.n }}</div><div class="l">阶段数</div></div>
    </div>
    <div class="m-table-wrap">
      <table class="m-table">
        <thead><tr><th style="width:34px"></th><th>阶段 / 文件</th><th>记录</th><th>Pass</th><th>Yield</th><th>程序</th><th>测试日期</th></tr></thead>
        <tbody>
          <template v-for="k in ['FT', 'QA1', 'QA2']" :key="k">
            <tr v-if="stages[k]" style="cursor:pointer" @click="open[k] = !open[k]">
              <td>{{ open[k] ? '▾' : '▸' }}</td>
              <td><b>{{ k }}</b> <span class="tag mut">{{ cur.phases[k].files.length }} 文件</span></td>
              <td class="num">{{ cur.phases[k].rows }}</td><td class="num">{{ cur.phases[k].pass }}</td>
              <td class="num">{{ cur.phases[k].rows ? (cur.phases[k].pass / cur.phases[k].rows * 100).toFixed(2) + '%' : '—' }}</td>
              <td>—</td><td>—</td>
            </tr>
            <template v-if="stages[k] && open[k]">
              <tr v-for="(f, fi) in cur.phases[k].files" :key="fi">
                <td></td><td style="padding-left:26px">{{ f[0] }}</td><td class="num">{{ f[1] }}</td><td class="num">{{ f[2] }}</td>
                <td class="num">{{ (Number(f[2]) / Number(f[1]) * 100).toFixed(2) }}%</td><td>{{ f[3] }}</td><td>{{ f[4] }}</td>
              </tr>
              <tr v-if="!cur.phases[k].files.length"><td></td><td colspan="6" style="color:var(--vp-c-text-2)">该阶段无文件——QA 校验不通过的原因之一</td></tr>
            </template>
          </template>
        </tbody>
      </table>
    </div>
    <div class="m-foot"><span>阶段胶囊为全局过滤：点掉某阶段，KPI / 校验条 / 明细表同步重算。</span><span>明细行可展开元数据。</span></div>
  </MockFrame>
</template>