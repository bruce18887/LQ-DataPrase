<template>
  <el-select-v2
    v-bind="attrs"
    :model-value="modelValue"
    :options="options"
    :multiple="multiple"
    :clearable="clearable"
    :collapse-tags="collapseTags"
    :collapse-tags-tooltip="collapseTagsTooltip"
    :size="size || undefined"
    :placeholder="placeholder"
    :disabled="disabled"
    :loading="loading"
    :id="id || undefined"
    :popper-class="dropdownClass"
    :height="360"
    :item-height="itemHeight"
    filterable
    :filter-method="onFilter"
    @update:model-value="onUpdate"
    @change="onChange"
    @visible-change="onVisibleChange"
    @clear="onClear"
  >
    <template #default="{ item }">
      <div class="dp-file-option">
        <span class="dp-file-option__name">
          <template v-for="(seg, i) in segmentsFor(item.file.filename ?? '')" :key="i">
            <mark v-if="seg.mark">{{ seg.text }}</mark>
            <template v-else>{{ seg.text }}</template>
          </template>
        </span>
        <span v-if="showMeta" class="dp-file-option__meta">{{ metaText(item.file) }}</span>
      </div>
    </template>
    <template #empty>
      <div class="dp-empty-hint">无匹配文件</div>
    </template>
    <template #footer>
      <div class="dp-file-count-hint">{{ q ? '匹配' : '共' }} {{ options.length }} 项</div>
    </template>
  </el-select-v2>
</template>

<script setup lang="ts">
import { computed, ref, useAttrs } from 'vue'
import type { DataFile } from '../../types'
import {
  buildFileOptions,
  matchFile,
  metaText,
  normalizeQuery,
} from './fileSelectModel'
import { highlightSegments } from '../../utils/selectOptions'

type FileSelectSize = 'large' | 'default' | 'small' | ''

interface Props {
  /** 文件列表（由父级拉取后传入，组件不做远程加载） */
  files: DataFile[]
  /** v-model：单选 number|null；多选 number[] */
  modelValue: number | number[] | null
  /** 多选模式 */
  multiple?: boolean
  placeholder?: string
  clearable?: boolean
  collapseTags?: boolean
  collapseTagsTooltip?: boolean
  size?: FileSelectSize
  disabled?: boolean
  /** 透传给 el-select 的 loading（父级文件列表加载态） */
  loading?: boolean
  /** 绑定内部原生 input（label[for] 指向依赖） */
  id?: string
  /** 追加到下拉 popper 根节点的类（内部自带 dp-file-select-dropdown） */
  popperClass?: string
  /** 富信息行：文件名 + program · format · 行数 · 大小 · 上传时间 */
  showMeta?: boolean
  /** 多选模式已选文件置顶（单选恒保持 files 原序） */
  pinSelected?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  multiple: false,
  placeholder: '选择数据文件',
  clearable: false,
  collapseTags: false,
  collapseTagsTooltip: false,
  size: '',
  disabled: false,
  loading: false,
  id: undefined,
  popperClass: '',
  showMeta: false,
  pinSelected: true,
})

interface Emits {
  (e: 'update:modelValue', value: number | number[] | null): void
  (e: 'change', value: number | number[] | null): void
  (e: 'visible-change', visible: boolean): void
  (e: 'clear'): void
}
const emit = defineEmits<Emits>()

const attrs = useAttrs()
defineOptions({ inheritAttrs: false })

const filterText = ref('')
const q = computed(() => normalizeQuery(filterText.value))

/** 已选文件 id（保持选中顺序，多选置顶按此序） */
const pinnedOrder = computed<number[]>(() =>
  props.multiple && props.pinSelected && Array.isArray(props.modelValue)
    ? [...props.modelValue]
    : [],
)

const options = computed(() =>
  buildFileOptions(
    props.files.filter((f) => matchFile(f, q.value)),
    q.value,
    pinnedOrder.value,
  ),
)

/** v2 的虚拟滚动要求固定行高：富信息行两行约 40px，取 48；紧凑行维持 34。 */
const itemHeight = computed(() => (props.showMeta ? 48 : 34))

const dropdownClass = computed(() =>
  ['dp-file-select-dropdown', props.popperClass].filter(Boolean).join(' '),
)

function segmentsFor(text: string) {
  return highlightSegments(text, q.value)
}

// ---------- 事件流转 ----------
function onFilter(query: string) {
  filterText.value = query
}
function onVisibleChange(visible: boolean) {
  if (!visible) filterText.value = ''
  emit('visible-change', visible)
}
function onUpdate(val: number | number[] | null) {
  emit('update:modelValue', val)
}
function onChange(val: number | number[] | null) {
  emit('change', val)
}
function onClear() {
  emit('clear')
}
</script>

<style scoped>
.dp-file-option {
  display: flex;
  flex-direction: column;
  justify-content: center;
  width: 100%;
  height: 100%;
  line-height: normal;
}

.dp-file-option__name {
  font-size: var(--p-fs-small);
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.dp-file-option__name :deep(mark) {
  color: var(--brand);
  font-weight: 600;
  background-color: color-mix(in srgb, var(--brand) 15%, transparent);
  padding: 0 2px;
  border-radius: 2px;
}

.dp-file-option__meta {
  font-size: var(--p-fs-micro);
  color: var(--text-2);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>

<!-- 下拉 teleport 到 body，scoped 样式无法命中，需 unscoped + 命名空间前缀 -->
<style>
.dp-file-select-dropdown .el-select-dropdown__item {
  line-height: normal;
  padding: 0 20px;
}

.dp-file-select-dropdown .dp-file-count-hint {
  font-size: var(--p-fs-micro);
  color: var(--text-2);
  text-align: center;
}

.dp-file-select-dropdown .el-select-dropdown__empty {
  color: var(--text-2);
}
</style>
