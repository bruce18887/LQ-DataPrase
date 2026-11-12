<script setup lang="ts">
import { ref, computed } from 'vue'
import MockFrame from './MockFrame.vue'
import { SF_NODES } from '../data'
import { toast, dialog } from '../useUi'
const path = ref('home/datalogs/2026Q4/LOTC')
const q = ref('')
const csv = ref(true)
const connected = ref(true)
const parsed = ref<string[]>([])
const parts = computed(() => path.value.split('/'))
const node = computed(() => SF_NODES[path.value] || {})
const dirs = computed(() => node.value.dirs || [])
const files = computed(() => (node.value.files || []).filter(f => (!csv.value || f[2] === 'csv') && (!q.value || f[0].toLowerCase().includes(q.value.toLowerCase()))))
const kb = computed(() => files.value.reduce((a, f) => a + parseFloat(f[1]), 0))
function parse(name: string) {
  if (!parsed.value.includes(name)) parsed.value.push(name)
  toast(name + ' 已解析入库（演示）· 与本地上传同权')
}
</script>

<template>
  <MockFrame title="SFTP 浏览器">
    <div class="m-toolbar">
      <span class="tag" :class="connected ? 'ok' : 'err'">{{ connected ? '已连接' : '未连接' }}</span>
      <template v-if="connected">
        <template v-for="(p, i) in parts" :key="i">
          <button class="chipx" @click="path = parts.slice(0, i + 1).join('/')">{{ p }}</button>
          <span v-if="i < parts.length - 1" style="color:var(--vp-c-text-2)">/</span>
        </template>
      </template>
      <span class="grow"></span>
      <label class="m-label"><input type="checkbox" v-model="csv"> 仅 CSV</label>
      <input v-model="q" class="m-input" placeholder="文件名即时搜索" style="width:170px">
      <button class="m-btn" @click="document.getElementById('sftp-search')?.scrollIntoView({ behavior: 'smooth' })">高级搜索</button>
      <button class="m-btn" @click="connected = false">断开</button>
    </div>
    <div v-if="!connected" class="intro-note">
      <div class="m-toolbar" style="margin:0">
        <input class="m-input" value="demo.sftp.local" style="width:150px" aria-label="主机">
        <input class="m-input" value="22" style="width:70px" aria-label="端口">
        <input class="m-input" placeholder="账号" style="width:110px">
        <input class="m-input" type="password" placeholder="密码" style="width:110px">
        <label class="m-label"><input type="checkbox" checked> 保存配置</label>
        <button class="m-btn pri" @click="connected = true; toast('已连接（演示）· 密码加密保存')">连接</button>
      </div>
      <p style="color:var(--vp-c-text-2);font-size:12.5px;margin:8px 0 0">密码加密存储在服务端配置；可保存多套服务器配置一键连接。</p>
    </div>
    <div v-else class="m-table-wrap">
      <table class="m-table">
        <thead><tr><th>名称</th><th>大小</th><th>类型</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="d in dirs" :key="d"><td>📁 {{ d }}</td><td>—</td><td><span class="tag mut">目录</span></td><td><button class="m-btn" @click="path += '/' + d">进入</button></td></tr>
          <tr v-for="f in files" :key="f[0]">
            <td>{{ f[0] }}</td><td class="num">{{ f[1] }}</td><td><span class="tag" :class="f[2] === 'csv' ? 'ok' : 'mut'">{{ f[2] }}</span></td>
            <td style="white-space:nowrap">
              <button class="m-btn" @click="toast('已下载 ' + f[0] + '（演示）')">下载</button>
              <button class="m-btn pri" @click="parse(f[0])">解析</button>
            </td>
          </tr>
          <tr v-if="!dirs.length && !files.length"><td colspan="4" style="color:var(--vp-c-text-2)">空目录或无匹配</td></tr>
        </tbody>
      </table>
    </div>
    <div class="m-foot">
      <span>{{ connected ? `${dirs.length} 个文件夹 / ${files.length} 个文件 / 总计 ${kb.toFixed(1)} KB` : '连接面板 · 断开状态' }}</span>
      <span>「解析」直接入库进入分析链路，与本地上传文件完全同权。</span>
    </div>
    <div v-if="parsed.length" class="chips" style="margin-top:10px">
      <span class="m-label">已解析入库：</span><span v-for="p in parsed" :key="p" class="tag ok">{{ p }}</span>
    </div>
  </MockFrame>
</template>