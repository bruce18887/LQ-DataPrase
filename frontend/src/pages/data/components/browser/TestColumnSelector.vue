<template>
  <div class="test-col-selector">
    <el-select
      ref="selectRef"
      :model-value="modelValue"
      multiple
      filterable
      placeholder="搜索测试列"
      collapse-tags
      collapse-tags-tooltip
      class="col-select"
      aria-label="显示测试列"
      :filter-method="filterMethod"
      @update:model-value="$emit('update:modelValue', $event)"
      @keydown.capture="onSelectKeydown"
      @visible-change="onVisibleChange"
    >
      <el-option v-for="c in filteredItems" :key="c" :label="c" :value="c" />
      <template #empty>
        <div class="empty-hint">无匹配测试列</div>
      </template>
      <template #footer>
        <div v-if="matches.length > 0" class="match-hint">
          匹配 {{ matches.length }} 项，按 Enter 全选
        </div>
      </template>
    </el-select>
    <div class="col-actions">
      <el-button size="small" link type="primary" :disabled="cols.length === 0" @click="selectAll">
        全选
      </el-button>
      <el-button size="small" link type="primary" :disabled="modelValue.length === 0" @click="clearAll">
        清空
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

/**
 * 显示测试列选择器：复用导出工具「选择参数」的交互模式——
 * 输入关键词 → 按 Enter 全选匹配测试列（合并语义增量累计）。
 * 选中列 = 查看数据表格仅显示这些测试列；空选中集 = 显示全部（默认）。
 * 模式来源：ExportParamSelector.vue（2026-08-12 方案 A）。
 */
interface Props {
  /** 全部测试列（系统列已由父级排除） */
  cols: string[]
  modelValue: string[]
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: string[]): void
}>()

const filterText = ref('')
const selectRef = ref<{ $el: HTMLElement }>()

const kw = computed(() => filterText.value.trim().toLowerCase())

/** 匹配项：大小写不敏感子串匹配 */
const matches = computed(() =>
  kw.value ? props.cols.filter((c) => c.toLowerCase().includes(kw.value)) : [],
)

/** 下拉选项：有关键字显示过滤结果，否则全量 */
const filteredItems = computed(() => (kw.value ? matches.value : props.cols))

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

/** 下拉关闭时清空过滤，避免残留过滤误导下一次打开 */
function onVisibleChange(visible: boolean) {
  if (!visible) clearFilterInput()
}

function selectAll() {
  emit('update:modelValue', [...props.cols])
}

function clearAll() {
  emit('update:modelValue', [])
}

/** 合并语义：已选 ∪ 匹配项（增量累计，误选靠清空/单项取消） */
function selectMatches() {
  if (matches.value.length === 0) return
  emit('update:modelValue', [...new Set([...props.modelValue, ...matches.value])])
  clearFilterInput()
}
</script>

<style scoped>
.test-col-selector {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.col-actions {
  display: flex;
  justify-content: flex-end;
  gap: 2px;
}

.col-actions :deep(.el-button + .el-button) {
  margin-left: 2px;
}

.match-hint {
  padding: 6px 12px;
  font-size: 12px;
  color: var(--text-secondary);
  border-top: 1px solid var(--border-muted);
}

.empty-hint {
  padding: 8px 12px;
  font-size: 12px;
  color: var(--text-tertiary);
}
</style>
