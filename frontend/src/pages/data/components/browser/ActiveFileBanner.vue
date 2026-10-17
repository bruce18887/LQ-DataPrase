<template>
  <div class="active-file-banner">
    <span class="banner-icon">📄</span>
    <span class="banner-label">当前文件</span>
    <FileSelect
      :model-value="modelValue"
      :files="files"
      placeholder="请选择一个文件"
      clearable
      show-meta
      aria-label="当前文件"
      class="banner-file-select"
      @update:model-value="onSelect"
    />
    <!-- 文件级操作（重新加载 / 导出）挂在横幅右端：它们作用于「当前文件 + 当前筛选」，
         与文件选择同属一条上下文带，不必再单独占一行 -->
    <div v-if="$slots.actions" class="banner-actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup lang="ts">
import type { DataFile } from '../../../../types'
import FileSelect from '../../../../components/common/FileSelect.vue'

interface Props {
  files: DataFile[]
  /** v-model：当前文件 id（未选为 null） */
  modelValue: number | null
}

const props = defineProps<Props>()
const emit = defineEmits<{ 'update:modelValue': [number | null] }>()

/**
 * FileSelect 为支持多选把 emit 类型写成 number | number[] | null，单选下实际只会是
 * number | null | undefined —— 在这里收口，两个消费方（查看数据 / 导出工具）拿到的
 * 就是干净的 number | null，不必各自再 typeof 一遍。
 */
function onSelect(v: number | number[] | null | undefined) {
  emit('update:modelValue', typeof v === 'number' ? v : null)
}
</script>

<style scoped>
.active-file-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  margin-bottom: 16px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-left: 3px solid var(--brand);
  border-radius: 8px;
  font-size: var(--p-fs-small);
}

.banner-icon {
  font-size: var(--p-fs-base);
  flex-shrink: 0;
}

.banner-label {
  color: var(--text-3);
  font-weight: 500;
  white-space: nowrap;
}

/* 只允许收缩、不允许增长：320px 是原设计宽，加按钮后窄视口下先让下拉让位
   （按钮固定宽，反过来让位会把按钮挤出容器）。宽视口下保持 320，多出来的宽度
   留给 margin-left:auto 的按钮组去贴右缘——原样是「下拉靠左、操作靠右」。 */
.banner-file-select {
  flex: 0 1 320px;
  min-width: 160px;
}

.banner-actions {
  display: flex;
  align-items: center;
  margin-left: auto;
  flex-shrink: 0;
}

:root[data-theme="night"] .active-file-banner {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.08);
}
</style>
