<template>
  <div class="file-corr-section">
    <div class="section-card">
      <div class="card-header">
        <div class="card-title-group">
          <span class="card-icon">📁</span>
          <span class="card-title">文件相关性对比</span>
          <span class="card-subtitle">按序列号对齐两文件，逐测试项对比 ATE/Bench（Data A VS Data B）</span>
        </div>
      </div>

      <div class="card-body">
        <FileCorrelationControls
          v-model:file1="file1"
          v-model:file2="file2"
          v-model:threshold="options.threshold"
          v-model:diff-rule="options.diffRule"
          v-model:max-serials="options.maxSerials"
          v-model:ignore-no-limit="options.ignoreNoLimit"
          v-model:ignore-no-data="options.ignoreNoData"
          :files="files"
          :loading="loading"
          :exporting="exporting"
          @analyze="onAnalyze"
          @export="onExport"
        />

        <!-- 防呆：无相同测试项等 400 错误 -->
        <el-alert
          v-if="fcError"
          type="error"
          :title="fcError"
          show-icon
          :closable="false"
          class="fc-alert"
        />

        <!-- 防呆：无公共序列 → 仅对比 Limit -->
        <el-alert
          v-if="result?.limits_only"
          type="info"
          show-icon
          :closable="false"
          class="fc-alert"
        >
          两个文件没有相同的序列号，仅对比 Limit（LSL/USL Diff 与标红规则仍生效）。
        </el-alert>

        <template v-if="result">
          <FileCorrelationSummary :result="result" :diff-rule="options.diffRule" />
          <FileCorrelationTable
            :result="result"
            :threshold="options.threshold"
            :diff-rule="options.diffRule"
          />
        </template>
        <el-empty
          v-else-if="!loading && !fcError"
          description="选择两个文件后点击「分析」开始对比"
          :image-size="80"
          class="fc-empty"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import FileCorrelationControls from './FileCorrelationControls.vue'
import FileCorrelationSummary from './FileCorrelationSummary.vue'
import FileCorrelationTable from './FileCorrelationTable.vue'
import { useFileCorrelation } from '../../composables/useFileCorrelation'
import type { FileCorrelationOptions } from '../../../../types'

defineProps<{
  files: any[]
}>()

const {
  loading, result, error: fcError, exporting,
  loadFileCorrelation, exportFileCorrelation,
} = useFileCorrelation()

const file1 = ref<number | null>(null)
const file2 = ref<number | null>(null)
const options = ref<FileCorrelationOptions>({
  threshold: 3,
  diffRule: 'zero',
  maxSerials: 30,
  ignoreNoLimit: true,
  ignoreNoData: true,
})

function onAnalyze() {
  if (!file1.value || !file2.value) {
    ElMessage.warning('请选择两个文件')
    return
  }
  loadFileCorrelation(file1.value, file2.value, options.value)
}

function onExport() {
  if (!file1.value || !file2.value) {
    ElMessage.warning('请选择两个文件')
    return
  }
  exportFileCorrelation(file1.value, file2.value, options.value)
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
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}

.card-icon { font-size: 16px; }
.card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.card-subtitle {
  font-size: 12px;
  color: var(--text-tertiary);
}

.card-body {
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.fc-alert {
  border-radius: 8px;
}

.fc-empty {
  padding: 24px 0;
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
</style>
