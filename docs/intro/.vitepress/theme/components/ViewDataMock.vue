<script setup lang="ts">
import { ref, computed, reactive } from 'vue'
import MockFrame from './MockFrame.vue'
import { VD_COLS, vdRows } from '../data'
import { toast, dialog, openCtx, download, mean, sd, cpkOf, gradeOf } from '../useUi'
import { miniHist } from '../charts'
const files = ref(['DEMO_FT_LOTD.csv', 'DEMO_FT_LOTC.csv'])
const cur = ref(0)
interface St { pf: string; site: string; width: string; sticky: boolean; cols: Record<string, boolean>; hl: Record<number, boolean> }
const st = reactive<Record<number, St>>({})
function state(i: number): St {
  if (!st[i]) st[i] = { pf: 'all', site: 'all', width: 'std', sticky: true, cols: { bin: true, rcont: true, vref: true, ibias: true, osc: true }, hl: {} }
  return st[i]
}
const s = computed(() => state(cur.value))
const rows = computed(() => vdRows(cur.value))
const vis = computed(() => rows.value.filter(r => (s.value.pf === 'all' || (s.value.pf === 'fail') === r.fail) && (s.value.site === 'all' || r.site === s.value.site)))
const cols = computed(() => VD_COLS.filter(c => !c.test || s.value.cols[c.key]))
const pad = computed(() => (s.value.width === 'compact' ? '4px 6px' : s.value.width === 'wide' ? '10px 16px' : '7px 10px'))
const pass = computed(() => rows.value.filter(r => !r.fail).length)
const y = computed(() => (pass.value / rows.value.length) * 100)
const lowCpk = computed(() => VD_COLS.filter(c => c.test && c.key !== 'bin' && cpkOf(rows.value.map(r => Number(r[c.key])), c.lo, c.hi) < 1.33).length)
const delta = computed(() => {
  const sy: Record<string, [number, number]> = {}
  rows.value.forEach(r => { const k = String(r.site); sy[k] = sy[k] || [0, 0]; sy[k][0]++; if (!r.fail) sy[k][1]++ })
  const ys = Object.values(sy).map(v => (v[1] / v[0]) * 100)
  return Math.max(...ys) - Math.min(...ys)
})
function addFile() {
  const pool = ['DEMO_FT_LOTA.csv', 'DEMO_FT_LOTB.csv', 'DEMO_CP_WAFER01.csv'].filter(x => !files.value.includes(x))
  if (pool.length) { files.value.push(pool[0]); cur.value = files.value.length - 1 }
}
function applyView(v: string) {
  if (v === 'fail') { s.value.pf = 'fail'; s.value.site = 'all' }
  if (v === 's1') { s.value.pf = 'all'; s.value.site = 'S1' }
  if (v) toast('已应用保存的视图（演示）')
}
function cellCtx(e: MouseEvent, r: Record<string, unknown>, key: string) {
  e.preventDefault()
  if (key === 'serial') {
    const serial = Number(r.serial)
    openCtx(e.clientX, e.clientY, [
      { label: s.value.hl[serial] ? '取消高亮此行' : '高亮此行', fn: () => { s.value.hl[serial] = !s.value.hl[serial] } },
      { label: '复制序列号', fn: () => toast('已复制序列号 ' + serial) },
    ])
  } else if (key === 'bin' && r.bin !== 1) {
    openCtx(e.clientX, e.clientY, [{ label: '定位到 Fail 单元格', fn: () => { s.value.pf = 'fail'; toast('已切换到仅 Fail 视图') } }])
  }
}
function headCtx(e: MouseEvent, key: string) {
  const c = VD_COLS.find(x => x.key === key)!
  if (!c.test) return
  e.preventDefault()
  openCtx(e.clientX, e.clientY, [
    { label: '复制测试项名', fn: () => { navigator.clipboard?.writeText(c.label).catch(() => {}); toast('已复制 ' + c.label) } },
    { sep: true },
    { label: '展示分布图', fn: () => {
      const vals = rows.value.map(r => Number(r[key]))
      const cpk = cpkOf(vals, c.lo, c.hi)
      dialog('分布图 · ' + c.label, `<svg id="vd-hist" viewBox="0 0 520 240" style="width:100%;height:auto"></svg><p>N ${vals.length} · Mean ${mean(vals).toFixed(4)} · STD ${sd(vals).toFixed(4)} · CPK ${cpk.toFixed(4)}（${gradeOf(cpk)} 级）</p>`)
      requestAnimationFrame(() => { const el = document.getElementById('vd-hist') as unknown as SVGSVGElement; if (el) miniHist(el, vals, { limits: true, lo: c.lo, hi: c.hi, kde: true, bins: 16 }) })
    } },
  ])
}
function exportCsv() {
  const csv = cols.value.map(c => c.label).join(',') + '\n' + vis.value.map(r => cols.value.map(c => (c.test && c.key !== 'bin' ? Number(r[c.key]).toFixed(4) : r[c.key])).join(',')).join('\n')
  download('view-data-demo.csv', csv, 'text/csv')
  toast(`CSV 已同步下载（${vis.value.length} 行，与当前过滤一致）`)
}
function fmt(r: Record<string, unknown>, key: string) {
  const c = VD_COLS.find(x => x.key === key)!
  return c.test && key !== 'bin' ? Number(r[key]).toFixed(4) : String(r[key])
}
function isFail(r: Record<string, unknown>, key: string) {
  const c = VD_COLS.find(x => x.key === key)!
  if (key === 'bin') return r.bin !== 1
  return c.test && (Number(r[key]) < c.lo || Number(r[key]) > c.hi)
}
</script>

