<script setup lang="ts">
import { computed } from 'vue'
import { CircleCheck, Lock, Stamp, UserFilled } from '@element-plus/icons-vue'

const props = defineProps<{
  total: number
  active: number
  locked: number
  admins: number
}>()

const chips = computed(() => [
  { key: 'total', label: '总用户', value: props.total, icon: UserFilled, tone: 'brand' },
  { key: 'active', label: '活跃', value: props.active, icon: CircleCheck, tone: 'success' },
  { key: 'locked', label: '锁定', value: props.locked, icon: Lock, tone: 'warn' },
  { key: 'admins', label: '管理员', value: props.admins, icon: Stamp, tone: 'info' },
])
</script>

<template>
  <div class="user-kpi-chips">
    <div
      v-for="chip in chips"
      :key="chip.key"
      class="kpi-chip"
      :class="`kpi-chip--${chip.tone}`"
    >
      <el-icon class="kpi-chip__icon"><component :is="chip.icon" /></el-icon>
      <span class="kpi-chip__label">{{ chip.label }}</span>
      <span class="kpi-chip__value">{{ chip.value }}</span>
    </div>
  </div>
</template>

<style scoped>
.user-kpi-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--p-space-2);
  margin-bottom: var(--p-space-3);
}

.kpi-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--p-space-1);
  padding: var(--p-space-1) var(--p-space-3);
  border: 1px solid var(--border-2);
  border-radius: 999px;
  background: var(--bg-2);
  color: var(--text);
  font-size: var(--p-fs-small);
}

.kpi-chip__icon {
  color: var(--text-2);
}

.kpi-chip--brand .kpi-chip__icon { color: var(--brand); }
.kpi-chip--success .kpi-chip__icon { color: var(--success); }
.kpi-chip--warn .kpi-chip__icon { color: var(--warn); }
.kpi-chip--info .kpi-chip__icon { color: var(--info); }

.kpi-chip__value {
  font-weight: var(--p-fw-semibold);
  font-variant-numeric: tabular-nums;
}
</style>
