<template>
  <el-card class="settings-section">
    <template #header>
      <span class="section-title">📄 导出文件名</span>
    </template>
    <el-form label-width="160px" class="export-template-form">
      <div
        v-for="key in templateKeys"
        :key="key"
        class="template-row"
        :class="`template-row--${key}`"
      >
        <el-form-item :label="metaOf(key).label" class="template-form-item">
          <div class="template-controls">
            <el-input
              v-model="templates[key]"
              :data-testid="`template-input-${key}`"
              :placeholder="metaOf(key).default"
              maxlength="200"
              show-word-limit
              class="template-input"
            />
            <el-select
              :data-testid="`template-insert-${key}`"
              :model-value="null"
              :placeholder="'插入变量'"
              size="default"
              class="template-insert"
              @change="(v: string) => insertVariable(key, v)"
            >
              <el-option
                v-for="v in metaOf(key).variables"
                :key="v"
                :value="v"
                :label="`{${v}} ${variableLabel(v)}`"
              />
            </el-select>
            <el-button
              :data-testid="`template-reset-${key}`"
              link
              type="primary"
              @click="resetRow(key)"
            >
              恢复默认
            </el-button>
          </div>
          <div class="template-preview" :data-testid="`template-preview-${key}`">
            预览：{{ previewOf(key) }}
          </div>
        </el-form-item>
      </div>
      <div class="template-hint">
        可用变量：
        <span v-for="v in allVariables" :key="v" class="template-hint__var">
          <code>{&#123;{{ v }}&#125;}</code> {{ variableLabel(v) }}
        </span>
      </div>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ExportTypeKey } from '../../../types'
import {
  EXPORT_TEMPLATE_META,
  EXPORT_TEMPLATE_KEYS,
  EXPORT_TEMPLATE_VARIABLE_LABELS,
  PREVIEW_SAMPLE_VALUES,
} from '../../../constants/export-templates'
import { sanitizeFilename } from '../../../utils/download'

interface Props {
  templates: Record<ExportTypeKey, string>
}
interface Emits {
  (e: 'update:templates', value: Record<ExportTypeKey, string>): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const templateKeys = EXPORT_TEMPLATE_KEYS

function metaOf(key: ExportTypeKey) {
  return EXPORT_TEMPLATE_META[key]
}

function variableLabel(v: string): string {
  return EXPORT_TEMPLATE_VARIABLE_LABELS[v] ?? v
}

function update(key: ExportTypeKey, value: string) {
  emit('update:templates', { ...props.templates, [key]: value })
}

function insertVariable(key: ExportTypeKey, variable: string) {
  if (!variable) return
  update(key, props.templates[key] + `{${variable}}`)
}

function resetRow(key: ExportTypeKey) {
  update(key, metaOf(key).default)
}

/** 与后端渲染一致：已知变量替换样例值，未知占位符保留，非法字符清洗，拼扩展名 */
function previewOf(key: ExportTypeKey): string {
  const template = props.templates[key] || metaOf(key).default
  const rendered = template.replace(/\{(\w+)\}/g, (whole, name: string) => {
    if (name in PREVIEW_SAMPLE_VALUES) return PREVIEW_SAMPLE_VALUES[name]
    return whole
  })
  const cleaned = sanitizeFilename(rendered)
  const base = cleaned || sanitizeFilename(metaOf(key).default.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in PREVIEW_SAMPLE_VALUES ? PREVIEW_SAMPLE_VALUES[name] : whole))
  const ext = metaOf(key).extension
  return base.toLowerCase().endsWith(`.${ext}`) ? base : `${base}.${ext}`
}

const allVariables = computed(() => {
  const set = new Set<string>()
  templateKeys.forEach((key) => metaOf(key).variables.forEach((v) => set.add(v)))
  return [...set]
})
</script>

<style scoped>
.template-row {
  margin-bottom: 4px;
}

.template-form-item {
  margin-bottom: 0;
}

.template-controls {
  display: flex;
  gap: 8px;
  align-items: center;
  width: 100%;
}

.template-input {
  flex: 1;
  max-width: 420px;
}

.template-insert {
  width: 130px;
}

.template-preview {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-secondary);
}

.template-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 2;
}

.template-hint__var {
  margin-right: 12px;
}

.template-hint__var code {
  background-color: var(--bg-tertiary);
  border: 1px solid var(--border-default);
  border-radius: 4px;
  padding: 0 4px;
  color: var(--brand-primary);
}
</style>
