<template>
  <el-card header="📥 批量导出" style="margin-top:16px">
    <el-row :gutter="12">
      <el-col :span="6">
        <el-select v-model="localParams" multiple placeholder="选择参数" style="width:100%">
          <el-option v-for="p in params" :key="p" :label="p" :value="p" />
        </el-select>
      </el-col>
      <el-col :span="4">
        <el-select v-model="localSigma" style="width:100%">
          <el-option :value="3" label="3 Sigma" />
          <el-option :value="4" label="4 Sigma" />
          <el-option :value="6" label="6 Sigma" />
        </el-select>
      </el-col>
      <el-col :span="4">
        <el-button @click="onExportSigma" :loading="exporting">导出 Sigma Limit</el-button>
      </el-col>
      <el-col :span="5">
        <el-button @click="onExportBatch('xlsx')" :loading="exporting">批量导出 Excel</el-button>
      </el-col>
      <el-col :span="5">
        <el-button @click="onExportBatch('pptx')" :loading="exporting">批量导出 PPT</el-button>
      </el-col>
    </el-row>
  </el-card>
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

function onExportSigma() {
  emit('exportSigma', localSigma.value)
}

function onExportBatch(format: string) {
  emit('exportBatch', localParams.value, format)
}
</script>
