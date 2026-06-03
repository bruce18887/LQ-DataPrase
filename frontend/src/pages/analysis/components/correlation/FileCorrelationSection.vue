<template>
  <div class="file-corr-section">
    <div class="section-card">
      <div class="card-header">
        <div class="card-title-group">
          <span class="card-icon">📁</span>
          <span class="card-title">文件相关性对比</span>
        </div>
      </div>

      <div class="card-body">
        <div class="corr-controls">
          <el-select v-model="localFile1" placeholder="文件1 (ATE)" filterable style="flex: 1">
            <el-option v-for="f in files" :key="f.id" :label="f.filename" :value="f.id" />
          </el-select>
          <span class="vs-badge">VS</span>
          <el-select v-model="localFile2" placeholder="文件2 (Bench)" filterable style="flex: 1">
            <el-option v-for="f in files" :key="f.id" :label="f.filename" :value="f.id" />
          </el-select>
          <el-input-number v-model="localThreshold" :min="0" :max="20" :step="0.5" style="width: 130px" placeholder="阈值%" />
          <el-button type="primary" @click="onAnalyze" :loading="loading">分析</el-button>
        </div>

        <el-table v-if="result" :data="result.summary" stripe style="margin-top:14px"
          :header-cell-style="{ background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontWeight: '600', fontSize: '12px' }"
        >
          <el-table-column prop="param" label="参数" show-overflow-tooltip />
          <el-table-column prop="compared" label="对比数" width="100" align="center" />
          <el-table-column prop="fail_count" label="Fail" width="80" align="center">
            <template #default="{ row }">
              <span :class="['fail-cell', { 'has-fail': row.fail_count > 0 }]">{{ row.fail_count }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="pass_rate" label="通过率(%)" width="110" align="center">
            <template #default="{ row }">
              <span :class="['rate-cell', rateClass(row.pass_rate)]">{{ row.pass_rate }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="max_diff" label="最大偏差(%)" width="120" align="center">
            <template #default="{ row }">
              <span class="diff-cell">{{ row.max_diff }}</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useFileCorrelation } from '../../composables/useFileCorrelation'

defineProps<{
  files: any[]
}>()

const localFile1 = ref<number | null>(null)
const localFile2 = ref<number | null>(null)
const localThreshold = ref(3)

const { loading, result, loadFileCorrelation } = useFileCorrelation()

function onAnalyze() {
  if (localFile1.value && localFile2.value) {
    loadFileCorrelation(localFile1.value, localFile2.value, localThreshold.value)
  }
}

function rateClass(rate: number) {
  if (rate >= 99) return 'rate-excellent'
  if (rate >= 95) return 'rate-good'
  if (rate >= 90) return 'rate-warn'
  return 'rate-bad'
}
</script>

<style scoped>
.file-corr-section {
  width: 100%;
}

.section-card {
  background: var(--bg-primary);
  border: 1px solid var(--border-muted);
  border-radius: 12px;
  overflow: hidden;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-muted);
}

.card-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-icon { font-size: 16px; }
.card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.card-body {
  padding: 16px 20px;
}

/* Controls row */
.corr-controls {
  display: flex;
  align-items: center;
  gap: 10px;
}

.vs-badge {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-tertiary);
  background: var(--bg-secondary);
  border: 1px solid var(--border-muted);
  border-radius: 4px;
  padding: 2px 6px;
  flex-shrink: 0;
  letter-spacing: 0.05em;
}

/* Table */
:deep(.el-table) {
  --el-table-border-color: var(--border-muted);
  border-radius: 8px;
  overflow: hidden;
}

.fail-cell {
  font-size: 12px;
  font-weight: 600;
  font-family: var(--font-mono);
}

.has-fail { color: var(--color-error); }

.rate-cell {
  font-size: 12px;
  font-weight: 600;
  font-family: var(--font-mono);
}

.rate-excellent { color: var(--color-success); }
.rate-good { color: var(--color-info); }
.rate-warn { color: var(--color-warning); }
.rate-bad { color: var(--color-error); }

.diff-cell {
  font-size: 12px;
  font-weight: 500;
  font-family: var(--font-mono);
  color: var(--text-secondary);
}

/* Night */
:root[data-theme="night"] .section-card {
  background: rgba(255, 255, 255, 0.03);
  border-color: rgba(255, 255, 255, 0.08);
}

:root[data-theme="night"] .card-header {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.06);
}

:root[data-theme="night"] .vs-badge {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(255, 255, 255, 0.1);
}
</style>
