<template>
  <div v-if="visible" class="quality-bar">
    <div class="chip">
      <span class="chip-label">Total</span>
      <span class="chip-value">{{ metrics.total_rows?.toLocaleString() ?? '-' }}</span>
    </div>
    <div class="chip">
      <span class="chip-label">Pass</span>
      <span class="chip-value chip-pass">{{ metrics.pass_count?.toLocaleString() ?? '-' }}</span>
    </div>
    <div class="chip">
      <span class="chip-label">Fail</span>
      <span class="chip-value chip-fail">{{ metrics.fail_count?.toLocaleString() ?? '-' }}</span>
    </div>
    <div class="chip">
      <span class="chip-label">Yield</span>
      <span class="chip-value" :class="yieldClass">{{ metrics.yield_pct != null ? metrics.yield_pct + '%' : '-' }}</span>
    </div>
    <div class="chip-tags">
      <el-tag v-for="a in alerts" :key="a.message" :type="a.level === 'error' ? 'danger' : 'warning'" size="small" effect="plain">
        {{ a.message }}
      </el-tag>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { analysisApi } from '../../../../api/analysis'

interface Props {
  fileId: number | null
}

const props = defineProps<Props>()

interface Metrics {
  total_rows: number
  pass_count: number
  fail_count: number
  yield_pct: number
  format: string
}

const visible = ref(false)
const metrics = ref<Metrics>({
  total_rows: 0,
  pass_count: 0,
  fail_count: 0,
  yield_pct: 0,
  format: 'N/A',
})
const alerts = ref<Array<{ level: string; message: string }>>([])

const yieldClass = computed(() => {
  const y = metrics.value.yield_pct
  if (y == null) return ''
  if (y >= 90) return 'yield-good'
  if (y >= 80) return 'yield-mid'
  return 'yield-bad'
})

async function load() {
  if (!props.fileId) {
    visible.value = false
    return
  }
  try {
    const resp = await analysisApi.getDashboard(props.fileId)
    const d = resp.data
    if (!d?.metrics) {
      visible.value = false
      return
    }
    metrics.value = d.metrics
    alerts.value = (d.quality_alerts ?? []).filter(
      (a: any) => a.level === 'warning' || a.level === 'error',
    )
    visible.value = true
  } catch {
    // 静默降级：质量条加载失败不阻塞表格
    visible.value = false
  }
}

watch(() => props.fileId, load, { immediate: true })
</script>

<style scoped>
.quality-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  margin-bottom: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-muted);
  border-radius: 8px;
  flex-wrap: wrap;
}

.chip {
  display: flex;
  flex-direction: column;
  padding: 2px 14px 2px 0;
  border-right: 1px solid var(--border-muted);
  min-width: 56px;
}

.chip:last-of-type {
  border-right: none;
}

.chip-label {
  font-size: 11px;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.chip-value {
  font-size: 17px;
  font-weight: 700;
  color: var(--brand-primary);
  line-height: 1.2;
}

.chip-pass {
  color: var(--color-success);
}

.chip-fail {
  color: var(--color-error);
}

.yield-good {
  color: var(--color-success);
}

.yield-mid {
  color: var(--color-warning);
}

.yield-bad {
  color: var(--color-error);
}

.chip-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-left: 4px;
}
</style>
