<template>
  <div class="param-selector">
    <div class="selector-label">选择参数 (↑↓ 切换)</div>
    <el-select
      :model-value="selectedParam"
      placeholder="选择测试参数"
      filterable
      size="small"
      style="width: 100%"
      @change="onParamChange"
      popper-class="param-select-dropdown"
    >
      <el-option v-for="p in params" :key="p" :label="p" :value="p" />
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
const props = defineProps<{
  params: string[]
  selectedParam: string
}>()

const emit = defineEmits<{
  'update:selectedParam': [value: string]
  prev: []
  next: []
}>()

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
</style>
