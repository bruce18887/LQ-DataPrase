<template>
  <div class="batch-export-panel">
    <div class="panel-header">
      <span class="panel-icon">📥</span>
      <span class="panel-title">批量导出</span>
    </div>

    <div class="panel-body">
      <el-row :gutter="12" align="middle">
        <el-col :span="8">
          <div class="param-select-row">
            <el-select v-model="localParams" multiple placeholder="选择参数" collapse-tags collapse-tags-tooltip style="flex:1">
              <el-option v-for="p in params" :key="p" :label="p" :value="p" />
            </el-select>
            <el-button size="small" @click="selectAll" :disabled="params.length === 0">全选</el-button>
            <el-button size="small" @click="clearAll" :disabled="localParams.length === 0">清空</el-button>
          </div>
        </el-col>
        <el-col :span="3">
          <el-select v-model="localSigma" style="width:100%">
            <el-option :value="3" label="3 Sigma" />
            <el-option :value="4" label="4 Sigma" />
            <el-option :value="6" label="6 Sigma" />
          </el-select>
        </el-col>
        <el-col :span="4">
          <el-button @click="onExportSigma" :loading="exporting">导出 Sigma Limit</el-button>
        </el-col>
        <el-col :span="4">
          <el-button type="primary" @click="onExportBatch('xlsx')" :loading="exporting">批量导出 Excel</el-button>
        </el-col>
        <el-col :span="4">
          <el-button @click="onExportBatch('pptx')" :loading="exporting">批量导出 PPT</el-button>
        </el-col>
      </el-row>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  params: string[]
  exporting: boolean
}>()

const emit = defineEmits<{
  exportSigma: [sigma: number]
  exportBatch: [params: string[], format: string]
}>()

const localParams = ref<string[]>([])
const localSigma = ref(3)

function selectAll() {
  localParams.value = [...props.params]
}

function clearAll() {
  localParams.value = []
}

function onExportSigma() {
  emit('exportSigma', localSigma.value)
}

function onExportBatch(format: string) {
  emit('exportBatch', localParams.value, format)
}
</script>

<style scoped>
.batch-export-panel {
  background: var(--bg-primary);
  border: 1px solid var(--border-muted);
  border-radius: 12px;
  overflow: hidden;
  margin-top: 16px;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 18px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-muted);
}

.panel-icon {
  font-size: 16px;
}

.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.panel-body {
  padding: 18px;
}

.param-select-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

/* Night overrides */
:root[data-theme="night"] .batch-export-panel {
  background: rgba(255, 255, 255, 0.03);
  border-color: rgba(255, 255, 255, 0.08);
}

:root[data-theme="night"] .panel-header {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.06);
}
</style>
