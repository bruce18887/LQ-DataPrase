<template>
  <el-card v-if="visible" class="repair-card" :data-testid="testId">
    <template #header>
      <div class="card-header">
        <span class="card-title">{{ title }}</span>
        <el-tag :type="tagType" size="small">{{ tagText }}</el-tag>
      </div>
    </template>
    <el-alert
      v-if="alert"
      :title="alert.title"
      :type="alert.type ?? 'warning'"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
    />
    <el-alert
      v-if="truncatedNote"
      :title="truncatedNote"
      type="info"
      :closable="false"
      style="margin-bottom: 12px"
    />
    <slot />
    <div class="card-footer">
      <slot name="footer-left" />
      <slot name="footer-right" />
    </div>
  </el-card>
</template>

<script setup lang="ts">
/**
 * 修复中心卡片的公共外壳：卡片标题行 + 警示条 + 主体 + 底部操作栏。
 *
 * 四张卡（重复文件 / 孤立磁盘文件 / 孤立数据库记录 / 产品名缺失）此前各存一份
 * **逐字节相同**的 `.card-header` / `.card-title` / `.card-footer` 与同样的
 * el-card + tag + alert + footer 结构 —— 改一处视觉要翻四个文件才改得齐。
 * 卡片自己的表格 / 分组样式仍留在各卡片里，插槽内容按父作用域编译，
 * 所以 `.action-row` 这类卡片私有 class 照旧生效。
 */
interface RepairAlert {
  title: string
  type?: 'warning' | 'info' | 'success' | 'error'
}

defineProps<{
  /** 稳定测试位点：e2e 按 `[data-testid]` 选卡（repair-center.spec.ts），迁移时不许改值 */
  testId: string
  /** 卡片自身的显示条件（原各卡写在 el-card 上的 v-if） */
  visible: boolean
  title: string
  tagText: string
  tagType: 'danger' | 'warning' | 'info' | 'success'
  alert?: RepairAlert
  /** 「共 N 个，仅显示前 M 个」提示；空串不渲染 */
  truncatedNote?: string
}>()
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-title {
  font-weight: 600;
  color: var(--text);
}

.card-footer {
  margin-top: 12px;
  padding: 12px;
  background: var(--bg-2);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
</style>
