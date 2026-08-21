<template>
  <el-select
    v-bind="attrs"
    :model-value="modelValue"
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
    filterable
    :filter-method="onFilter"
    @update:model-value="onUpdate"
    @change="onChange"
    @visible-change="onVisibleChange"
    @clear="onClear"
  >
    <template v-if="groupBy">
      <el-option-group
        v-for="g in groupedItems"
        :key="g.key"
        :label="g.label"
        :class="g.pinned ? 'dp-file-group--pinned' : ''"
      >
        <el-option v-for="f in g.files" :key="f.id" :label="f.filename" :value="f.id">
          <div class="dp-file-option">
            <span class="dp-file-option__name" v-html="f.filenameHtml" />
            <span v-if="showMeta" class="dp-file-option__meta">{{ metaText(f) }}</span>
          </div>
        </el-option>
      </el-option-group>
    </template>
    <el-option
      v-else
      v-for="f in filteredItems"
      :key="f.id"
      :label="f.filename"
      :value="f.id"
    >
      <div class="dp-file-option">
        <span class="dp-file-option__name" v-html="f.filenameHtml" />
        <span v-if="showMeta" class="dp-file-option__meta">{{ metaText(f) }}</span>
      </div>
    </el-option>
    <!-- 自定义 filter-method 绕过 EP 内部过滤，空态判定只看到「0 个 option」→
         no-match-text prop 不生效，须用 #empty 插槽提供文案 -->
    <template #empty>
      <div class="dp-empty-hint">无匹配文件</div>
    </template>
  </el-select>
</template>

<script setup lang="ts">
import { computed, ref, useAttrs } from 'vue'
import type { DataFile } from '../../types'
import { formatSize, formatTime } from '../../utils/format'

type FileSelectSize = 'large' | 'default' | 'small' | ''
type GroupKey = 'program_name' | 'format_type' | ''

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
  /** 按字段分组（空值归「未分组」；'' 不分组） */
  groupBy?: GroupKey
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
  groupBy: '',
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
/** 已选文件 id 数组（保持选中顺序，多选置顶按此序） */
const pinnedOrder = computed<number[]>(() =>
  props.multiple && props.pinSelected && Array.isArray(props.modelValue)
    ? [...props.modelValue]
    : []
)
const pinnedIds = computed(() => new Set(pinnedOrder.value))
const filteredItems = computed<DisplayFile[]>(() =>
  toDisplay(
    sortFiles(
      props.files.filter((f) => matchFile(f, q.value)),
      q.value,
      pinnedIds.value,
      pinnedOrder.value
    ),
    q.value
  )
)
const groupedItems = computed<FileGroup[]>(() =>
  props.groupBy ? groupFiles(filteredItems.value, props.groupBy, pinnedIds.value, pinnedOrder.value) : []
)
const dropdownClass = computed(() =>
  ['dp-file-select-dropdown', props.popperClass].filter(Boolean).join(' ')
)

