<template>
  <el-card class="settings-section">
    <template #header>
      <span class="section-title">⏱️ SFTP 下载超时</span>
    </template>
    <el-form label-width="160px" class="sftp-timeout-form">
      <el-form-item label="超时时间（秒）">
        <div class="sftp-timeout-controls">
          <el-input-number
            :model-value="timeout"
            :min="MIN_SFTP_TIMEOUT_SEC"
            :max="MAX_SFTP_TIMEOUT_SEC"
            :step="30"
            :data-testid="'sftp-timeout-input'"
            @update:model-value="onTimeoutChange"
          />
          <span class="sftp-timeout-note">
            SFTP 单文件/批量下载最长等待秒数，超过则中断；默认 600 秒（大文件下载耗时较长时请调大，范围 30-3600）
          </span>
        </div>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
import { MIN_SFTP_TIMEOUT_SEC, MAX_SFTP_TIMEOUT_SEC } from '../../../utils/sftpTimeout'

interface Props {
  timeout: number
}
interface Emits {
  (e: 'update:timeout', value: number): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

// el-input-number 清空输入时发射 undefined，钳位到当前值（仿 ExportTimeoutSettings）
function onTimeoutChange(value: number | undefined) {
  emit('update:timeout', value ?? props.timeout)
}
</script>

<style scoped>
.sftp-timeout-form {
  max-width: 720px;
}

.sftp-timeout-controls {
  display: flex;
  align-items: center;
  gap: 12px;
}

.sftp-timeout-note {
  font-size: 12px;
  color: var(--text-secondary);
}
</style>
