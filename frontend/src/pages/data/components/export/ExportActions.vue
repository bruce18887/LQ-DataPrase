<template>
  <div class="step-card">
    <div class="step-header">
      <span class="step-number">3</span>
      <span class="step-title">导出</span>
      <span v-if="!hasParams" class="step-hint">请先完成步骤 1 选择参数</span>
    </div>
    <div class="step-body">
      <div class="sigma-group">
        <span class="sigma-label">Sigma 范围</span>
        <el-select :model-value="sigma" size="small" class="sigma-select" aria-label="选择Sigma范围" @update:model-value="$emit('update:sigma', $event)">
          <el-option :value="3" label="3 Sigma" />
          <el-option :value="4" label="4 Sigma" />
          <el-option :value="6" label="6 Sigma" />
        </el-select>
        <el-button :disabled="!hasParams" :loading="exporting" @click="$emit('export-sigma')">
          导出 Sigma Limit
        </el-button>
      </div>

      <div class="action-spacer" />

      <el-tooltip :disabled="hasParams" content="请先选择要导出的参数" placement="top">
        <el-button type="primary" :disabled="!hasParams" :loading="exporting" @click="$emit('export-batch', 'xlsx')">
          📊 批量导出 Excel
        </el-button>
      </el-tooltip>
      <el-tooltip :disabled="hasParams" content="请先选择要导出的参数" placement="top">
        <el-button :disabled="!hasParams" :loading="exporting" @click="$emit('export-batch', 'pptx')">
          📽️ 批量导出 PPT
        </el-button>
      </el-tooltip>
    </div>
  </div>
</template>

<script setup lang="ts">
interface Props {
  sigma: number
  exporting: boolean
  hasParams: boolean
}

defineProps<Props>()
defineEmits<{
  (e: 'update:sigma', value: number): void
  (e: 'export-sigma'): void
  (e: 'export-batch', format: string): void
}>()
</script>

<style scoped>
.step-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-muted);
  border-radius: 10px;
  padding: 14px 16px;
}

.step-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.step-number {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--brand-primary);
  color: var(--text-inverse);
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}

.step-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.step-hint {
  margin-left: auto;
  font-size: 11px;
  color: var(--color-warning);
  font-weight: 500;
}

.step-body {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.sigma-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sigma-label {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.sigma-select {
  width: 120px;
}

.action-spacer {
  flex: 1;
}
</style>
