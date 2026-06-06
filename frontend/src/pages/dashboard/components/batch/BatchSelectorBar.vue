<template>
  <div class="batch-selector">
    <el-select
      :model-value="selectedBatch"
      placeholder="选择批次"
      clearable
      @update:model-value="$emit('update:selectedBatch', $event)"
      style="width: 300px"
    >
      <el-option
        v-for="b in batches"
        :key="b.batch_name"
        :label="`${b.batch_name} (${b.count}文件)`"
        :value="b.batch_name"
      />
    </el-select>
    <el-button
      type="primary"
      @click="$emit('load')"
      :loading="loading"
      :disabled="!selectedBatch"
    >
      🔍 加载批次报表
    </el-button>
    <el-button
      v-if="hasData"
      @click="$emit('export')"
      :loading="exporting"
    >
      📥 导出 Excel
    </el-button>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  batches: any[]
  selectedBatch: string
  loading: boolean
  exporting: boolean
  hasData: boolean
}>()

defineEmits<{
  'update:selectedBatch': [value: string]
  'load': []
  'export': []
}>()
</script>

<style scoped>
.batch-selector {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}
</style>
