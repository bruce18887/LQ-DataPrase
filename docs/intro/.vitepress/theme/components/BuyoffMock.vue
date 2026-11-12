<script setup lang="ts">
import { ref, computed } from 'vue'
import MockFrame from './MockFrame.vue'
import { GG_FILES } from '../data'
import { toast } from '../useUi'
const roles = ref<Record<string, string>>({ ft: 'DEMO_FT_LOTD.csv', qa1: 'DEMO_FT_LOTC.csv', qa2: '' })
const bin1 = ref(true)
const chips = ref<{ t: string; c: string }[] | null>(null)
const n = computed(() => Object.values(roles.value).filter(Boolean).length)
function pick(role: string, v: string) {
  for (const k of Object.keys(roles.value)) if (k !== role && roles.value[k] === v && v) roles.value[k] = ''
  roles.value[role] = v
}
function common() {
  if (n.value < 2) { toast('至少分配 2 个角色才能分析共同测试项', 'warn'); return }
  chips.value = [{ t: '共同 12 项', c: 'ok' }, { t: '部分共有 5 项', c: 'warn' }, { t: '独有 3 项', c: 'mut' }]
  toast('共同测试项分析完成（演示）')
}
</script>

<template>
  <MockFrame title="数据管理 · Buyoff Form">
    <div class="slotgrid" style="grid-template-columns:repeat(3,1fr)">
      <div v-for="(label, key) in { ft: 'FT 角色', qa1: 'QA1 角色', qa2: 'QA2 角色' }" :key="key" class="slot">
        <div class="sl">{{ label }}</div>
        <select class="m-select" :value="roles[key]" @change="pick(key, ($event.target as HTMLSelectElement).value)">
          <option value="">（未分配）</option><option v-for="f in GG_FILES" :key="f" :value="f">{{ f }}</option>
        </select>
      </div>
    </div>
    <div class="m-toolbar" style="margin-top:12px">
      <label class="m-label"><input type="checkbox" v-model="bin1"> 只选 Bin1</label>
      <button class="m-btn" @click="common">分析共同测试项</button>
      <span class="grow"></span>
      <button class="m-btn pri" :disabled="n < 2" @click="toast('Buyoff Form 已生成（演示）· 下载 buyoff_form.xlsx')">生成 Buyoff Form</button>
    </div>
    <div v-if="chips" class="chips"><span v-for="c in chips" :key="c.t" class="tag" :class="c.c">{{ c.t }}</span></div>
    <div class="m-foot">三角色分配文件互斥（一份文件只能属于一个角色）；≥2 个角色有文件才可生成；下载为 xlsx。</div>
  </MockFrame>
</template>