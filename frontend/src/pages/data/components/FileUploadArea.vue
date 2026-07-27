<template>
  <el-collapse-transition>
    <div v-show="visible" class="upload-section">
      <el-upload
        drag
        :http-request="handleUpload"
        accept=".csv,.txt,.dat,.zip,.7z,.rar"
        :show-file-list="false"
        multiple
      >
        <el-icon :size="48"><UploadFilled /></el-icon>
        <div class="upload-text">拖拽文件到此处 或 <em>点击上传</em></div>
        <div class="upload-hint">支持多文件上传，ZIP/7z/RAR 压缩包会自动解压</div>
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

async function handleUpload(options: { file: File }) {
  uploadProgress.value = 0
  try {
    await datafilesApi.upload(options.file, (pct: number) => {
      uploadProgress.value = pct
    })
    ElMessage.success(`${options.file.name} 上传成功`)
    emit('upload-success')
  } catch {
    ElMessage.error(`${options.file.name} 上传失败`)
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
