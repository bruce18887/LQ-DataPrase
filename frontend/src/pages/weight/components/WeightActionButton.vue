<script setup lang="ts">
withDefaults(defineProps<{ variant?: 'primary' | 'ghost' }>(), { variant: 'ghost' })
</script>

<template>
  <button type="button" class="weight-action" :class="`weight-action--${variant}`">
    <slot />
  </button>
</template>

<style scoped>
.weight-action {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 13px;
  border: 1px solid transparent;
  border-radius: var(--p-radius-md);
  font-size: var(--p-fs-dense);
  font-weight: 600;
  white-space: nowrap;
  transition:
    transform 0.12s ease,
    box-shadow 0.12s ease,
    border-color 0.12s ease,
    color 0.12s ease;
}

.weight-action svg {
  width: 14px;
  height: 14px;
}

.weight-action:disabled {
  opacity: 0.45;
  cursor: default;
  box-shadow: none;
  transform: none;
}

.weight-action:not(:disabled):hover {
  transform: translateY(-1px);
  box-shadow: var(--shadow-md);
}

.weight-action:not(:disabled):active {
  transform: translateY(0);
}

.weight-action--ghost {
  background: var(--card);
  border-color: var(--border-2);
  color: var(--text-2);
}

.weight-action--ghost:not(:disabled):hover {
  border-color: var(--brand);
  color: var(--brand);
}

.weight-action--primary {
  background: var(--grad-brand);
  color: var(--on-brand);
  box-shadow: var(--shadow-sm);
}

/* night 的 amber 渐变上白字只有 1.4–3.5:1（指南 §3.3 / §10.2）：新组件按条件式前景取深墨。 */
:global([data-theme='night']) .weight-action--primary {
  color: var(--p-slate-950);
}

@media (prefers-reduced-motion: reduce) {
  .weight-action:not(:disabled):hover {
    transform: none;
  }
}
</style>
