<script setup lang="ts">
import { ref, computed, reactive } from 'vue'
import MockFrame from './MockFrame.vue'
import { FILES } from '../data'
import { toast, dialog } from '../useUi'
const files = ref(FILES.map(f => ({ ...f })))
const q = ref('')
const sel = reactive<Record<number, boolean>>({})
const open = reactive<Record<number, boolean>>({})
const vis = computed(() => files.value.filter(f => !q.value || (f.name + f.fmt + f.tag).toLowerCase().includes(q.value.toLowerCase())))
const nsel = computed(() => Object.values(sel).filter(Boolean).length)
function combine() {
  const n = nsel.value
  dialog('组合为批次',
    `<p>已选 <b>${n}</b> 个文件。</p><p>新建批次需 ≥2 文件；追加到已有批次 1 个即可。</p>` + (n < 2 ? '<p style="color:var(--intro-warn)">新建不可用：至少勾选 2 个文件。</p>' : ''),
    [{ label: '取消' }, { label: '组合', cls: 'pri', fn: () => toast('已组合为批次（演示）· 仪表板批次良率可选') }])
}
function delOne(id: number) {
  const f = files.value.find(x => x.id === id)!
  dialog('删除文件', `<p>移除 <b>${f.name}</b> 及其解析结果。真实应用中此操作不可逆。</p>`, [
    { label: '取消' },
    { label: '删除', cls: 'danger', fn: () => {
      const idx = files.value.indexOf(f)
      files.value.splice(idx, 1); delete sel[id]
      toast('已删除 ' + f.name, 'warn', { label: '撤销', fn: () => files.value.splice(idx, 0, f) })
    } },
  ])
}
function delSel() {
  const ids = Object.keys(sel).filter(k => sel[+k]).map(Number)
  dialog('批量删除', `<p>移除勾选的 <b>${ids.length}</b> 个文件及其解析结果。</p>`, [
    { label: '取消' },
    { label: '删除', cls: 'danger', fn: () => {
      const removed = files.value.filter(f => ids.includes(f.id))
      files.value = files.value.filter(f => !ids.includes(f.id))
      for (const k of Object.keys(sel)) delete sel[+k]
      toast(`已删除 ${removed.length} 个文件`, 'warn', { label: '撤销', fn: () => { files.value = files.value.concat(removed) } })
    } },
  ])
}
function repair() {
  dialog('数据修复中心', '<p>检查四类不一致：</p><p>① 孤立 DB 记录（有元数据无磁盘文件）</p><p>② 孤立磁盘文件（有文件无元数据）</p><p>③ 产品名缺失</p><p>④ 重复文件（同内容多记录）</p>',
    [{ label: '关闭' }, { label: '运行检查', cls: 'pri', fn: () => toast('检查完成：0 / 0 / 0 / 0（演示环境一致）') }])
}
function upload() {
  dialog('上传文件', '<p>拖拽 CSV / ZIP 到列表区，或点击选择。</p><p>接受 .csv（可多选）与 .zip 批量包；ZIP 自动解析为批次。上传后自动解析：阶段 / 程序 / 限值 / 测试列写入本地数据库。</p>',
    [{ label: '关闭' }, { label: '模拟上传 1 个 CSV', cls: 'pri', fn: () => {
      files.value.push({ id: 106, name: 'DEMO_FT_LOTE.csv', prod: 'DEMO_P1', stage: 'FT', fmt: 'CTA8290D', tag: 'LOT-E', size: '286.4 KB', rows: 100, cols: 271 })
      toast('DEMO_FT_LOTE.csv 解析入库（演示）')
    } }])
}
</script>

<template>
  <MockFrame title="数据管理 · 文件列表">
    <div class="m-toolbar">
      <input v-model="q" class="m-input" placeholder="搜索文件名 / 程序 / 标签" style="width:220px">
      <button class="m-btn pri" @click="upload">上传文件</button>
      <button class="m-btn" :disabled="nsel < 1" @click="combine">组合为批次</button>
      <button class="m-btn danger" :disabled="nsel < 1" @click="delSel">批量删除</button>
      <button class="m-btn" @click="repair">数据修复</button>
      <span class="grow"></span>
      <span class="m-label">共 {{ files.length }} 个文件 · 已选 {{ nsel }}</span>
    </div>
    <div class="m-table-wrap">
      <table class="m-table">
        <thead><tr><th style="width:30px"></th><th style="width:30px"></th><th>ID</th><th>文件名</th><th>产品</th><th>阶段</th><th>格式</th><th>标签</th><th>大小</th><th>操作</th></tr></thead>
        <tbody>
          <template v-for="f in vis" :key="f.id">
            <tr>
              <td><input type="checkbox" v-model="sel[f.id]"></td>
              <td><button class="m-btn" style="padding:1px 7px" @click="open[f.id] = !open[f.id]">{{ open[f.id] ? '▾' : '▸' }}</button></td>
              <td class="num">{{ f.id }}</td><td>{{ f.name }}</td><td>{{ f.prod }}</td>
              <td><span class="tag" :class="f.stage === 'CP' ? 'info' : 'ok'">{{ f.stage }}</span></td>
              <td>{{ f.fmt }}</td><td>{{ f.tag }}</td><td class="num">{{ f.size }}</td>
              <td style="white-space:nowrap">
                <button class="m-btn" style="padding:2px 9px" @click="toast('跳转「查看数据」并加载该文件（演示）')">查看</button>
                <button class="m-btn danger" style="padding:2px 9px" @click="delOne(f.id)">删除</button>
              </td>
            </tr>
            <tr v-if="open[f.id]"><td></td><td colspan="9" style="color:var(--vp-c-text-2);font-size:12px">完整文件名 {{ f.name }} · {{ f.rows }} 行 × {{ f.cols }} 列 · 程序 {{ f.fmt }} · 标签 {{ f.tag }} · 上传于 2026-11-12 09:4{{ f.id % 10 }}</td></tr>
          </template>
          <tr v-if="!vis.length"><td colspan="10" style="color:var(--vp-c-text-2)">无匹配文件</td></tr>
        </tbody>
      </table>
    </div>
    <div class="m-foot"><span>勾选 ≥2 个文件可「组合为批次·新建」；勾选 1 个可「追加」到已有批次。</span><span>行首 ▸ 展开元数据；表头筛选与排序在真实应用中为服务端分页。</span></div>
  </MockFrame>
</template>