<template>
  <div class="step-card">
    <div class="step-header">
      <span class="step-number">1</span>
      <span class="step-title">选择参数</span>
      <span class="step-count">已选 {{ modelValue.length }} / 共 {{ params.length }} 个</span>
    </div>
    <div class="step-body">
      <el-select
        :model-value="modelValue"
        multiple
        filterable
        placeholder="点击选择要导出的参数"
        collapse-tags
        collapse-tags-tooltip
        class="param-select"
        aria-label="选择导出参数"
        @update:model-value="$emit('update:modelValue', $event)"
      >
        <el-option v-for="p in params" :key="p" :label="p" :value="p" />
      </el-select>
      <el-button size="small" :disabled="params.length === 0" @click="selectAll">全选</el-button>
      <el-button size="small" :disabled="modelValue.length === 0" @click="clearAll">清空</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
interface Props {
  params: string[]
  modelValue: string[]
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: string[]): void
}>()

function selectAll() {
  emit('update:modelValue', [...props.params])
}

function clearAll() {
  emit('update:modelValue', [])
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
</style>
