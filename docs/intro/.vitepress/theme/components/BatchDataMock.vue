<script setup lang="ts">
import { ref, computed, reactive } from 'vue'
import MockFrame from './MockFrame.vue'
import { BA_BATCHES } from '../data'
import { toast, dialog } from '../useUi'
const batches = ref(BA_BATCHES.map(b => ({ ...b, files: b.files.map(f => [...f]) })))
const q = ref('')
const allOpen = ref(false)
const sel = reactive<Record<string, boolean>>({})
const sftp = ref<{ dir: string; n: number } | null>({ dir: 'datalogs/2026Q4/LOTE', n: 2 })
const vis = computed(() => batches.value.filter(b => !q.value || b.name.toLowerCase().includes(q.value.toLowerCase())))
const nf = computed(() => batches.value.reduce((a, b) => a + b.files.length, 0))
const nsel = computed(() => Object.values(sel).filter(Boolean).length)
function removeSel() {
  const keys = Object.keys(sel).filter(k => sel[k])
  for (const k of keys) { const [bi, fi] = k.split(':').map(Number); batches.value[bi].files.splice(fi, 1) }
  for (const k of Object.keys(sel)) delete sel[k]
  toast(`已移出 ${keys.length} 个文件（演示）`)
}
function delBatch(i: number) {
  const b = batches.value[i]
  dialog('删除批次', `<p>删除 <b>${b.name}</b>（成员文件保留在文件列表）。</p>`, [
    { label: '取消' },
    { label: '删除', cls: 'danger', fn: () => { batches.value.splice(i, 1); toast('批次已删除', 'warn', { label: '撤销', fn: () => batches.value.splice(i, 0, b) }) } },
  ])
}
function delFile(bi: number, fi: number) {
  const f = batches.value[bi].files[fi]
  batches.value[bi].files.splice(fi, 1)
  toast('已移出 ' + f[0], 'warn', { label: '撤销', fn: () => batches.value[bi].files.splice(fi, 0, f) })
}
</script>

<template>
  <MockFrame title="数据管理 · 批次数据">
    <div class="m-toolbar">
      <input v-model="q" class="m-input" placeholder="搜索批次名" style="width:200px">
      <button class="m-btn" @click="allOpen = !allOpen">{{ allOpen ? '全部折叠' : '全部展开' }}</button>
      <button class="m-btn" :disabled="nsel < 1" @click="removeSel">移出选中</button>
      <span class="grow"></span>
      <span class="m-label">显示 {{ vis.length }} / {{ batches.length }} 批次</span>
    </div>
    <div class="m-strip">
      <div class="sc"><div class="v">{{ batches.length }}</div><div class="l">批次</div></div>
      <div class="sc"><div class="v">{{ nf }}</div><div class="l">文件</div></div>
      <div class="sc"><div class="v">{{ nf * 100 }}</div><div class="l">总行数</div></div>
    </div>
    <div v-if="sftp" class="intro-note" style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
      <b>SFTP 未导入目录</b><code>{{ sftp.dir }}</code> · {{ sftp.n }} 个文件
      <span class="grow"></span>
      <button class="m-btn pri" @click="sftp = null; toast('已送入解析链路（演示）· 入库后与本地文件同权')">导入</button>
      <button class="m-btn danger" @click="dialog('删除未导入目录', `<p>移除远端下载缓存 <code>${sftp!.dir}</code>？</p>`, [{ label: '取消' }, { label: '删除', cls: 'danger', fn: () => { sftp = null; toast('已删除未导入目录', 'warn') } }])">删除</button>
    </div>
    <div v-for="(b, bi) in vis" :key="b.name" class="intro-note" style="border-left-color:var(--vp-c-border);background:var(--vp-c-bg);padding:12px 16px">
      <div class="m-toolbar" style="margin:0">
        <button class="m-btn" style="padding:1px 8px" @click="b.open = !b.open; allOpen = false">{{ allOpen || b.open ? '▾' : '▸' }}</button>
        <b>{{ b.name }}</b>
        <span class="tag mut">{{ b.files.length }} 文件</span>
        <span class="tag mut">{{ (b.files.length * 286.4).toFixed(1) }} KB</span>
        <span class="tag mut">{{ b.files.length * 100 }} 行</span>
        <span class="tag ok">FT</span><span class="tag info">DEMO_P1</span>
        <span class="grow"></span>
        <button class="m-btn danger" @click="delBatch(bi)">删批次</button>
      </div>
      <div v-if="allOpen || b.open" class="m-table-wrap" style="margin-top:10px">
        <table class="m-table">
          <thead><tr><th style="width:30px"></th><th>文件</th><th>子批次</th><th>行 × 列</th><th>大小</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="(f, fi) in b.files" :key="fi">
              <td><input type="checkbox" v-model="sel[bi + ':' + fi]"></td>
              <td>{{ f[0] }}</td><td>{{ f[1] }}</td><td class="num">{{ f[2] }} × {{ f[3] }}</td><td class="num">{{ f[4] }}</td>
              <td><button class="m-btn danger" style="padding:2px 9px" @click="delFile(bi, fi)">删子批次</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <p v-if="!vis.length" style="color:var(--vp-c-text-2)">无匹配批次</p>
    <div class="m-foot"><span>批次头显示文件数 / 大小 / 行数 / 格式 / 产品 / 阶段 / 子批次；展开看明细与子批次。</span></div>
  </MockFrame>
</template>