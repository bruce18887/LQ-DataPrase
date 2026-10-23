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
            导出请求最长等待秒数，超过则中断；默认 600 秒（大数据量导出耗时较长时请调大）。
            仅作用于仍为同步的导出（CSV、Sigma Limit、批次报告 HTML 等）；
            Excel、批量图表、HTML 报表已改为后台作业，不受此值限制
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

// el-input-number 清空输入时发射 undefined，钳位到当前值（避免把 undefined 存进设置）
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
  /* 窄窗口下的兜底：整段文案落到第二行，而不是和控件抢同一行把对方挤没 */
  flex-wrap: wrap;
}

/* 控件宽度是锁死的（`flex: 0 0 auto`），换行让给文案：el-input-number 默认
   `flex: 0 1 auto` ⇒ 会被长说明文案压缩，而它的收缩下限只有 wrapper 的 42+42px 内边距。
   2026-10-23 在 1280×720 实测：本行控件 150→84px、内部 `<input>` 宽 **0px**
   ⇒ 数值既看不见也点不着（e2e 那条 `toBeVisible` 存量红的真因，回归点是 73c4791 加长文案）。 */
:deep(.el-input-number) {
  flex: 0 0 auto;
}

.export-timeout-note {
  flex: 1 1 260px;
  min-width: 0;
  font-size: var(--p-fs-dense);
  color: var(--text-2);
}
</style>
