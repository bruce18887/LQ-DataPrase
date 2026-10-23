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
  /* 与导出超时行同形：文案换行，控件不陪它抢同一行 */
  flex-wrap: wrap;
}

/* 同 ExportTimeoutSettings：这行实测 150→109.9px、内部 `<input>` 只剩 25.9px，
   没归零所以 e2e 一直是绿的，但「600」已经被塞进一个看不全的框里。 */
:deep(.el-input-number) {
  flex: 0 0 auto;
}

.sftp-timeout-note {
  flex: 1 1 260px;
  min-width: 0;
  font-size: var(--p-fs-dense);
  color: var(--text-2);
}
</style>
