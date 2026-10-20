<script setup lang="ts">
import { computed } from 'vue'
import type { WeightDocDto } from '../weightChartOption'
import WeightSeriesTable from './WeightSeriesTable.vue'

const props = defineProps<{
  modelValue: boolean
  doc: WeightDocDto
  showMean: boolean
  colors: string[]
}>()
const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>()

const open = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const rowCount = computed(() =>
  props.doc.series_count + (props.showMean ? props.doc.group_count : 0),
)
</script>

<template>
  <el-drawer
    v-model="open"
    direction="rtl"
    size="780px"
    :with-header="false"
    :destroy-on-close="true"
    class="weight-drawer"
  >
    <div class="weight-drawer-body" data-testid="weight-drawer">
      <header class="weight-drawer-head">
        <h2>数值明细</h2>
        <span class="drawer-desc">
          {{ rowCount }} 行 · {{ doc.group_count }} 测试项 · 均值{{ showMean ? '已显示' : '已隐藏' }}
        </span>
        <span class="grow" />
        <button
          type="button"
          class="drawer-close"
          data-testid="weight-close-table"
          aria-label="关闭数值明细"
          @click="open = false"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <path d="m6 6 12 12M18 6 6 18" />
          </svg>
        </button>
      </header>

      <div class="weight-drawer-table">
        <WeightSeriesTable :doc="doc" :show-mean="showMean" :colors="colors" />
      </div>

      <footer class="weight-drawer-foot">
        表格始终显示全部测试项的数值；图表上的分组开关只影响画廊，不影响这里的行。均值行随「显示均值」开关增减。
      </footer>
    </div>
  </el-drawer>
</template>

<style scoped>
.weight-drawer-body {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.weight-drawer-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 0 0 auto;
  padding: 14px 20px;
  border-bottom: 1px solid var(--border);
}

.weight-drawer-head h2 {
  font-size: var(--p-fs-lead);
  font-weight: 700;
  color: var(--text);
}

.drawer-desc {
  font-size: var(--p-fs-micro);
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}

.weight-drawer-head .grow {
  flex: 1;
}

.drawer-close {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border: 1px solid var(--border-2);
  border-radius: var(--p-radius-md);
  background: var(--card);
  color: var(--text-2);
  cursor: pointer;
}

.drawer-close:hover {
  border-color: var(--brand);
  color: var(--brand);
}

.drawer-close svg {
  width: 14px;
  height: 14px;
}

.weight-drawer-table {
  flex: 1 1 auto;
  min-height: 0;
  padding: 14px 20px;
}

.weight-drawer-foot {
  flex: 0 0 auto;
  padding: 10px 20px 12px;
  border-top: 1px solid var(--border);
  font-size: var(--p-fs-micro);
  color: var(--text-2);
}
</style>

<!-- 抽屉会 teleport 到 body：作用域样式选不到 el-drawer 自己的 body，按 FileSelect 的既有做法用命名空间放到全局。 -->
<style>
.weight-drawer .el-drawer__body {
  display: flex;
  flex-direction: column;
  padding: 0;
  overflow: hidden;
}
</style>
