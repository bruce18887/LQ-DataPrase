<template>
  <div>
    <p style="color:var(--text-secondary);margin-bottom:12px">对比两个文件的 Serial 数据差异（超出阈值 3% 标红）</p>
    <el-row :gutter="12">
      <el-col :span="6">
        <el-select v-model="localFile1" placeholder="文件1 (ATE)" style="width:100%">
          <el-option v-for="f in files" :key="f.id" :label="f.filename" :value="f.id" />
        </el-select>
      </el-col>
      <el-col :span="6">
        <el-select v-model="localFile2" placeholder="文件2 (Bench)" style="width:100%">
          <el-option v-for="f in files" :key="f.id" :label="f.filename" :value="f.id" />
        </el-select>
      </el-col>
      <el-col :span="4">
        <el-input-number v-model="localThreshold" :min="0" :max="20" :step="0.5" style="width:100%" />
      </el-col>
      <el-col :span="4">
        <el-button type="primary" @click="onAnalyze" :loading="loading">分析</el-button>
      </el-col>
    </el-row>
    <el-table v-if="result" :data="result.summary" stripe style="margin-top:12px">
      <el-table-column prop="param" label="参数" show-overflow-tooltip />
      <el-table-column prop="compared" label="对比数" width="100" />
      <el-table-column prop="fail_count" label="Fail" width="80" />
      <el-table-column prop="pass_rate" label="通过率(%)" width="110" />
      <el-table-column prop="max_diff" label="最大偏差(%)" width="120" />
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  files: any[]
  loading: boolean
  result: any
}>()

const emit = defineEmits<{
  analyze: [file1: number, file2: number, threshold: number]
}>()

const localFile1 = ref<number | null>(null)
const localFile2 = ref<number | null>(null)
const localThreshold = ref(3)

function onAnalyze() {
  if (localFile1.value && localFile2.value) {
    emit('analyze', localFile1.value, localFile2.value, localThreshold.value)
  }
}
</script>
