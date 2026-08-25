<template>
  <div class="fc-controls">
    <FileSelect
      :model-value="file1"
      :files="files"
      placeholder="文件1 (ATE)"
      show-meta
      style="flex: 1.2"
      @update:model-value="(v: number | number[] | null) => emit('update:file1', typeof v === 'number' ? v : null)"
    />
    <span class="vs-badge">VS</span>
    <FileSelect
      :model-value="file2"
      :files="files"
      placeholder="文件2 (Bench)"
      show-meta
      style="flex: 1.2"
      @update:model-value="(v: number | number[] | null) => emit('update:file2', typeof v === 'number' ? v : null)"
    />

    <div class="fc-opt">
      <label class="fc-opt-label">误差阈值 (%)</label>
      <el-input-number
        :model-value="threshold"
        :min="0"
        :max="100"
        :step="0.1"
        :precision="1"
        size="small"
        style="width: 92px"
        @update:model-value="(v: number | undefined) => emit('update:threshold', v ?? 3)"
      />
    </div>

    <div class="fc-opt">
      <label class="fc-opt-label">Limit Diff 规则</label>
      <el-radio-group
        :model-value="diffRule"
        size="small"
        @update:model-value="(v: string | number | boolean) => emit('update:diffRule', v as DiffRule)"
      >
        <el-radio-button value="zero">A：Diff 必须为 0</el-radio-button>
        <el-radio-button value="wider">B：B 的 Limit 不更紧</el-radio-button>
      </el-radio-group>
    </div>

    <div class="fc-opt">
      <label class="fc-opt-label">序列上限</label>
      <el-input-number
        :model-value="maxSerials"
        :min="1"
        :max="200"
        size="small"
        style="width: 92px"
        @update:model-value="(v: number | undefined) => emit('update:maxSerials', v ?? 30)"
      />
    </div>

    <div class="fc-checks">
      <el-checkbox
        :model-value="ignoreNoLimit"
        size="small"
        @update:model-value="(v: boolean | string | number) => emit('update:ignoreNoLimit', Boolean(v))"
      >
        Ignore No Limit
      </el-checkbox>
      <el-checkbox
        :model-value="ignoreNoData"
        size="small"
        @update:model-value="(v: boolean | string | number) => emit('update:ignoreNoData', Boolean(v))"
      >
        Ignore No Data
      </el-checkbox>
    </div>

    <div class="fc-actions">
      <el-button type="primary" :loading="loading" @click="emit('analyze')">分析</el-button>
      <el-button :loading="exporting" :disabled="!file1 || !file2" @click="emit('export')">
        导出Excel
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import FileSelect from '../../../../components/common/FileSelect.vue'
import type { DiffRule } from '../../../../types'

interface Props {
  files: any[]
  file1: number | null
  file2: number | null
  threshold: number
  diffRule: DiffRule
  maxSerials: number
  ignoreNoLimit: boolean
  ignoreNoData: boolean
  loading?: boolean
  exporting?: boolean
}

withDefaults(defineProps<Props>(), { loading: false, exporting: false })

const emit = defineEmits<{
  (e: 'update:file1', v: number | null): void
  (e: 'update:file2', v: number | null): void
  (e: 'update:threshold', v: number): void
  (e: 'update:diffRule', v: DiffRule): void
  (e: 'update:maxSerials', v: number): void
  (e: 'update:ignoreNoLimit', v: boolean): void
  (e: 'update:ignoreNoData', v: boolean): void
  (e: 'analyze'): void
  (e: 'export'): void
}>()
</script>

<style scoped>
.fc-controls {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
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

.fc-opt {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.fc-opt-label {
  font-size: 11px;
  color: var(--text-secondary);
  font-weight: 500;
  white-space: nowrap;
}

.fc-checks {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.fc-checks :deep(.el-checkbox__label) {
  font-size: 12px;
}

.fc-actions {
  display: flex;
  gap: 8px;
  margin-left: auto;
}
</style>
