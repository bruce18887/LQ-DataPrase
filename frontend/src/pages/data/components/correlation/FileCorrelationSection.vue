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
          v-model:serials="options.serials"
          v-model:ignore-no-limit="options.ignoreNoLimit"
          v-model:ignore-no-data="options.ignoreNoData"
          :files="files"
          :common-serials="commonSerials"
          :serials-loading="serialsLoading"
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
          没有可对比的序列，仅对比 Limit（LSL/USL Diff 与标红规则仍生效）。
        </el-alert>

        <template v-if="result">
          <!-- 视图切换：测试值对比 / Limit 对比 分离（Limit 列不再占固定列宽） -->
          <div class="fc-view-switch">
            <span class="fc-view-label">对比视图</span>
            <el-radio-group v-model="viewMode" size="small">
              <el-radio-button value="data">测试值对比</el-radio-button>
              <el-radio-button value="limit">Limit 对比</el-radio-button>
            </el-radio-group>
          </div>

          <FileCorrelationSummary :result="result" :diff-rule="options.diffRule" />

          <!-- 重型表格：ag-grid 行列双虚拟化后 DOM 很小，tab 不活跃时仅
               v-show 隐藏（display:none 切换毫秒级），切回无需重渲染 -->
          <FileCorrelationTable
            v-if="viewMode === 'data'"
            v-show="active"
            :result="result"
            :threshold="options.threshold"
            :diff-rule="options.diffRule"
          />
          <FileCorrelationLimitTable
            v-if="viewMode === 'limit'"
            v-show="active"
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
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import FileCorrelationControls from './FileCorrelationControls.vue'
import FileCorrelationSummary from './FileCorrelationSummary.vue'
import FileCorrelationTable from './FileCorrelationTable.vue'
import FileCorrelationLimitTable from './FileCorrelationLimitTable.vue'
import { useFileCorrelation } from '../../composables/useFileCorrelation'
import type { FileCorrelationOptions } from '../../../../types'

withDefaults(defineProps<{
  files: any[]
  /** 当前 tab 是否活跃（不活跃时卸载重型结果表格 DOM） */
  active?: boolean
}>(), { active: true })

const {
  loading, result, error: fcError, exporting,
  commonSerials, commonSerialsLoading: serialsLoading,
  loadCommonSerials, loadFileCorrelation, exportFileCorrelation,
} = useFileCorrelation()

const file1 = ref<number | null>(null)
const file2 = ref<number | null>(null)
const options = ref<FileCorrelationOptions>({
  threshold: 3,
  diffRule: 'zero',
  serials: [],
  ignoreNoLimit: true,
  ignoreNoData: true,
})
/** 对比视图：data=测试值对比（默认）/ limit=Limit 对比 */
const viewMode = ref<'data' | 'limit'>('data')

// 文件对变化 → 拉取公共序列并默认选中前 10 颗（升序）
watch([file1, file2], async ([a, b]) => {
  if (!a || !b) {
    commonSerials.value = []
    options.value.serials = []
    return
  }
  const list = await loadCommonSerials(a, b)
  options.value.serials = list.slice(0, 10)
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
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: var(--bg-2);
  border-bottom: 1px solid var(--border);
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
  color: var(--text);
}
.card-subtitle {
  font-size: 12px;
  color: var(--text-3);
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

.fc-view-switch {
  display: flex;
  align-items: center;
  gap: 10px;
}

.fc-view-label {
  font-size: 12px;
  color: var(--text-2);
  font-weight: 500;
  white-space: nowrap;
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
