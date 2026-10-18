<template>
  <div class="dash-footer">
    <el-button type="primary" size="large" :loading="exporting" @click="exportHtml">
      <span>📥</span> 保存 HTML 报表
    </el-button>
    <JobProgressChip :percent="progress" :active="exporting" />
    <p class="dash-footer-note">📅 最后更新: {{ updateTime }} | LiqunData ATE 数据分析软件</p>
  </div>
</template>

<script setup lang="ts">
import JobProgressChip from '../../../components/common/JobProgressChip.vue'
import { useJobExport } from '../../../composables/useJobExport'

const props = defineProps<{
  fileId: number | null
  updateTime: string
}>()

const job = useJobExport()
const exporting = job.exporting
const progress = job.progress

async function exportHtml() {
  if (!props.fileId) return
  // 报表要跑 compute_dashboard_summary + 内联 base64 图表，属于「一个人点、全站等」
  // 的那一类，所以走作业。文件名以后端渲染的模板为准（旧的前端时间戳兜底随之删掉）。
  const res = await job.run('export_html_report', { file_id: props.fileId })
  if (!res.ok && res.reason !== 'gave-up') {
    // gave-up 时 run() 已经弹过那句 info（前端停止等待，作业没取消），这里不重复提示
    console.error('导出失败:', res.message)
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
  font-size: var(--p-fs-dense);
}
</style>
