<template>
  <div class="step-card">
    <div class="step-header">
      <span class="step-number">1</span>
      <span class="step-title">选择参数</span>
      <span class="step-count">已选 {{ modelValue.length }} / 共 {{ params.length }} 个</span>
    </div>
    <div class="step-body">
      <el-select
        ref="selectRef"
        :model-value="modelValue"
        multiple
        filterable
        placeholder="点击选择要导出的参数"
        collapse-tags
        collapse-tags-tooltip
        class="param-select"
        aria-label="选择导出参数"
        :filter-method="filterMethod"
        @update:model-value="$emit('update:modelValue', $event)"
        @keydown.capture="onSelectKeydown"
        @visible-change="onVisibleChange"
      >
        <el-option v-for="p in filteredItems" :key="p" :label="p" :value="p" />
        <template #footer>
          <div v-if="matches.length > 0" class="match-hint">
            匹配 {{ matches.length }} 项，按 Enter 全选
          </div>
        </template>
      </el-select>
      <el-button size="small" :disabled="params.length === 0" @click="selectAll">全选</el-button>
      <el-button size="small" :disabled="modelValue.length === 0" @click="clearAll">清空</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

interface Props {
  params: string[]
  modelValue: string[]
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: string[]): void
}>()

const filterText = ref('')
const selectRef = ref<{ $el: HTMLElement }>()

const kw = computed(() => filterText.value.trim().toLowerCase())

/** 匹配项：大小写不敏感子串匹配，与 ParamSelector.vue 过滤逻辑一致 */
const matches = computed(() =>
  kw.value ? props.params.filter((p) => p.toLowerCase().includes(kw.value)) : [],
)

/** 下拉选项：有关键字显示过滤结果，否则全量 */
const filteredItems = computed(() => (kw.value ? matches.value : props.params))

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
  emit('update:modelValue', [...props.params])
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
.step-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-muted);
  border-radius: 10px;
  padding: 14px 16px;
}

.step-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.step-number {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--brand-primary);
  color: var(--text-inverse);
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}

.step-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.step-count {
  margin-left: auto;
  font-size: 11px;
  font-weight: 500;
  color: var(--text-tertiary);
}

.step-body {
  display: flex;
  align-items: center;
  gap: 10px;
}

.param-select {
  flex: 1;
}

.match-hint {
  padding: 6px 12px;
  font-size: 12px;
  color: var(--text-secondary);
  border-top: 1px solid var(--border-muted);
}
</style>
