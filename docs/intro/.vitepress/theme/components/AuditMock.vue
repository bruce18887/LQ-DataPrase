<script setup lang="ts">
import { ref, computed } from 'vue'
import MockFrame from './MockFrame.vue'
import { AU_EVENTS, AU_SEED } from '../data'
import { toast } from '../useUi'
const props = defineProps<{ extra?: { t: string; ev: string; op: string; tg: string; ip: string; d: string }[] }>()
const ev = ref('')
const acct = ref('')
const from = ref('2026-11-01')
const to = ref('2026-11-12')
const open = ref(-1)
const all = computed(() => [...(props.extra || []), ...AU_SEED])
const vis = computed(() => all.value.filter(r => {
  const day = r.t.slice(0, 10)
  return (!ev.value || r.ev === ev.value) && (!acct.value || (r.op + r.tg).toLowerCase().includes(acct.value.toLowerCase())) && (!from.value || day >= from.value) && (!to.value || day <= to.value)
}))
function reset() { ev.value = ''; acct.value = ''; from.value = '2026-11-01'; to.value = '2026-11-12' }
</script>

<template>
  <MockFrame title="操作审计">
    <div class="m-toolbar">
      <select v-model="ev" class="m-select"><option value="">全部事件</option><option v-for="e in AU_EVENTS" :key="e" :value="e">{{ e }}</option></select>
      <input v-model="acct" class="m-input" placeholder="账号" style="width:120px">
      <input v-model="from" type="date" class="m-input">
      <span class="m-label">至</span>
      <input v-model="to" type="date" class="m-input">
      <button class="m-btn pri" @click="toast('审计查询完成（演示）· 筛选口径即时生效')">查询</button>
      <button class="m-btn" @click="reset">重置</button>
    </div>
    <div class="m-table-wrap">
      <table class="m-table">
        <thead><tr><th style="width:30px"></th><th>时间</th><th>事件</th><th>操作者</th><th>目标账号</th><th>IP</th><th>详情摘要</th></tr></thead>
        <tbody>
          <template v-for="(r, i) in vis" :key="r.t + i">
            <tr style="cursor:pointer" @click="open = open === i ? -1 : i">
              <td>{{ open === i ? '▾' : '▸' }}</td><td class="num">{{ r.t }}</td>
              <td><span class="tag" :class="r.ev === '登录失败' || r.ev === '账号锁定' ? 'err' : r.ev === '登录成功' ? 'ok' : 'mut'">{{ r.ev }}</span></td>
              <td>{{ r.op }}</td><td>{{ r.tg }}</td><td class="num">{{ r.ip }}</td>
              <td style="color:var(--vp-c-text-2)">{{ r.d.length > 26 ? r.d.slice(0, 26) + '…' : r.d }}</td>
            </tr>
            <tr v-if="open === i"><td></td><td colspan="6" style="color:var(--vp-c-text-2);font-size:12px">完整详情：{{ r.d }} · 事件 {{ r.ev }} · 操作者 {{ r.op }} · 目标 {{ r.tg }}</td></tr>
          </template>
          <tr v-if="!vis.length"><td colspan="7" style="color:var(--vp-c-text-2)">无匹配记录</td></tr>
        </tbody>
      </table>
    </div>
    <div class="m-foot">点行首 ▸ 展开详情摘要（失败原因 / 剩余尝试次数 / 变更字段）。十类事件全留痕；上方用户管理的操作会实时写入本表。</div>
  </MockFrame>
</template>