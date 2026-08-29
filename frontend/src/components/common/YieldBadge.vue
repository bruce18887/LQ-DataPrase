<template>
  <span
    v-if="value != null && !Number.isNaN(pct)"
    :class="['yield-badge', `yield-badge--${level}`, { 'yield-badge--lg': size === 'lg', 'yield-badge--compact': compact }]"
  >{{ icon }}{{ display }}</span>
</template>

<script setup lang="ts">
/**
 * YieldBadge 良率徽标（指南 §10.1 良率族 · V1 柔和底 + 形状双编码）
 *
 * ≥95 优 = --success ▲ / ≥90 警 = --warn ◆ / <90 差 = --error ▼
 * 彩底 color-mix(语义色 13%) + 同色字，无边框；11.5px/700 r6 tabular-nums，lg=12.5px
 * compact：表格数值格用，仅语义色文字（去底色），双编码符号保留
 *
 * @example
 * <YieldBadge :value="98.2" />
 * <YieldBadge value="97.5%" size="lg" />
 * <YieldBadge value="N/A" compact />
 */
import { computed } from 'vue'

interface Props {
  /** 数字百分比或带 % 的字符串；'N/A'/空值不渲染 */
  value: number | string
  size?: 'sm' | 'lg'
  compact?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  size: 'sm',
  compact: false,
})

const pct = computed(() =>
  typeof props.value === 'number' ? props.value : parseFloat(String(props.value)),
)

const level = computed(() => {
  if (pct.value >= 95) return 'good'
  if (pct.value >= 90) return 'warn'
  return 'bad'
})

const icon = computed(() =>
  level.value === 'good' ? '▲' : level.value === 'warn' ? '◆' : '▼',
)

const display = computed(() =>
  typeof props.value === 'number' ? `${props.value}%` : props.value,
)
</script>

<style scoped>
.yield-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 700;
  line-height: 1.5;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.yield-badge--lg {
  font-size: 12.5px;
  padding: 3px 10px;
}

.yield-badge--compact {
  padding: 0;
  background: transparent;
}

.yield-badge--good {
  background: color-mix(in srgb, var(--success) 13%, transparent);
  color: var(--success);
}

.yield-badge--warn {
  background: color-mix(in srgb, var(--warn) 13%, transparent);
  color: var(--warn);
}

.yield-badge--bad {
  background: color-mix(in srgb, var(--error) 13%, transparent);
  color: var(--error);
}
</style>