// ---------- 事件流转 ----------
function onFilter(query: string) {
  filterText.value = query
}
function onVisibleChange(visible: boolean) {
  // 关闭下拉时清空过滤，下次打开恢复全量列表
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

// ---------- 纯函数：过滤 / 高亮 / 排序 / 分组 ----------

/** 查询归一化：去首尾空白 + 小写 */
function normalizeQuery(raw: string): string {
  return raw.trim().toLowerCase()
}

/** HTML 转义（v-html 注入前必须，文件名是外部数据防 XSS） */
function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/** 正则元字符转义 */
function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** 高亮匹配段：原文 HTML 转义后注入 <mark>（大小写不敏感） */
function highlightMatch(text: string, query: string): string {
  const safe = escapeHtml(text)
  if (!query) return safe
  const esc = escapeRegex(escapeHtml(query))
  return safe.replace(new RegExp(`(${esc})`, 'gi'), '<mark>$1</mark>')
}

/** 匹配：filename / program_name / batch_name 任一包含（对齐后端 search_fields） */
function matchFile(f: DataFile, query: string): boolean {
  if (!query) return true
  return [f.filename, f.program_name, f.batch_name]
    .some((v) => (v ?? '').toLowerCase().includes(query))
}

/** 排序权重：0=filename 前缀 > 1=filename 包含 > 2=仅 program/batch 命中 */
function fileRank(f: DataFile, query: string): number {
  const name = (f.filename ?? '').toLowerCase()
  if (name.startsWith(query)) return 0
  if (name.includes(query)) return 1
  return 2
}

/**
 * 排序：无 query 保持 files 原序（多选时已选置顶）；
 * 有 query 按权重排序 + localeCompare 平局决胜，多选时已选再置顶。
 * 置顶组按选中顺序（pinnedOrder），而非 files 原序。
 */
function sortFiles(
  list: DataFile[],
  query: string,
  pinned: Set<number>,
  pinnedOrder: number[]
): DataFile[] {
  const ranked = query
    ? [...list].sort((a, b) => {
        const r = fileRank(a, query) - fileRank(b, query)
        return r !== 0 ? r : a.filename.localeCompare(b.filename)
      })
    : list
  if (pinned.size) {
    const p = pinnedOrder
      .map((id) => ranked.find((f) => f.id === id))
      .filter((f): f is DataFile => Boolean(f))
    const rest = ranked.filter((f) => !pinned.has(f.id))
    return [...p, ...rest]
  }
  return ranked
}

interface DisplayFile extends DataFile {
  /** 高亮后的文件名 HTML */
  filenameHtml: string
}
function toDisplay(list: DataFile[], query: string): DisplayFile[] {
  return list.map((f) => ({ ...f, filenameHtml: highlightMatch(f.filename ?? '', query) }))
}

/** 富信息行文本：program · format · N 行 · 大小 · 上传时间 */
function metaText(f: DataFile): string {
  return [
    f.program_name,
    f.format_type,
    `${f.row_count ?? 0} 行`,
    f.file_size ? formatSize(f.file_size) : '',
    f.created_at ? formatTime(f.created_at) : '',
  ]
    .filter(Boolean)
    .join(' · ')
}

interface FileGroup {
  key: string
  label: string
  pinned: boolean
  files: DisplayFile[]
}
/** 分组：已选成首组「已选 (n)」（按选中顺序），其余按字段首次出现顺序分组，空值归「未分组」 */
function groupFiles(
  list: DisplayFile[],
  key: GroupKey,
  pinned: Set<number>,
  pinnedOrder: number[]
): FileGroup[] {
  const groups: FileGroup[] = []
  const pinnedFiles = pinned.size
    ? pinnedOrder
        .map((id) => list.find((f) => f.id === id))
        .filter((f): f is DisplayFile => Boolean(f))
    : []
  if (pinnedFiles.length) {
    groups.push({ key: '__pinned__', label: `已选 (${pinnedFiles.length})`, pinned: true, files: pinnedFiles })
  }
  const map = new Map<string, DisplayFile[]>()
  for (const f of list) {
    if (pinned.has(f.id)) continue
    const raw = key ? (f[key] ?? '') : ''
    const label = raw || '未分组'
    if (!map.has(label)) map.set(label, [])
    map.get(label)!.push(f)
  }
  for (const [label, files] of map) {
    groups.push({ key: label, label, pinned: false, files })
  }
  return groups
}
</script>

<style scoped>
.dp-file-option {
  display: flex;
  flex-direction: column;
  width: 100%;
  line-height: normal;
}

.dp-file-option__name {
  font-size: 13px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.dp-file-option__name :deep(mark) {
  color: var(--brand-primary);
  font-weight: 600;
  background-color: rgba(var(--brand-primary-rgb), 0.15);
  padding: 0 2px;
  border-radius: 2px;
}

.dp-file-option__meta {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>

<!-- 下拉 teleport 到 body，scoped 样式无法命中，需 unscoped + 命名空间前缀 -->
<style>
.dp-file-select-dropdown .el-select-dropdown__list {
  max-height: 360px;
}

.dp-file-select-dropdown .el-select-dropdown__item {
  line-height: normal;
  padding: 6px 20px;
  /* 覆盖 EP 默认 height:34px + overflow:hidden——富信息行（文件名 + meta）约
     40px 会被纵向裁剪，第二行显示不全；min-height 保证非 show-meta 场景
     下拉项保持紧凑观感 */
  height: auto;
  min-height: 34px;
}

.dp-file-select-dropdown .el-select-group__title {
  color: var(--text-secondary);
  font-size: 12px;
}

.dp-file-select-dropdown .dp-file-group--pinned .el-select-group__title {
  color: var(--brand-primary);
  font-weight: 600;
}

.dp-file-select-dropdown .el-select-dropdown__empty {
  color: var(--text-secondary);
}
</style>
