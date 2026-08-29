<template>
  <!-- 告警横幅（指南 §10.8 四色横幅 + §11.1）：多条告警合并为单行汇总，
       级别取最高（error > warning），点击展开逐条明细；无告警零占位。 -->
  <div
    v-if="alerts.length"
    class="alert-banner"
    :class="`alert-banner--${topLevel}`"
    data-testid="alert-banner"
  >
    <div class="banner-head" role="button" tabindex="0" @click="open = !open" @keydown.enter="open = !open">
      <span class="b-icon">{{ icon }}</span>
      <span class="b-title">{{ summaryTitle }}</span>
      <span class="b-toggle">{{ open ? '收起明细' : '展开明细' }} <span class="b-caret">{{ open ? '▴' : '▾' }}</span></span>
    </div>
    <ul v-if="open" class="banner-body">
      <li v-for="(a, i) in alerts" :key="i">
        <b>{{ a.message }}</b>
        <span v-if="a.params"> — 问题参数: {{ a.params.join(', ') }}</span>
        <span v-if="a.max_site"> — 最高: {{ a.max_site }} | 最低: {{ a.min_site }}</span>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  alerts: any[]
}>()

const open = ref(false)

const topLevel = computed<'error' | 'warning' | 'info'>(() => {
  const levels = props.alerts.map((a) => a.level)
  if (levels.includes('error')) return 'error'
  if (levels.includes('warning')) return 'warning'
  return 'info'
})

const icon = computed(() => (topLevel.value === 'error' ? '🔴' : topLevel.value === 'warning' ? '⚠️' : 'ℹ️'))

const summaryTitle = computed(() => {
  const total = props.alerts.length
  const serious = props.alerts.filter((a) => a.level === 'error').length
  return serious > 0 ? `${total} 项告警 · ${serious} 项需关注` : `${total} 项告警`
})
</script>

<style scoped>
.alert-banner {
  margin-bottom: 14px;
  border-radius: 12px;
  border: 1px solid;
}
.alert-banner--warning {
  background: color-mix(in srgb, var(--warn) 10%, transparent);
  border-color: color-mix(in srgb, var(--warn) 40%, transparent);
}
.alert-banner--error {
  background: color-mix(in srgb, var(--error) 10%, transparent);
  border-color: color-mix(in srgb, var(--error) 40%, transparent);
}
.alert-banner--info {
  background: color-mix(in srgb, var(--info) 10%, transparent);
  border-color: color-mix(in srgb, var(--info) 40%, transparent);
}

.banner-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 16px;
  cursor: pointer;
}
.b-icon { font-size: 16px; }
.b-title {
  font-weight: 700;
  font-size: 13px;
}
.alert-banner--warning .b-title { color: var(--warn); }
.alert-banner--error .b-title { color: var(--error); }
.alert-banner--info .b-title { color: var(--info); }

.b-toggle {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-2);
  display: inline-flex;
  gap: 4px;
  align-items: center;
}

.banner-body {
  padding: 0 16px 12px 42px;
  font-size: 12px;
  color: var(--text-2);
}
.banner-body li {
  margin: 3px 0 3px 14px;
}
.banner-body li b {
  color: var(--text);
}
</style>
