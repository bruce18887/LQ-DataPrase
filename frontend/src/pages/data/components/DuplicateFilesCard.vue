<template>
  <MaintenanceCard
    test-id="duplicate-files-card"
    :visible="groups.length > 0"
    title="重复文件"
    tag-text="文件名与大小完全相同"
    tag-type="danger"
    :alert="{
      title: '以下文件按「文件名 + 大小」判定重复。每组保留一项、删除其余；未改选的组默认保留最早导入的那条。',
      type: 'warning',
    }"
    :truncated-note="truncatedNote"
  >
    <!-- 为什么这颗 radio 的标签**不写**「未改选的组默认保留」（终审 F2，2026-11-15 实测缺陷）：
         `strategy` 全卡只被 `applyStrategy()` 读一次；未改选组的保留项走
         `keepIdForGroup` → `defaultKeepId` = `files[0].id` = 最早那条，**不看 strategy**。
         即「拨动策略 radio 不改变未改选组的默认值」，只有点右边那颗「应用到未改选的 N 组」
         才真的生效。标签里出现「默认保留」就是在承诺一个不发生的行为 —— 而卡片上面那条 alert
         已经在说「未改选的组默认保留最早导入的那条」，同一个屏幕两句互斥的话，用户拨到「最新导入」
         却不点应用时，被物理删掉的是**最新那一份**（设计 §5.5 已否掉回收站，删了就没了）。
         真相只留 alert 那一句；标签只说这颗策略的作用范围。类名 `dup-strategy` 不动（e2e 按它选）。
      -->
    <div class="dup-strategy">
      <span class="dup-strategy-label">一键策略（只作用未改选的组）</span>
      <el-radio-group v-model="strategy" size="small" :disabled="!canDelete">
        <el-radio value="earliest">最早导入</el-radio>
        <el-radio value="latest">最新导入</el-radio>
      </el-radio-group>
      <el-button
        size="small"
        :disabled="!canDelete || untouched.length < 1"
        data-testid="dup-apply-strategy"
        @click="applyStrategy"
      >
        应用到未改选的 {{ untouched.length }} 组
      </el-button>
    </div>

    <div
      v-for="group in groups"
      :key="groupKey(group)"
      class="dup-group"
      data-testid="dup-group"
    >
      <div class="dup-group-header">
        <span class="dup-group-key mono">{{ group.filename }}</span>
        <span class="dup-group-size mono">{{ formatSize(group.file_size) }}</span>
        <span class="dup-group-count">{{ group.files.length }} 个</span>
      </div>
      <el-radio-group
        class="dup-keep-rows"
        :model-value="keepFor(group)"
        :disabled="!canDelete"
        @update:model-value="(id: number) => pick(group, id)"
      >
        <div
          v-for="f in group.files"
          :key="f.id"
          class="dup-file-row"
          data-testid="dup-keep-row"
          :data-keep="f.id === keepFor(group) ? 'keep' : 'delete'"
        >
          <el-radio :value="f.id">
            <span class="dup-file-state">{{ f.id === keepFor(group) ? '保留' : '将删除' }}</span>
            <span class="dup-file-loc mono">{{ f.file_type === 'batch' ? `[${f.batch_name}]` : '[单文件]' }}</span>
            <span class="dup-file-id mono">#{{ f.id }}</span>
            <span class="dup-file-time">{{ dupImportText(f.created_at) }}</span>
            <span class="dup-file-size mono">{{ formatSize(f.file_size) }}</span>
          </el-radio>
        </div>
      </el-radio-group>
    </div>

    <template #footer-left>
      <el-checkbox v-model="deleteConfirmed" :disabled="!canDelete">
        <span :style="{ color: canDelete ? 'var(--error)' : 'var(--text-3)', fontWeight: 600 }">
          {{ canDelete ? '我已确认按以上选择删除' : '仅管理员可删除重复文件' }}
        </span>
      </el-checkbox>
    </template>
    <template #footer-right>
      <el-button
        type="danger"
        plain
        :disabled="!deleteConfirmed || !canDelete"
        :loading="fixing"
        @click="submit"
      >
        <el-icon><Delete /></el-icon> {{ summaryText }}
      </el-button>
    </template>
  </MaintenanceCard>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Delete } from '@element-plus/icons-vue'
