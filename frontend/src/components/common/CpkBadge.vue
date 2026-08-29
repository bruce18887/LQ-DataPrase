<template>
  <span v-if="level" :class="['cpk-badge', `cpk-badge--${level}`, { 'cpk-badge--compact': compact }]">{{ icon }}{{ label }}</span>
</template>

<script setup lang="ts">
/**
 * CpkBadge CPK 等级徽标（指南 §10.1 CPK 族 · 色相 + 形状双编码）
 *
 * A✓ 绿（--success）/ B● 品牌色（--brand）/ C◆ 琥珀（--warn）/ D▼ 红（--error，底色加深到 22%）
 * night 下 --brand 与 --warn 同为金黄，B/C 靠 ●◆ 形状区分
 *
 * @example
 * <CpkBadge level="A" />
 * <CpkBadge :level="row.cpk_level" compact />
 */
import { computed } from 'vue'

interface Props {
  /** 等级字母（A/B/C/D），大小写不敏感；非法值不渲染 */
  level: string | null | undefined
  /** 表格数值格用：仅语义色文字（去底色） */
  compact?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  compact: false,
})

const level = computed(() => {
  const l = (props.level || '').trim().toUpperCase().charAt(0)
  return 'ABCD'.includes(l) ? l.toLowerCase() : ''
})

const icon = computed(() =>
  ({ a: '✓', b: '●', c: '◆', d: '▼' } as Record<string, string>)[level.value] || '',
)

const label = computed(() => (level.value ? level.value.toUpperCase() : ''))
</script>

<style scoped>
.cpk-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 700;
  line-height: 1.5;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.cpk-badge--compact {
  padding: 0;
  background: transparent;
}

.cpk-badge--a {
  background: color-mix(in srgb, var(--success) 13%, transparent);
  color: var(--success);
}

.cpk-badge--b {
  background: color-mix(in srgb, var(--brand) 13%, transparent);
  color: var(--brand);
}

.cpk-badge--c {
  background: color-mix(in srgb, var(--warn) 13%, transparent);
  color: var(--warn);
}

.cpk-badge--d {
  background: color-mix(in srgb, var(--error) 22%, transparent);
  color: var(--error);
}
</style>
