<template>
  <div class="dash-footer">
    <el-button type="primary" size="large" :loading="exporting" @click="exportHtml">
      <span>📥</span> 保存 HTML 报表
    </el-button>
    <p class="dash-footer-note">📅 最后更新: {{ updateTime }} | LiqunData ATE 数据分析软件</p>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../../api'

const props = defineProps<{
  fileId: number | null
  filename: string
  updateTime: string
}>()

const exporting = ref(false)

async function exportHtml() {
  exporting.value = true
  try {
    const resp = await api.post('/export/dashboard_html/', {
      file_id: props.fileId,
    }, { responseType: 'blob' })
    const url = window.URL.createObjectURL(new Blob([resp.data]))
    const link = document.createElement('a')
    link.href = url
    const now = new Date()
    const ts = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}_${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}${String(now.getSeconds()).padStart(2, '0')}`
    const fileLabel = (props.filename || 'report').replace('.csv', '')
    link.download = `Dashboard_${fileLabel}_${ts}.html`
    link.click()
    window.URL.revokeObjectURL(url)
  } catch (error) {
    console.error('导出失败:', error)
    // 错误 toast 由 axios 拦截器统一弹出
  } finally {
    exporting.value = false
  }
}
</script>

<style scoped>
/* ================================================================
   Footer
   ================================================================ */
.dash-footer {
  text-align: center;
  margin-top: 36px;
}
.dash-footer-note {
  margin: 16px 0 0;
  color: var(--text-tertiary);
  font-size: 12px;
}
</style>
