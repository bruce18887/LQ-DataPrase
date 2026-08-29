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
import api from '../../../api'
import { downloadBlob, extractFilenameFromContentDisposition } from '../../../utils/download'
import { getExportTimeoutMs } from '../../../utils/exportTimeout'

const props = defineProps<{
  fileId: number | null
  filename: string
  updateTime: string
}>()

const exporting = ref(false)

async function exportHtml() {
  exporting.value = true
  try {
    const resp = await api.post('/export/html_report/', {
      file_id: props.fileId,
    }, { responseType: 'blob', timeout: await getExportTimeoutMs() })
    // 文件名优先解析后端模板渲染的 Content-Disposition，缺失时用时间戳兜底
    const fname = extractFilenameFromContentDisposition(resp.headers?.['content-disposition'])
      ?? (() => {
        const now = new Date()
        const ts = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}_${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}${String(now.getSeconds()).padStart(2, '0')}`
        const fileLabel = (props.filename || 'report').replace('.csv', '')
        return `Dashboard_${fileLabel}_${ts}.html`
      })()
    downloadBlob(resp.data as Blob, fname)
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
  color: var(--text-3);
  font-size: 12px;
}
</style>
