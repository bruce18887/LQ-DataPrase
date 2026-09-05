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
      :disabled="disabled"
      placeholder="选择数据文件"
      show-meta
      :data-file-picker="scope"
      :popper-class="popperClass"
      class="picker-select"
      @update:model-value="emit('update:modelValue', $event)"
      @change="emit('change', $event)"
    />
    <!-- 加载状态由本组件的常驻槽位呈现，**不能**透传给 el-select 的 loading：
         EP 会往后缀插槽里放一个 `is-loading` 无限旋转图标，reference 的 rect
         随之逐帧变化 → popper 逐帧重定位 → 下拉选项永不安定（懒加载 tab 里参数
         请求要几秒，这几十秒内 e2e 永远点不中选项，真人也看到下拉抖动） -->
    <!-- 加载圈占位常驻：不预留宽度时，它挂载/移除会让 select 宽度变化，
         而下拉 popper 跟随 reference 定位 → 选项一直在动（e2e 判定
         “element is not stable” 点不中，真人也会看到下拉抖动） -->
    <span class="picker-spin" aria-hidden="true">
      <CircularProgress :loading="loading" />
    </span>
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
  /** 本 tab 参数列表/取数进行中：只驱动常驻槽位的加载圈 */
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
/**
 * 每个 picker 的下拉面板独立 class。
 *
 * popper 被 teleport 到 body，不随 tab pane 的 `display:none` 隐藏：若共用一个
 * class，隐藏 pane 的下拉面板仍会参与选项查询，而它的 reference 尺寸为零 →
 * popper 逐帧重定位（永不安定），还容易点到另一个 tab 的文件。
 */
const popperClass = `dp-file-picker-${props.scope}`
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
  /* 宽度只由容器决定（不随内容/加载圈变化），popper 定位才稳定 */
  flex: 1 1 auto;
  width: 320px;
  min-width: 0;
  max-width: 360px;
}

/* 加载圈槽位：44px 常驻，空闲时内部无内容也不收缩 */
.picker-spin {
  width: 44px;
  height: 44px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
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
  max-width: none;
}

@media (max-width: 720px) {
  .picker-select {
    width: 100%;
  }
}
</style>