import type { DuplicateGroup } from '../../../api/datafiles'
import { formatSize } from '../../../utils/format'
import {
  applyStrategyToUntouched,
  deleteSummaryText,
  groupKey,
  keepIdForGroup,
  resolveKeepIds,
  truncatedNoteText,
  dupImportText,
  type KeepStrategy,
} from '../../../utils/dupKeep'
import MaintenanceCard from './MaintenanceCard.vue'

/**
 * 重复文件卡（批3a）。这里原来的两支「✓ 保留 / 删除」是**只读 `el-tag`**，
 * 没有 `@click`：文案把后端既定策略渲染成用户的承诺，而用户什么都选不了。
 *
 * 选择状态只有一份 `choice`（Map）。曾经考虑过再加一个 `touched` 集合，那是两份事实：
 * `choice.has(key)` 就是「用户改选过」，删掉集合后「一键策略只碰未改选组」这条
 * 由 `applyStrategyToUntouched` 自己判，不需要调用方再维护一个影子。
 */
const props = defineProps<{
  groups: DuplicateGroup[]
  /** 总组数（groups 只是展示切片） */
  totalCount: number
  fixing: boolean
  /** 当前用户是否有删除权限（管理员） */
  canDelete: boolean
}>()

const emit = defineEmits<{
  fix: [keepIds: number[]]
}>()

const deleteConfirmed = ref(false)
const choice = ref(new Map<string, number>())
const strategy = ref<KeepStrategy>('earliest')

// 检查结果刷新后：确认态与选择态一起清零。留着旧选择等于拿上一批 id 去删这一批 ——
// 服务端会按白名单拒（400），但那只是兜底，界面不该先骗一次。
watch(() => [props.groups, props.totalCount], () => {
  deleteConfirmed.value = false
  choice.value = new Map()
})

const untouched = computed(() =>
  props.groups.filter((g) => !choice.value.has(groupKey(g))))

const truncatedNote = computed(() => truncatedNoteText(props.totalCount, props.groups.length))
const summaryText = computed(() => deleteSummaryText(props.groups))

function keepFor(group: DuplicateGroup): number {
  return keepIdForGroup(group, choice.value)
}

function pick(group: DuplicateGroup, id: number) {
  choice.value.set(groupKey(group), id)
}

function applyStrategy() {
  choice.value = applyStrategyToUntouched(props.groups, choice.value, strategy.value)
}

function submit() {
  emit('fix', resolveKeepIds(props.groups, choice.value))
}
</script>

<style scoped>
.dup-strategy {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
  padding: 8px 12px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
}

.dup-strategy-label {
  font-size: var(--p-fs-dense);
  color: var(--text-2);
}

.dup-group {
  padding: 10px 12px;
  margin-bottom: 8px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: 8px;
}

.dup-group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.dup-group-key {
  font-size: var(--p-fs-dense);
  font-weight: 600;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 55%;
}

.dup-group-size {
  font-size: var(--p-fs-micro);
  color: var(--info);
}

.dup-group-count {
  font-size: var(--p-fs-micro);
  color: var(--text-3);
  padding: 1px 6px;
  background: var(--bg);
  border-radius: 8px;
}

.dup-keep-rows {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
}

.dup-file-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.dup-file-state {
  min-width: 3.5em;
  font-weight: 600;
  color: var(--text);
}

.dup-file-row[data-keep='keep'] .dup-file-state {
  color: var(--success);
}

.dup-file-row[data-keep='delete'] .dup-file-state {
  color: var(--error);
}

.dup-file-loc,
.dup-file-id,
.dup-file-time,
.dup-file-size {
  font-size: var(--p-fs-micro);
  color: var(--text-2);
}

.mono {
  font-family: var(--font-mono);
}
</style>
