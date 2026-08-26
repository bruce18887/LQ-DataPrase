<template>
  <div class="param-selector">
    <div class="selector-label">选择参数 (↑↓ 切换)</div>
    <el-select
      :model-value="selectedParam"
      placeholder="输入搜索或选择参数..."
      filterable
      clearable
      size="small"
      style="width: 100%"
      :filter-method="filterMethod"
      :virtual="filteredItems.length > 50"
      @change="onParamChange"
      @visible-change="onVisibleChange"
      popper-class="param-select-dropdown"
    >
      <el-option
        v-for="item in filteredItems"
        :key="item.value"
        :label="item.value"
        :value="item.value"
      >
        <div class="param-option">
          <span class="param-name" v-html="item.highlighted || item.value" />
          <!-- 分类提示：暂时关闭，后续开发启用 -->
          <!-- <span v-if="item.hint" class="param-hint">{{ item.hint }}</span> -->
        </div>
      </el-option>
    </el-select>
    <div class="nav-buttons">
      <el-button :disabled="params.length === 0" size="small" @click="onPrev">
        ◀ 上一个
      </el-button>
      <el-button :disabled="params.length === 0" size="small" @click="onNext">
        下一个 ▶
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

interface ParamItem {
  value: string
  highlighted?: string
  hint?: string
}

const props = defineProps<{
  params: string[]
  selectedParam: string
}>()

const emit = defineEmits<{
  'update:selectedParam': [value: string]
  prev: []
  next: []
}>()

const filterText = ref('')

/** 构建参数列表（带分类提示） */
const allItems = computed<ParamItem[]>(() =>
  props.params.map((p) => ({
    value: p,
    hint: getParamHint(p),
  }))
)

/** 过滤后的列表 */
const filteredItems = computed<ParamItem[]>(() => {
  if (!filterText.value) return allItems.value

  const query = filterText.value.toLowerCase()
  return allItems.value
    .filter((item) => item.value.toLowerCase().includes(query))
    .map((item) => ({
      ...item,
      highlighted: highlightMatch(item.value, filterText.value),
    }))
    .sort((a, b) => {
      // 前缀匹配优先
      const aStarts = a.value.toLowerCase().startsWith(query)
      const bStarts = b.value.toLowerCase().startsWith(query)
      if (aStarts && !bStarts) return -1
      if (!aStarts && bStarts) return 1
      return a.value.localeCompare(b.value)
    })
})

/** 根据参数名推断分类提示 */
function getParamHint(param: string): string {
  const upper = param.toUpperCase()
  if (upper.includes('VOLTAGE') || upper.includes('V_') || upper.startsWith('V')) return '电压'
  if (upper.includes('CURRENT') || upper.includes('I_') || upper.startsWith('I')) return '电流'
  if (upper.includes('RESISTANCE') || upper.includes('R_') || upper.startsWith('R')) return '电阻'
  if (upper.includes('FREQUENCY') || upper.includes('F_') || upper.startsWith('F')) return '频率'
  if (upper.includes('TIME') || upper.includes('T_')) return '时间'
  if (upper.includes('POWER') || upper.includes('P_')) return '功率'
  if (upper.includes('GAIN') || upper.includes('G_')) return '增益'
  if (upper.includes('TEMP') || upper.includes('T_')) return '温度'
  return ''
}

/** 高亮匹配文本 */
function highlightMatch(text: string, query: string): string {
  if (!query) return text
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const regex = new RegExp(`(${escaped})`, 'gi')
  return text.replace(regex, '<mark>$1</mark>')
}

/** 自定义过滤方法 */
function filterMethod(query: string) {
  filterText.value = query
}

/** 下拉框关闭时清空过滤 */
function onVisibleChange(visible: boolean) {
  if (!visible) {
    filterText.value = ''
  }
}

function onParamChange(val: string) {
  emit('update:selectedParam', val)
}

function onPrev() {
  const idx = props.params.indexOf(props.selectedParam)
  if (idx > 0) {
    emit('update:selectedParam', props.params[idx - 1])
  } else if (props.params.length > 0) {
    emit('update:selectedParam', props.params[props.params.length - 1])
  }
  emit('prev')
}

function onNext() {
  const idx = props.params.indexOf(props.selectedParam)
  if (idx < props.params.length - 1) {
    emit('update:selectedParam', props.params[idx + 1])
  } else if (props.params.length > 0) {
    emit('update:selectedParam', props.params[0])
  }
  emit('next')
}
</script>

<style scoped>
.param-selector {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.selector-label {
  font-size: 11px;
  color: var(--text-secondary);
  font-weight: 500;
}

.nav-buttons {
  display: flex;
  gap: 8px;
}

.nav-buttons :deep(.el-button) {
  flex: 1;
  padding: 6px 8px;
  font-size: 12px;
}

.param-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.param-name {
  font-size: 13px;
  color: var(--text-primary);
}

.param-name :deep(mark) {
  color: var(--brand-primary);
  font-weight: 600;
  background-color: rgba(var(--brand-primary-rgb), 0.15);
  padding: 0 2px;
  border-radius: 2px;
}

.param-hint {
  font-size: 11px;
  color: var(--text-secondary);
  margin-left: 12px;
  flex-shrink: 0;
}
</style>
