<template>
  <el-collapse-transition>
    <div v-show="visible" class="upload-section">
      <el-upload
        drag
        :http-request="handleUpload"
        :before-upload="beforeUpload"
        accept=".csv,.zip"
        :show-file-list="false"
        multiple
      >
        <el-icon :size="48"><UploadFilled /></el-icon>
        <div class="upload-text">拖拽文件到此处 或 <em>点击上传</em></div>
        <div class="upload-hint">支持 CSV 与 ZIP 压缩包，ZIP 自动解析为批次数据</div>
      </el-upload>
      <el-progress
        v-if="uploadProgress > 0 && uploadProgress < 100"
        :percentage="uploadProgress"
        style="margin-top: 8px"
      />
    </div>
  </el-collapse-transition>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { datafilesApi } from '../../../api/datafiles'

defineProps<{
  visible: boolean
}>()

const emit = defineEmits<{
  'upload-success': []
}>()

const uploadProgress = ref(0)

/** 允许上传的文件扩展名：CSV 单文件 + ZIP 压缩包（后端解压其中 CSV 注册为批次） */
const ALLOWED_EXTS = ['.csv', '.zip']

function beforeUpload(file: File): boolean {
  const ext = file.name.toLowerCase().slice(file.name.lastIndexOf('.'))
  if (!ALLOWED_EXTS.includes(ext)) {
    ElMessage.error(`${file.name} 不是 CSV 或 ZIP 文件，仅支持 .csv / .zip 格式`)
    return false
  }
  return true
}

async function handleUpload(options: { file: File }) {
  uploadProgress.value = 0
  try {
    const { data } = await datafilesApi.upload(options.file, (pct: number) => {
      uploadProgress.value = pct
    })
    // ZIP 批量导入时后端返回该 zip 注册的文件数；csv 单文件保持原提示
    const count = Array.isArray(data) ? data.length : 0
    const message = count > 0 && /\.zip$/i.test(options.file.name)
      ? `${options.file.name} 上传成功，导入 ${count} 个文件`
      : `${options.file.name} 上传成功`
    ElMessage.success(message)
    emit('upload-success')
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
  } finally {
    uploadProgress.value = 0
  }
}
</script>

<style scoped>
.upload-section {
  margin-bottom: 16px;
  padding: 16px;
  background: var(--bg-secondary);
  border: 1px dashed var(--border-default);
  border-radius: 10px;
}

.upload-text {
  font-size: 14px;
  color: var(--text-secondary);
  margin-top: 8px;
}

.upload-hint {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 4px;
}

:root[data-theme="night"] .upload-section {
  border-color: rgba(255, 255, 255, 0.1);
}
</style>
