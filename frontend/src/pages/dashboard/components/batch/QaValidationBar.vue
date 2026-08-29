<template>
  <div v-if="checks.length" class="qa-bar" role="status">
    <div
      v-for="(c, i) in checks"
      :key="i"
      class="qa-line"
      :class="isOk(c) ? 'qa-line--ok' : 'qa-line--warn'"
    >
      <span class="qa-icon" aria-hidden="true">{{ isOk(c) ? '✅' : '⚠️' }}</span>
      <span class="qa-title">QA 数量校验</span>
      <span class="qa-check">{{ c.check }}</span>
      <span class="qa-vals">
        期望 <b>{{ c.expected }}</b> / 实际 <b>{{ c.actual }}</b>
      </span>
      <span class="qa-status">{{ c.status }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  checks: { check: string; expected: string; actual: string; status: string }[]
}>()

function isOk(c: { check: string; expected: string; actual: string; status: string }): boolean {
  return !c.status.includes('差异') && c.expected === c.actual
}
</script>

<style scoped>
/* 单行紧凑条：替换原整卡表格；语义同 /sftp、/data 的质量色阈值（绿/黄） */
.qa-bar {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 16px;
}

.qa-line {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 7px 14px;
  border-radius: 8px;
  border: 1px solid transparent;
  font-size: 13px;
  line-height: 1.4;
}

.qa-line--ok {
  background: color-mix(in srgb, var(--color-success) 10%, transparent);
  border-color: color-mix(in srgb, var(--color-success) 35%, transparent);
}

.qa-line--warn {
  background: color-mix(in srgb, var(--color-warning) 10%, transparent);
  border-color: color-mix(in srgb, var(--color-warning) 40%, transparent);
}

.qa-icon {
  flex-shrink: 0;
}

.qa-title {
  font-weight: 600;
  color: var(--text-primary);
}

.qa-check {
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 480px;
}

.qa-vals b {
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}

.qa-line--ok .qa-status {
  color: var(--color-success);
  font-weight: 600;
}

.qa-line--warn .qa-status {
  color: var(--color-warning);
  font-weight: 600;
}
</style>
