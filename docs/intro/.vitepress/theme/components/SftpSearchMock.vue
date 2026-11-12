<script setup lang="ts">
import { ref, computed } from 'vue'
import MockFrame from './MockFrame.vue'
import { SF_CORPUS } from '../data'
import { toast, download } from '../useUi'
const mode = ref('content')
const kw = ref('ShadowReg2')
const match = ref('sub')
const cs = ref(false)
const pattern = ref('')
const dataOnly = ref(true)
const perdir = ref(false)
const worker = ref(4)
const status = ref('就绪 · 引擎待探测')
const running = ref(false)
const hits = ref<{ path: string; matched: [number, string][] }[] | null>(null)
let timer: ReturnType<typeof setInterval> | null = null
function fnmatchToRe(p: string) {
  let out = ''
  for (const c of p) out += c === '*' ? '.*' : c === '?' ? '.' : c.replace(/[.+^${}()|[\]\\]/g, '\\$&')
  return new RegExp('^' + out + '$', 'i')
}
function run() {
  if (timer) clearInterval(timer)
  running.value = true
  hits.value = null
  const pool = SF_CORPUS.filter(f => !dataOnly.value || (!f.sum && !f.log))
    .filter(f => !pattern.value.trim() || fnmatchToRe(pattern.value.trim()).test(f.path.split('/').pop()!))
  const nonAscii = /[^\x00-\x7F]/.test(kw.value)
  const reason = mode.value === 'content' ? (nonAscii ? '关键词含非 ASCII 字符' : 'Channel closed.') : '目录列举引擎'
  let scanned = 0
  status.value = 'running · 引擎探测中… 并发 ' + worker.value
  timer = setInterval(() => {
    scanned = Math.min(pool.length, scanned + 1)
    status.value = `running · 引擎 client · 并发 ${worker.value} · 已扫描 ${scanned} / ${pool.length}`
    if (scanned < pool.length) return
    clearInterval(timer!); timer = null
    running.value = false
    const found: { path: string; matched: [number, string][] }[] = []
    for (const f of pool) {
      const base = f.path.split('/').pop()!
      let matched: [number, string][] = []
      if (mode.value === 'name') {
        const re = kw.value ? fnmatchToRe('*' + kw.value + '*') : null
        if (!re || re.test(base)) matched = [[0, base]]
      } else if (mode.value === 'column') {
        f.lines.forEach((ln, li) => { if (ln.includes(',') && (!kw.value || ln.includes(kw.value))) matched.push([li + 1, ln]) })
        matched = matched.slice(0, 1)
      } else {
        f.lines.forEach((ln, li) => {
          const hay = cs.value ? ln : ln.toLowerCase()
          const needle = cs.value ? kw.value : kw.value.toLowerCase()
          let ok = false
          if (!needle) ok = true
          else if (match.value === 'sub') ok = hay.includes(needle)
          else if (match.value === 'word') ok = new RegExp('\\b' + needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\b', cs.value ? '' : 'i').test(ln)
          else ok = new RegExp(needle.split('').map(c => c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('.*'), cs.value ? '' : 'i').test(ln)
          if (ok) matched.push([li + 1, ln])
        })
      }
      if (matched.length) found.push({ path: f.path, matched })
    }
    let final = found
    if (perdir.value) {
      const seen = new Set<string>()
      final = found.filter(h => { const d = h.path.split('/').slice(0, -1).join('/'); if (seen.has(d)) return false; seen.add(d); return true })
    }
    hits.value = final
    status.value = `done · 引擎 client · 并发 ${worker.value} · 已扫描 ${pool.length} · 候选 ${pool.length} · 命中 ${final.length} · 0.${9 - worker.value}s` + (mode.value === 'content' ? ` · 回落原因：${reason}` : '')
  }, Math.max(60, 260 - worker.value * 25))
}
function hl(line: string) {
  const esc = line.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]!))
  if (!kw.value) return esc
  const safe = kw.value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return esc.replace(new RegExp('(' + safe + ')', cs.value ? 'g' : 'gi'), '<mark>$1</mark>')
}
function exportHits() {
  download('sftp-hits.csv', 'path,line,text\n' + (hits.value || []).map(h => h.matched.map(m => `${h.path},${m[0]},"${m[1].replace(/"/g, '""')}"`).join('\n')).join('\n'), 'text/csv')
  toast('命中清单 CSV 已下载')
}
</script>

<template>
  <MockFrame title="SFTP 搜索 · 范围 → 过滤 → 命中" id="sftp-search">
    <div class="m-toolbar">
      <label class="m-label">匹配模式
        <select v-model="mode" class="m-select"><option value="name">文件名</option><option value="content">内容含</option><option value="column">列名</option></select>
      </label>
      <input v-model="kw" class="m-input" placeholder="关键词" style="width:160px">
      <label class="m-label">匹配
        <select v-model="match" class="m-select"><option value="sub">子串</option><option value="word">整词</option><option value="fuzzy">模糊</option></select>
      </label>
      <label class="m-label"><input type="checkbox" v-model="cs"> 区分大小写</label>
    </div>
    <div class="m-toolbar">
      <input v-model="pattern" class="m-input" placeholder="名称模式 fnmatch，如 RT*.csv（留空不限）" style="width:230px">
      <label class="m-label"><input type="checkbox" v-model="dataOnly"> 仅数据文件</label>
      <label class="m-label"><input type="checkbox" v-model="perdir"> 每目录只取一个</label>
      <label class="m-label">并发 <input type="range" min="1" max="8" v-model.number="worker" style="width:90px"><span>{{ worker }}</span></label>
      <span class="grow"></span>
      <button class="m-btn pri" :disabled="running" @click="run">搜索</button>
    </div>
    <div class="m-foot" style="margin:0 0 10px">{{ status }}</div>
    <div v-for="h in hits || []" :key="h.path" class="intro-note" style="border-left-color:var(--vp-c-border);background:var(--vp-c-bg);padding:12px 16px">
      <div class="m-toolbar" style="margin:0 0 6px"><b style="font-size:13px">{{ h.path }}</b><span class="grow"></span><button class="m-btn pri" @click="toast(h.path.split('/').pop() + ' 已下载并解析入库（演示）')">下载并解析</button></div>
      <div v-for="m in h.matched.slice(0, 3)" :key="m[0]" style="font-family:Consolas,monospace;font-size:12px;color:var(--vp-c-text-2)">L{{ m[0] }} · <span v-html="hl(m[1])"></span></div>
    </div>
    <p v-if="hits && !hits.length" style="color:var(--vp-c-text-2)">无命中——换匹配模式或关掉「仅数据文件」试试。</p>
    <div v-if="hits && hits.length" class="m-toolbar"><button class="m-btn" @click="exportHits">导出命中清单 CSV</button></div>
    <div class="m-foot"><span>命中片段关键词高亮，附行号 / TestFile / StartTime / 完整路径；可下载并解析或导出命中清单 CSV。</span></div>
  </MockFrame>
</template>