<template>
  <MockFrame title="数据管理 · 查看数据">
    <div class="m-toolbar">
      <button v-for="(f, i) in files" :key="f" class="chipx" :class="{ on: i === cur }" @click="cur = i">{{ f }}</button>
      <button v-if="files.length < 4" class="chipx" @click="addFile">＋ 打开文件</button>
    </div>
    <div class="m-toolbar">
      <select v-model="s.pf" class="m-select"><option value="all">Pass + Fail</option><option value="pass">仅 Pass</option><option value="fail">仅 Fail</option></select>
      <select v-model="s.site" class="m-select"><option value="all">全部 Site</option><option>S1</option><option>S2</option><option>S3</option><option>S4</option></select>
      <select v-model="s.width" class="m-select"><option value="std">列宽·标准</option><option value="compact">列宽·紧凑</option><option value="wide">列宽·宽松</option></select>
      <label class="m-label"><input type="checkbox" v-model="s.sticky"> 固定列</label>
      <select class="m-select" @change="applyView(($event.target as HTMLSelectElement).value); ($event.target as HTMLSelectElement).value = ''">
        <option value="">保存的视图…</option><option value="fail">只看 Fail</option><option value="s1">Site1 巡检</option>
      </select>
      <span class="grow"></span>
      <button class="m-btn" @click="toast('导出 Excel：后台作业已提交（演示）· 口径=当前过滤')">导出 Excel</button>
      <button class="m-btn" @click="exportCsv">导出 CSV</button>
    </div>
    <div class="chips" style="margin-bottom:10px">
      <button v-for="c in VD_COLS.filter(x => x.test)" :key="c.key" class="chipx" :class="{ on: s.cols[c.key] }" @click="s.cols[c.key] = !s.cols[c.key]">{{ c.label }}</button>
    </div>
    <div class="qchips">
      <span class="qchip" :class="y < 90 ? 'warn' : 'ok'">整体良率 {{ y.toFixed(2) }}%（目标 ≥90%）</span>
      <span v-if="lowCpk" class="qchip err">{{ lowCpk }} 个参数 CPK 不足（CPK&lt;1.33）</span>
      <span v-if="delta > 10" class="qchip warn">Site 间良率差异 {{ delta.toFixed(2) }}%</span>
    </div>
    <div class="m-table-wrap">
      <table class="m-table">
        <thead><tr>
          <th v-for="c in cols" :key="c.key" :class="{ sticky: c.sticky && s.sticky }" :style="{ padding: pad }" @contextmenu="headCtx($event, c.key)">
            {{ c.label }}<span v-if="c.test" class="lim">[{{ c.lo }}, {{ c.hi }}]</span>
          </th>
        </tr></thead>
        <tbody>
          <tr v-for="r in vis" :key="String(r.serial)" :class="{ hl: s.hl[Number(r.serial)] }">
            <td v-for="c in cols" :key="c.key" :class="{ sticky: c.sticky && s.sticky, fail: isFail(r, c.key), num: c.test }" :style="{ padding: pad }" @contextmenu="cellCtx($event, r, c.key)">{{ fmt(r, c.key) }}</td>
          </tr>
          <tr v-if="!vis.length"><td :colspan="cols.length" style="color:var(--vp-c-text-2)">当前过滤下无数据</td></tr>
        </tbody>
      </table>
    </div>
    <div class="m-foot"><span>共 {{ rows.length }} 条数据（Fail: {{ rows.length - pass }} 行）· 当前显示 {{ vis.length }} 行</span><span>右键序列号 → 高亮此行；右键测试列表头 → 复制名称 / 展示分布图。</span></div>
  </MockFrame>
</template>