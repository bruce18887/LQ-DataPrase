<script setup lang="ts">
import { groupColor, type WeightGroupDto } from '../weightChartOption'

const props = defineProps<{ groups: WeightGroupDto[]; visible: number[]; colors: string[] }>()
const emit = defineEmits<{ (e: 'update:visible', value: number[]): void }>()

function onChange(next: (string | number | boolean)[]) {
  emit('update:visible', (next as number[]).slice().sort((a, b) => a - b))
}
</script>

<template>
  <div class="weight-chips">
    <el-checkbox-group
      :model-value="visible"
      class="chips-grid"
      @change="onChange"
    >
      <el-checkbox
        v-for="g in groups"
        :key="g.index"
        :value="g.index"
        class="weight-chip"
      >
        <span class="chip-dot" :style="{ backgroundColor: groupColor(props.colors, g.index) }" />
        <span class="chip-name">{{ g.name }}</span>
      </el-checkbox>
    </el-checkbox-group>
    <p class="chip-hint">
      组内四条按线型区分（实线 / 虚线 / 点线 / 点划线）；均值线为深灰粗实线。
    </p>
  </div>
</template>

<style scoped>
.weight-chips {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.chips-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  max-height: 132px;
  overflow-y: auto;
}

.chip-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 2px;
  margin-right: 6px;
  vertical-align: middle;
  /* 实色块而不是 tint：项目实测里 tint 对比度到不了 3:1（memory「token 对比度实测口径」）。 */
}

.chip-name {
  vertical-align: middle;
}

.chip-hint {
  margin: 0;
  font-size: var(--p-fs-dense);
  color: var(--text-2);
}
</style>
