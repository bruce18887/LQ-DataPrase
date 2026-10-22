<script setup lang="ts">
import type { WeightGroupDto } from '../weightChartOption'
import WeightActionButton from './WeightActionButton.vue'
import WeightFilterChips from './WeightFilterChips.vue'

defineProps<{
  filename: string
  groupCount: number
  seriesCount: number
  codeMax: number
  showMean: boolean
  showLegend: boolean
  busy: boolean
  groups: WeightGroupDto[]
  visible: number[]
  slotTotal: number
  visibleSlots: number[]
  colors: string[]
}>()

const emit = defineEmits<{
  (e: 'pick'): void
  (e: 'toggle-mean'): void
  (e: 'toggle-legend'): void
  (e: 'export'): void
  (e: 'update:visible', value: number[]): void
  (e: 'update:visibleSlots', value: number[]): void
}>()
</script>

<template>
  <section class="weight-workspace">
    <div class="weight-workspace-main">
      <div class="file-badge" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
          <path d="M14 3v6h6" />
          <path d="m8 14 2.5 2.5L16 11" />
        </svg>
      </div>

      <div class="file-info">
        <div class="file-title">
          <span class="file-name" :title="filename">{{ filename }}</span>
          <span class="file-tag">已载入</span>
        </div>
        <div class="file-meta">
          <span class="num">{{ groupCount }} 测试项 · {{ seriesCount }} 系列 · Code 0–{{ codeMax }}</span>
          <span class="sep">·</span>
          <span class="privacy">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="4" y="11" width="16" height="10" rx="2" />
              <path d="M8 11V7a4 4 0 0 1 8 0v4" />
            </svg>
            仅本页使用，不写入数据库
          </span>
        </div>
      </div>

      <div class="weight-workspace-actions">
        <span v-if="busy" class="busy-hint">处理中…</span>
        <WeightActionButton @click="emit('pick')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 7h6l2 2h10v10H3z" />
          </svg>
          重新选择
        </WeightActionButton>

        <button
          type="button"
          class="ws-switch"
          :class="{ on: showMean }"
          role="switch"
          :aria-checked="showMean"
          data-testid="weight-mean-switch"
          @click="emit('toggle-mean')"
        >
          <span>显示均值</span>
          <i aria-hidden="true" />
        </button>

        <button
          type="button"
          class="ws-switch"
          :class="{ on: showLegend }"
          role="switch"
          :aria-checked="showLegend"
          data-testid="weight-legend-switch"
          @click="emit('toggle-legend')"
        >
          <span>显示图例</span>
          <i aria-hidden="true" />
        </button>

        <WeightActionButton variant="primary" :disabled="busy" @click="emit('export')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 3v12" />
            <path d="m7 10 5 5 5-5" />
            <path d="M4 19h16" />
          </svg>
          导出 Excel
        </WeightActionButton>
      </div>
    </div>

    <WeightFilterChips
      :groups="groups"
      :visible="visible"
      :slot-total="slotTotal"
      :visible-slots="visibleSlots"
      :colors="colors"
      @update:visible="(value) => emit('update:visible', value)"
      @update:visible-slots="(value) => emit('update:visibleSlots', value)"
    />
  </section>
</template>

<style scoped>
.weight-workspace {
  padding: 14px 16px 12px;
  border: 1px solid var(--border);
  border-radius: var(--p-radius-lg);
  background: var(--card);
  box-shadow: var(--shadow-sm);
}

.weight-workspace-main {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}

.file-badge {
  display: grid;
  place-items: center;
  flex: 0 0 38px;
  width: 38px;
  height: 38px;
  border: 1px solid color-mix(in srgb, var(--brand) 26%, transparent);
  border-radius: 10px;
  background: color-mix(in srgb, var(--brand) 12%, transparent);
  color: var(--brand);
}

.file-badge svg {
  width: 20px;
  height: 20px;
}

.file-info {
  min-width: 0;
}

.file-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.file-name {
  max-width: 44ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--p-fs-lead);
  font-weight: 700;
  color: var(--text);
}

.file-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 7px;
  border: 1px solid color-mix(in srgb, var(--success) 32%, transparent);
  border-radius: var(--p-radius-full);
  background: color-mix(in srgb, var(--success) 13%, transparent);
  color: var(--success);
  font-size: var(--p-fs-micro);
  font-weight: 700;
  white-space: nowrap;
}

.file-tag::before {
  content: '';
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--success);
}

/* night 的 --success 是深青绿，压在同色 13% 底上 11px 小字偏暗；用亮档承载文字与圆点。 */
:global([data-theme='night']) .file-tag {
  color: var(--success-2);
  border-color: color-mix(in srgb, var(--success-2) 32%, transparent);
}

:global([data-theme='night']) .file-tag::before {
  background: var(--success-2);
}

.file-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 3px;
  font-size: var(--p-fs-micro);
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}

.file-meta .sep {
  color: var(--text-3);
}

.privacy {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.privacy svg {
  width: 11px;
  height: 11px;
  color: var(--text-3);
}

.weight-workspace-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.busy-hint {
  font-size: var(--p-fs-micro);
  color: var(--text-2);
}

.ws-switch {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 32px;
  padding: 0 4px;
  border: 0;
  background: transparent;
  color: var(--text-2);
  font-size: var(--p-fs-dense);
  cursor: pointer;
}

.ws-switch i {
  position: relative;
  width: 32px;
  height: 18px;
  border: 1px solid var(--border-2);
  border-radius: var(--p-radius-full);
  background: var(--bg-3);
  transition: background 0.18s;
}

.ws-switch i::after {
  content: '';
  position: absolute;
  top: 1px;
  left: 1px;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--card);
  box-shadow: var(--shadow-sm);
  transition: transform 0.18s;
}

.ws-switch.on i {
  border-color: transparent;
  background: var(--grad-brand);
}

.ws-switch.on i::after {
  transform: translateX(14px);
}

:global([data-theme='night']) .ws-switch.on i::after {
  background: var(--p-slate-950);
}

.ws-switch:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: 2px;
}

@media (max-width: 900px) {
  .weight-workspace-actions {
    margin-left: 0;
    width: 100%;
  }

  .file-name {
    max-width: 30ch;
  }
}
</style>
