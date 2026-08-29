<template>
  <el-card v-if="show" shadow="hover" :body-style="{ padding: '12px' }">
    <el-collapse v-model="collapse" style="border: none">
      <el-collapse-item title="坐标轴范围设置" name="axis">
        <div class="axis-body">
          <div class="axis-item">
            <label class="axis-label">X轴</label>
            <el-select :model-value="axisModeX" size="small" style="width: 95px"
              @update:model-value="(v: string) => emit('update:axisModeX', v as AxisMode)">
              <el-option label="数据分布" value="data" />
              <el-option label="西格玛" value="sigma" />
              <el-option label="自定义" value="custom" />
            </el-select>
            <el-select v-if="axisModeX === 'sigma'" :model-value="sigmaX" size="small" style="width: 65px; margin-left: 6px"
              @update:model-value="(v: number) => emit('update:sigmaX', v)">
              <el-option :value="3" label="3σ" /><el-option :value="4" label="4σ" /><el-option :value="6" label="6σ" />
            </el-select>
            <template v-if="axisModeX === 'custom'">
              <el-input-number :model-value="customMinX" size="small" :precision="4" :controls="false"
                style="width: 100px; margin-left: 6px" placeholder="最小值"
                @update:model-value="(v: number | undefined) => emit('update:customMinX', v ?? 0)" />
              <span style="margin: 0 3px">~</span>
              <el-input-number :model-value="customMaxX" size="small" :precision="4" :controls="false"
                style="width: 100px" placeholder="最大值"
                @update:model-value="(v: number | undefined) => emit('update:customMaxX', v ?? 0)" />
            </template>
          </div>
          <div class="axis-item">
            <label class="axis-label">Y轴</label>
            <el-select :model-value="axisModeY" size="small" style="width: 95px"
              @update:model-value="(v: string) => emit('update:axisModeY', v as AxisMode)">
              <el-option label="数据分布" value="data" />
              <el-option label="西格玛" value="sigma" />
              <el-option label="自定义" value="custom" />
            </el-select>
            <el-select v-if="axisModeY === 'sigma'" :model-value="sigmaY" size="small" style="width: 65px; margin-left: 6px"
              @update:model-value="(v: number) => emit('update:sigmaY', v)">
              <el-option :value="3" label="3σ" /><el-option :value="4" label="4σ" /><el-option :value="6" label="6σ" />
            </el-select>
            <template v-if="axisModeY === 'custom'">
              <el-input-number :model-value="customMinY" size="small" :precision="4" :controls="false"
                style="width: 100px; margin-left: 6px" placeholder="最小值"
                @update:model-value="(v: number | undefined) => emit('update:customMinY', v ?? 0)" />
              <span style="margin: 0 3px">~</span>
              <el-input-number :model-value="customMaxY" size="small" :precision="4" :controls="false"
                style="width: 100px" placeholder="最大值"
                @update:model-value="(v: number | undefined) => emit('update:customMaxY', v ?? 0)" />
            </template>
          </div>
        </div>
      </el-collapse-item>
    </el-collapse>
  </el-card>
</template>

<script setup lang="ts">
import { ref } from 'vue'

type AxisMode = 'data' | 'sigma' | 'custom'

withDefaults(defineProps<{
  show: boolean
  axisModeX: AxisMode
  axisModeY: AxisMode
  sigmaX: number
  sigmaY: number
  customMinX: number
  customMinY: number
  customMaxX: number
  customMaxY: number
}>(), {
  show: false,
  axisModeX: 'data',
  axisModeY: 'data',
  sigmaX: 3,
  sigmaY: 3,
  customMinX: 0,
  customMinY: 0,
  customMaxX: 0,
  customMaxY: 0,
})

const emit = defineEmits<{
  (e: 'update:axisModeX', v: AxisMode): void
  (e: 'update:axisModeY', v: AxisMode): void
  (e: 'update:sigmaX', v: number): void
  (e: 'update:sigmaY', v: number): void
  (e: 'update:customMinX', v: number): void
  (e: 'update:customMinY', v: number): void
  (e: 'update:customMaxX', v: number): void
  (e: 'update:customMaxY', v: number): void
}>()

// 折叠面板开合状态是本卡片局部 UI 状态（父组件无需感知）
const collapse = ref<string[]>([])
</script>

<style scoped>
.axis-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.axis-item {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.axis-label {
  font-size: 13px;
  color: var(--text-2, #909399);
  white-space: nowrap;
  min-width: 30px;
}

:deep(.el-collapse-item__header) {
  font-size: 13px;
  color: var(--text-2, #909399);
  border: none;
  padding: 4px 0;
}

:deep(.el-collapse-item__wrap) {
  border: none;
}

:deep(.el-collapse-item__content) {
  padding: 8px 0 0 0;
}
</style>
