<!-- frontend/src/pages/analysis/components/SerialSettingsForm.vue
     序列分布渲染设置（按 Site 拆分 / 点径 / 透明度），放进标题栏齿轮弹层。
     状态由父级 useSerialChartSettings 持有，本组件只做展示 + 事件（2026-09-13 齿轮化）。 -->
<template>
  <div class="ss-form">
    <el-checkbox
      v-if="canSplit"
      :model-value="splitBySite"
      size="small"
      @update:model-value="(v: string | number | boolean) => emit('update:splitBySite', Boolean(v))"
    >
      按 Site 拆分
    </el-checkbox>
    <div class="ss-item">
      <div class="ss-item__head">
        <span>点径 {{ effSize }} {{ sizeAutoHint }}</span>
      </div>
      <el-slider
        :model-value="effSize" :min="2" :max="8" :step="1" size="small"
        @update:model-value="(v: number | [number, number]) => emit('update:pointSize', Array.isArray(v) ? v[0] : v)"
      />
    </div>
    <div class="ss-item">
      <div class="ss-item__head">
        <span>透明度 {{ effOpacityPct }}% {{ opacityAutoHint }}</span>
      </div>
      <el-slider
        :model-value="effOpacityPct" :min="10" :max="100" :step="5" size="small"
        @update:model-value="(v: number | [number, number]) => emit('update:opacityPct', Array.isArray(v) ? v[0] : v)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  /** 站点数 ≥2 才显示「按 Site 拆分」（单站点无意义） */
  canSplit: boolean
  splitBySite: boolean
  /** 当前生效点径（自动或手动覆盖后） */
  effSize: number
  sizeAutoHint: string
  /** 当前生效透明度百分比（自动或手动覆盖后） */
  effOpacityPct: number
  opacityAutoHint: string
}>(), {})

const emit = defineEmits<{
  (e: 'update:splitBySite', v: boolean): void
  /** 点径手动覆盖值 */
  (e: 'update:pointSize', v: number): void
  /** 透明度手动覆盖百分比 */
  (e: 'update:opacityPct', v: number): void
}>()
</script>

<style scoped>
.ss-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ss-item__head {
  font-size: var(--p-fs-micro);
  color: var(--text-2);
  margin-bottom: 2px;
}
</style>
