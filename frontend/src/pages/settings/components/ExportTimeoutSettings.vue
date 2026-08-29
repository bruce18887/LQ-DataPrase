<template>
  <el-card class="settings-section">
    <template #header>
      <span class="section-title">⏱️ 导出超时</span>
    </template>
    <el-form label-width="160px" class="export-timeout-form">
      <el-form-item label="超时时间（秒）">
        <div class="export-timeout-controls">
          <el-input-number
            :model-value="timeout"
            :min="MIN_EXPORT_TIMEOUT_SEC"
            :max="MAX_EXPORT_TIMEOUT_SEC"
            :step="10"
            :data-testid="'export-timeout-input'"
            @update:model-value="onTimeoutChange"
          />
          <span class="export-timeout-note">
            导出请求最长等待秒数，超过则中断；默认 600 秒（大数据量导出耗时较长时请调大）
          </span>
        </div>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
import { MIN_EXPORT_TIMEOUT_SEC, MAX_EXPORT_TIMEOUT_SEC } from '../../../utils/exportTimeout'

interface Props {
  timeout: number
}
interface Emits {
  (e: 'update:timeout', value: number): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

// el-input-number 清空输入时发射 undefined，钳位到当前值（仿 RecentFilesSettings）
function onTimeoutChange(value: number | undefined) {
  emit('update:timeout', value ?? props.timeout)
}
</script>

<style scoped>
.export-timeout-form {
  max-width: 720px;
}

.export-timeout-controls {
  display: flex;
  align-items: center;
  gap: 12px;
}

.export-timeout-note {
  font-size: 12px;
  color: var(--text-2);
}
</style>
