<template>
  <div class="serial-selector">
    <el-select
      ref="selectRef"
      :model-value="modelValue"
      multiple
      filterable
      automatic-dropdown
      placeholder="搜索序列号"
      collapse-tags
      collapse-tags-tooltip
      class="seri-select"
      aria-label="对比序列"
      :loading="loading"
      :disabled="options.length === 0"
      :multiple-limit="MAX_SELECTED"
      :filter-method="filterMethod"
      @update:model-value="$emit('update:modelValue', clamp($event))"
      @keydown.capture="onSelectKeydown"
      @visible-change="onVisibleChange"
    >
      <el-option v-for="s in filteredItems" :key="s" :label="String(s)" :value="s" />
      <template #empty>
        <div class="empty-hint">无匹配序列</div>
      </template>
      <template #footer>
        <div v-if="kw && matches.length > 0" class="match-hint">
          匹配 {{ matches.length }} 项{{ matches.length > SERIAL_RENDER_CAP ? `（显示前 ${SERIAL_RENDER_CAP}）` : '' }}，按 Enter 全选
        </div>
        <div v-else-if="!kw && options.length > SERIAL_RENDER_CAP" class="match-hint">
          仅显示前 {{ SERIAL_RENDER_CAP }} 项，可搜索或直接全选
        </div>
      </template>
    </el-select>
    <div class="seri-actions">
      <el-button size="small" link type="primary" :disabled="options.length === 0" @click="selectAll">
        全选
      </el-button>
      <el-button size="small" link type="primary" :disabled="modelValue.length === 0" @click="clearAll">
        清空
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'

/**
 * 对比序列选择器：交互与查看数据「搜索测试项」输入框（TestColumnSelector）
 * 一致——输入关键词 → 按 Enter 全选匹配（合并语义增量累计）。
 * 选项 = 两文件公共序列（升序），默认由父级勾选前 10 颗。
 */
interface Props {
  /** 已选序列 */
  modelValue: number[]
  /** 全部公共序列（升序） */
  options: number[]
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), { loading: false })
const emit = defineEmits<{
  (e: 'update:modelValue', value: number[]): void
}>()

/** 已选序列上限（el-table 无列虚拟化：200 序列 × 4 列 ≈ 800 列已到现实极限） */
const MAX_SELECTED = 200

/** 下拉渲染上限：el-option 是完整组件实例，序列上万时挂载即冻结主线程；
 * 渲染截断，全选/Enter 全选仍作用于完整集合 */
const SERIAL_RENDER_CAP = 300

const filterText = ref('')
const selectRef = ref<{ $el: HTMLElement }>()

const kw = computed(() => filterText.value.trim().toLowerCase())

/** 匹配项：大小写不敏感子串匹配（序列号转字符串比较） */
const matches = computed(() =>
  kw.value ? props.options.filter((s) => String(s).toLowerCase().includes(kw.value)) : [],
)

/** 下拉选项：有关键字显示过滤结果，否则全量；渲染层一律截断到前 N */
const filteredItems = computed(() =>
  (kw.value ? matches.value : props.options).slice(0, SERIAL_RENDER_CAP))

/** 超限裁剪：保留前 N（配合 multiple-limit 双保险） */
function clamp(sel: number[]): number[] {
  return sel.length > MAX_SELECTED ? sel.slice(0, MAX_SELECTED) : sel
}

/** 接管 EP 内置过滤（el-select filterable 模式下 query 变化回调） */
function filterMethod(query: string) {
  filterText.value = query
}

/**
 * 捕获阶段拦截 Enter：输入框有关键字且有匹配时 = 全选。
 * EP 的 handleKeydown 在冒泡阶段处理 Enter 并 stopPropagation，捕获阶段先执行才能抢先。
 * 输入框为空（kw 空）时不拦截，保留 EP 原行为（选中高亮项）。
 */
function onSelectKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && matches.value.length > 0) {
    e.preventDefault()
    e.stopPropagation()
    selectMatches()
  }
}

/**
 * 清空过滤（含 EP 内部 query）：states.inputValue 是 EP 内部状态，外部只能
 * 通过原生 input 事件（onInput → handleQueryChange）同步，故置空后派发 input 事件。
 */
function clearFilterInput() {
  filterText.value = ''
  const inputEl = selectRef.value?.$el?.querySelector('input')
  if (inputEl) {
    inputEl.value = ''
    inputEl.dispatchEvent(new Event('input', { bubbles: true }))
  }
}

/** 下拉打开时聚焦过滤框；关闭时清空过滤，避免残留过滤误导下一次打开 */
function onVisibleChange(visible: boolean) {
  if (visible) {
    // EP 2.14 automatic-dropdown：菜单在 wrapper 获焦（mousedown）时就打开，此时
    // filter input 仍 display:none，EP 的 click 焦点逻辑被 isFocusable 守卫跳过，
    // 焦点困在 tabindex=-1 的 wrapper 上——打开后须显式聚焦 input 才能打字过滤。
    nextTick(() => selectRef.value?.$el?.querySelector('input')?.focus())
  } else {
    clearFilterInput()
  }
}

function selectAll() {
  emit('update:modelValue', clamp([...props.options]))
}

function clearAll() {
  emit('update:modelValue', [])
}

/** 合并语义：已选 ∪ 匹配项（增量累计，误选靠清空/单项取消）；超 200 裁剪 */
function selectMatches() {
  if (matches.value.length === 0) return
  emit('update:modelValue', clamp([...new Set([...props.modelValue, ...matches.value])]))
  clearFilterInput()
}
</script>

<style scoped>
.serial-selector {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 260px;
}

.seri-select {
  width: 100%;
}

.seri-actions {
  display: flex;
  justify-content: flex-end;
  gap: 2px;
}

.seri-actions :deep(.el-button + .el-button) {
  margin-left: 2px;
}

.match-hint {
  padding: 6px 12px;
  font-size: 12px;
  color: var(--text-2);
  border-top: 1px solid var(--border);
}

.empty-hint {
  padding: 8px 12px;
  font-size: 12px;
  color: var(--text-3);
}
</style>
