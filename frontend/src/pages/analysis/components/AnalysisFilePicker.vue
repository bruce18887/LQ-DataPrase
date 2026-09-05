<template>
  <div class="dp-analysis-filepicker" :class="{ 'dp-analysis-filepicker--block': block }">
    <label class="picker-label" :for="inputId">{{ label }}</label>
    <FileSelect
      :id="inputId"
      :model-value="modelValue"
      :files="files"
      :multiple="multiple"
      :collapse-tags="multiple"
      :collapse-tags-tooltip="multiple"
      :size="size"
      :loading="loading"
      :disabled="disabled"
      placeholder="选择数据文件"
      show-meta
      :data-file-picker="scope"
      class="picker-select"
      @update:model-value="emit('update:modelValue', $event)"
      @change="emit('change', $event)"
    />
    <CircularProgress :loading="loading" />
  </div>
</template>

<script setup lang="ts">
/**
 * 分析页 tab 内通用的「选择数据文件」控件。
 *
 * 每个 tab 一份（`scope` 决定 `data-file-picker` 契约值），文件选择因此
 * 天然互不影响；e2e 也按该属性定位，不再依赖「页面上第几个 el-select」。
 * 空文件列表由父级 tab 渲染 `el-empty`，本组件只负责选择器本身。
 */
import type { DataFile } from '../../../types'
import FileSelect from '../../../components/common/FileSelect.vue'
import CircularProgress from '../../../components/common/CircularProgress.vue'

type PickerScope = 'single' | 'wafer' | 'correlation' | 'multi'

const props = withDefaults(defineProps<{
  /** v-model：单选 number|null；多选 number[] */
  modelValue: number | number[] | null
  files: DataFile[]
  /** 契约属性值：single | wafer | correlation | multi */
  scope: PickerScope
  multiple?: boolean
  label?: string
  size?: '' | 'large' | 'default' | 'small'
  loading?: boolean
  disabled?: boolean
  /** true 时选择器撑满容器（左侧配置卡内用） */
  block?: boolean
}>(), {
  multiple: false,
  label: '选择数据文件',
  size: 'small',
  loading: false,
  disabled: false,
  block: false,
})

const emit = defineEmits<{
  (e: 'update:modelValue', val: number | number[] | null): void
  (e: 'change', val: number | number[] | null): void
}>()

const inputId = `analysis-file-${props.scope}`
</script>

<style scoped>
.dp-analysis-filepicker {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.picker-label {
  font-size: 12px;
  color: var(--text-2);
  white-space: nowrap;
  font-weight: 500;
}

.picker-select {
  width: 320px;
  max-width: 100%;
  min-width: 0;
}

/* 左栏卡片里撑满：label 与选择器上下排 */
.dp-analysis-filepicker--block {
  display: block;
}

.dp-analysis-filepicker--block .picker-label {
  display: block;
  margin-bottom: 4px;
}

.dp-analysis-filepicker--block .picker-select {
  width: 100%;
}

@media (max-width: 720px) {
  .picker-select {
    width: 100%;
  }
}
</style>
