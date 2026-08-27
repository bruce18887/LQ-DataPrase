<template>
  <span class="col-filter" :class="{ 'col-filter-active': isActive }" @click.stop>
    <el-popover
      v-model:visible="popVisible"
      :width="210"
      trigger="click"
      placement="bottom-start"
      popper-class="col-filter-popper"
    >
      <template #reference>
        <el-button
          text
          size="small"
          class="col-filter-btn"
          :title="isActive ? `清除${label}筛选` : `筛选${label}`"
          :aria-label="`筛选${label}`"
          :data-testid="`col-filter-btn-${testid}`"
        >
          <el-icon :size="13">
            <Filter :class="{ 'filter-icon-active': isActive }" />
          </el-icon>
        </el-button>
      </template>

      <!-- 下拉模式 -->
      <div v-if="mode === 'select'" class="col-filter-body">
        <el-select
          :model-value="modelValue || ''"
          filterable
          clearable
          size="small"
          :placeholder="`全部${label}`"
          :data-testid="`col-filter-select-${testid}`"
          @change="onSelectChange"
        >
          <el-option v-for="opt in options" :key="opt" :label="opt" :value="opt" />
        </el-select>
        <div class="col-filter-actions">
          <el-button
            v-if="isActive"
            size="small"
            text
            type="primary"
            :data-testid="`col-filter-clear-${testid}`"
            @click="clear"
          >清除筛选</el-button>
        </div>
      </div>

      <!-- 文本模式 -->
      <div v-else class="col-filter-body">
        <el-input
          :model-value="modelValue || ''"
          size="small"
          clearable
          :placeholder="`包含…`"
          :data-testid="`col-filter-input-${testid}`"
          @input="onInputDebounced"
          @keyup.enter="onInputNow"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <div class="col-filter-actions">
          <el-button
            v-if="isActive"
            size="small"
            text
            type="primary"
            :data-testid="`col-filter-clear-${testid}`"
            @click="clear"
          >清除筛选</el-button>
        </div>
      </div>
    </el-popover>
  </span>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Filter, Search } from '@element-plus/icons-vue'

const props = withDefaults(defineProps<{
  /** 当前筛选值（'' = 未激活） */
  modelValue: string
  /** select: 下拉（产品/格式/标签）；input: 文本 contains */
  mode: 'select' | 'input'
  /** select 模式的候选项 */
  options?: string[]
  /** 表头列名（用于 aria/提示） */
  label: string
  /** 测试定位 id */
  testid: string
}>(), {
  options: () => [],
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const popVisible = ref(false)
const isActive = computed(() => props.modelValue !== '' && props.modelValue != null)

let debounceTimer: ReturnType<typeof setTimeout> | undefined

function onSelectChange(value: string | number | undefined) {
  emit('update:modelValue', typeof value === 'string' ? value : '')
}

function onInputDebounced(value: string) {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => emit('update:modelValue', value), 300)
}

function onInputNow(value: string) {
  if (debounceTimer) clearTimeout(debounceTimer)
  emit('update:modelValue', value)
}

function clear() {
  if (debounceTimer) clearTimeout(debounceTimer)
  emit('update:modelValue', '')
  popVisible.value = false
}
</script>

<style scoped>
.col-filter {
  display: inline-flex;
  align-items: center;
  margin-left: 4px;
}

.col-filter-btn {
  padding: 2px;
  height: auto;
  color: var(--text-tertiary);
}

.col-filter-btn:hover {
  color: var(--brand-primary);
}

.filter-icon-active {
  color: var(--brand-primary);
}

.col-filter-active .col-filter-btn {
  color: var(--brand-primary);
}

/* popover（teleported=false 时挂在表头单元格内） */
.col-filter-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.col-filter-actions {
  display: flex;
  justify-content: flex-end;
  min-height: 0;
}
</style>

<style>
/* popper 渲染在 body，scoped 打不到，用全局覆盖 */
.col-filter-popper .el-select,
.col-filter-popper .el-input {
  width: 100%;
}
</style>
