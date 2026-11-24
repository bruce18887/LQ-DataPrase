<template>
  <el-collapse-transition>
    <div v-if="visible && active" class="upload-section" data-testid="file-upload-area">
      <div class="upload-options">
        <label class="upload-option">
          <span>加入组合（可选）</span>
          <el-select-v2
            v-model="selectedCombinationId"
            :options="combinationOptions"
            :disabled="lockCombination"
            clearable
            filterable
            placeholder="选择组合"
            aria-label="加入组合（可选）"
            data-testid="import-combination"
          />
        </label>
        <label class="upload-option">
          <span>批次号（可选）</span>
          <el-input
            v-model="batchNo"
            maxlength="40"
            placeholder="留空则使用解析批次号"
            aria-label="上传批次号（可选）"
            data-testid="import-batch-no"
          />
        </label>
        <label class="upload-option upload-option-tags">
          <span>手动标签</span>
          <el-select
            v-model="manualTags"
            multiple
            filterable
            allow-create
            default-first-option
            :multiple-limit="20"
            placeholder="输入标签后回车"
            aria-label="手动标签"
            data-testid="import-manual-tags"
            @change="onManualTagsChange"
          />
        </label>
      </div>
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
import { computed, ref, watch } from 'vue'
import { UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { datafilesApi } from '../../../api/datafiles'
import type { DataCombination } from '../../../types'

const props = withDefaults(defineProps<{
  visible: boolean
  active?: boolean
  combinations?: DataCombination[]
  combinationId?: number | null
  lockCombination?: boolean
}>(), {
  active: true,
  combinations: () => [],
  combinationId: null,
  lockCombination: false,
})

const emit = defineEmits<{
  'upload-success': []
}>()

const uploadProgress = ref(0)
const selectedCombinationId = ref<number | null>(props.combinationId ?? null)
const batchNo = ref('')
const manualTags = ref<string[]>([])
const combinationOptions = computed(() => props.combinations.map((combo) => ({
  value: combo.id,
  label: combo.name,
})))
const selectedCombination = computed(() =>
  props.combinations.find((combo) => combo.id === selectedCombinationId.value) ?? null,
)
const managedTagKeys = computed(() => {
  const name = selectedCombination.value?.name.trim()
  if (!name) return new Set<string>()
  const keys = new Set([name.toLowerCase()])
  if (batchNo.value.trim()) keys.add(`${name} / ${batchNo.value.trim()}`.toLowerCase())
  return keys
})

watch(() => props.combinationId, (value) => {
  selectedCombinationId.value = value ?? null
})
watch([selectedCombinationId, batchNo], () => {
  manualTags.value = sanitizeManualTags(manualTags.value)
})

function sanitizeManualTags(tags: string[]) {
  const seen = new Set<string>()
  return tags.map((tag) => tag.trim()).filter((tag) => {
    const key = tag.toLowerCase()
    if (!tag || managedTagKeys.value.has(key) || seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function onManualTagsChange(tags: string[]) {
  const sanitized = sanitizeManualTags(tags)
  if (sanitized.length !== tags.length) {
    manualTags.value = sanitized
    ElMessage.warning('系统标签由组合自动维护，不能作为手动标签重复添加')
  }
}

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
  const tags = sanitizeManualTags(manualTags.value)
  manualTags.value = tags
  try {
    const { data } = await datafilesApi.upload(options.file, (pct: number) => {
      uploadProgress.value = pct
    }, {
      combinationId: selectedCombinationId.value,
      batchNo: batchNo.value.trim(),
      tags,
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
  background: var(--bg-2);
  border: 1px dashed var(--border-2);
  border-radius: 10px;
}

.upload-options {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 12px;
  padding: 12px;
  background: var(--bg);
  border: 1px solid var(--border-2);
  border-radius: 8px;
}

.upload-option {
  display: grid;
  align-content: start;
  gap: 6px;
  min-width: 0;
  color: var(--text-2);
  font-size: var(--p-fs-dense);
}

.upload-option > span {
  color: var(--text-2);
}

.upload-text {
  font-size: var(--p-fs-base);
  color: var(--text-2);
  margin-top: 8px;
}

.upload-hint {
  font-size: var(--p-fs-dense);
  color: var(--text-3);
  margin-top: 4px;
}

@media (max-width: 760px) {
  .upload-options {
    grid-template-columns: 1fr;
  }
}

:root[data-theme="night"] .upload-section {
  border-color: rgba(255, 255, 255, 0.1);
}
</style>
