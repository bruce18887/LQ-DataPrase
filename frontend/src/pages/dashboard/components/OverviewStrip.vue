<template>
  <!-- 总览条（指南 §11.1）：一行 label+value 的信息记录中枢。
       数值大号 18/700、文本型小号 13.5；Pass 绿 / Fail>0 红 / 良率色阶；
       末尾数据格式中性 chip；窄视口可换行。 -->
  <div class="overview-strip" data-testid="overview-strip">
    <div class="strip-item">
      <span class="strip-label">程序</span>
      <span class="strip-value strip-value--sm">{{ program || '-' }}</span>
    </div>
    <div class="strip-item">
      <span class="strip-label">总记录</span>
      <span class="strip-value">{{ fmtNum(metrics.total_rows) }}</span>
    </div>
    <div class="strip-item">
      <span class="strip-label">Pass</span>
      <span class="strip-value strip-value--pass">{{ fmtNum(metrics.pass_count) }}</span>
    </div>
    <div class="strip-item">
      <span class="strip-label">Fail</span>
      <span class="strip-value" :class="metrics.fail_count > 0 ? 'strip-value--fail' : 'strip-value--ok'">
        {{ fmtNum(metrics.fail_count) }}
      </span>
    </div>
    <div class="strip-item">
      <span class="strip-label">Yield</span>
      <span class="strip-value" :class="yieldClass">{{ fmtYield(metrics.yield_pct) }}<span class="strip-unit">%</span></span>
    </div>
    <div class="strip-item">
      <span class="strip-label">UPH<el-tooltip placement="top" :width="340">
        <template #content>
          <div class="strip-helper">
            <div>UPH = 测试总数量 ÷ 总耗时 × 3600</div>
            <div v-if="uph?.site_count">总耗时 = 各单元测试时间之和 ÷ {{ uph.site_count }}（并行站点模型）</div>
          </div>
        </template>
        <span class="strip-help">?</span>
      </el-tooltip></span>
      <span class="strip-value">{{ uph ? uph.uph.toLocaleString() : '-' }}</span>
    </div>
    <div class="strip-item">
      <span class="strip-label">测试时长</span>
      <span class="strip-value strip-value--sm">{{ uph ? formatTime(uph.total_time_seconds) : '-' }}</span>
    </div>
    <div class="strip-item">
      <span class="strip-label">测试开始</span>
      <span class="strip-value strip-value--sm">{{ testStart || '-' }}</span>
    </div>
    <span v-if="metrics.format && metrics.format !== 'N/A'" class="strip-chip">{{ metrics.format }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { UphData } from '../../../types'

const props = defineProps<{
  metrics: { total_rows: number; pass_count: number; fail_count: number; yield_pct: number; format: string }
  /** UPH 数据（由页面统一拉取后下传，避免与 UphCard 重复请求） */
  uph: UphData | null
  /** 程序名称（文件元数据） */
  program: string
  /** 测试开始（文件元数据 metadata.start_time，显示已精简） */
  testStart: string
}>()

const yieldClass = computed(() => {
  const y = props.metrics.yield_pct
  if (y == null || Number.isNaN(y)) return ''
  if (y >= 95) return 'strip-value--good'
  if (y >= 90) return 'strip-value--warn'
  return 'strip-value--bad'
})

function fmtNum(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '-'
  return n.toLocaleString()
}

function fmtYield(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '-'
  return n.toFixed(2)
}

function formatTime(seconds: number): string {
  if (!seconds || seconds <= 0) return '-'
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}min`
  const h = Math.floor(seconds / 3600)
  const m = Math.round((seconds % 3600) / 60)
  return `${h}h ${m}m`
}
</script>

<style scoped>
.overview-strip {
  display: flex;
  align-items: center;
  padding: 10px 16px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--card);
  box-shadow: var(--shadow-sm);
  margin-bottom: 12px;
  flex-wrap: wrap;
  row-gap: 8px;
}

.strip-item {
  display: flex;
  align-items: baseline;
  gap: 7px;
  padding: 0 18px;
  border-right: 1px solid var(--border-2);
}
.strip-item:first-child { padding-left: 0; }
.strip-item:last-of-type { border-right: none; }

.strip-label {
  font-size: 11px;
  color: var(--text-3);
  white-space: nowrap;
}

.strip-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--text);
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}
.strip-value--sm {
  font-size: 13.5px;
  font-weight: 600;
}
.strip-unit {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-2);
  margin-left: 1px;
}

.strip-value--pass,
.strip-value--ok,
.strip-value--good { color: var(--success); }
.strip-value--warn { color: var(--warn); }
.strip-value--fail,
.strip-value--bad { color: var(--error); }

.strip-chip {
  margin-left: auto;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 9px;
  border-radius: 6px;
  background: color-mix(in srgb, var(--text-2) 12%, transparent);
  color: var(--text);
}

.strip-help {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 13px;
  height: 13px;
  margin-left: 3px;
  border-radius: 50%;
  border: 1px solid var(--border-2);
  color: var(--text-3);
  font-size: 9px;
  cursor: help;
}

.strip-helper {
  font-size: 12px;
  line-height: 1.7;
}

@media (max-width: 900px) {
  .strip-item { padding: 0 10px; }
}
</style>
