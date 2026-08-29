<template>
  <span :class="['bin-tag', `bin-tag--${variant}`]">{{ icon }}{{ label }}</span>
</template>

<script setup lang="ts">
/**
 * BinTag Bin 徽标（指南 §10.1 Bin 族，并入徽标变体 · 色相 + 形状双编码）
 *
 * pass（Bin 1）= good ✓ / 普通失效 = neutral — / 高失 = bad ▼
 * 高失判定：非 pass bin 且占比 pct ≥ highFailPct（默认 10）
 *
 * @example
 * <BinTag label="SBH 1" :pct="96.2" />
 * <BinTag label="Bin 3" :pct="18.4" />
 */
import { computed } from 'vue'

interface Props {
  label: string
  /** 该 Bin 占比百分比（用于高失判定），可缺省 */
  pct?: number | null
  /** 高失阈值，默认 10（%） */
  highFailPct?: number
}

const props = withDefaults(defineProps<Props>(), {
  pct: null,
  highFailPct: 10,
})

const isPass = computed(() => props.label.includes('1'))

const variant = computed(() => {
  if (isPass.value) return 'good'
  if (props.pct != null && props.pct >= props.highFailPct) return 'bad'
  return 'neutral'
})

const icon = computed(() =>
  variant.value === 'good' ? '✓' : variant.value === 'bad' ? '▼' : '—',
)
</script>

<style scoped>
.bin-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 700;
  line-height: 1.5;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.bin-tag--good {
  background: color-mix(in srgb, var(--success) 13%, transparent);
  color: var(--success);
}

.bin-tag--neutral {
  background: color-mix(in srgb, var(--text-2) 12%, transparent);
  color: var(--text-2);
}

.bin-tag--bad {
  background: color-mix(in srgb, var(--error) 13%, transparent);
  color: var(--error);
}
</style>
