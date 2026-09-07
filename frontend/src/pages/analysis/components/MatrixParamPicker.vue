<!-- frontend/src/pages/analysis/components/MatrixParamPicker.vue -->
<template>
  <el-card shadow="hover" :body-style="{ padding: '12px' }" data-matrix-param-picker>
    <div class="matrix-param-header">
      <label class="section-label">选择参数（已选 {{ selected.length }}/{{ params.length }}）</label>
      <div class="matrix-param-actions">
        <el-button link type="primary" size="small" :disabled="visibleParams.length === 0" @click="selectAllVisible">全选</el-button>
        <el-button link type="primary" size="small" :disabled="selected.length === 0" @click="emit('update:selected', [])">清空</el-button>
      </div>
    </div>
    <el-input
      v-model="keyword"
      placeholder="搜索参数"
      clearable
      size="small"
      data-matrix-search
    />
    <div class="chips-box">
      <button
        v-for="p in visibleParams"
        :key="p"
        type="button"
        class="chip"
        :class="{ on: selected.includes(p) }"
        :title="p"
        @click="toggle(p)"
      >{{ p }}</button>
      <div v-if="visibleParams.length === 0" class="chips-empty">无匹配参数</div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  /** 全量候选参数（本 tab 文件的带 Limit 参数列表） */
  params: string[]
  /** 已选参数集合（v-model:selected，父组件持有真值） */
  selected: string[]
}>()

const emit = defineEmits<{
  (e: 'update:selected', value: string[]): void
}>()

const keyword = ref('')

/** 搜索只影响可见性，不改已选集合；大小写不敏感包含匹配 */
const visibleParams = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return props.params
  return props.params.filter((p) => p.toLowerCase().includes(k))
})

function toggle(p: string) {
  const next = props.selected.includes(p)
    ? props.selected.filter((x) => x !== p)
    : [...props.selected, p]
  emit('update:selected', next)
}

/** 全选 = 当前可见项并入已选（搜索状态下只加可见项） */
function selectAllVisible() {
  const set = new Set(props.selected)
  for (const p of visibleParams.value) set.add(p)
  emit('update:selected', [...set])
}
</script>

<style scoped>
.matrix-param-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.matrix-param-header .section-label {
  margin-bottom: 0;
}

.matrix-param-actions {
  display: flex;
  gap: 4px;
}

.section-label {
  font-size: 11px;
  color: var(--text-2);
  font-weight: 500;
  display: block;
}

.chips-box {
  margin-top: 8px;
  max-height: 180px;
  overflow-y: auto;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.chip {
  font: inherit;
  font-size: 11px;
  line-height: 1.4;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border-radius: 12px;
  padding: 1px 9px;
  cursor: pointer;
  border: 1px solid var(--border-2);
  background: var(--card);
  color: var(--text-2);
}

.chip.on {
  border-color: var(--brand);
  background: var(--active-bg);
  color: var(--brand);
  font-weight: 600;
}

.chips-empty {
  font-size: 11px;
  color: var(--text-3);
  padding: 6px 2px;
}
</style>
