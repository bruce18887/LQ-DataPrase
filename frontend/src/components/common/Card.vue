<template>
  <div :class="['dp-card', `dp-card--${variant}`]">
    <div v-if="$slots.header || desc" class="dp-card__header">
      <span class="dp-card__title"><slot name="header"></slot></span>
      <span v-if="desc" class="dp-card__desc">{{ desc }}</span>
      <span v-if="$slots.actions" class="dp-card__actions"><slot name="actions"></slot></span>
    </div>
    <div class="dp-card__body">
      <slot></slot>
    </div>
    <div v-if="$slots.footer" class="dp-card__footer">
      <slot name="footer"></slot>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * Card 卡片组件（指南 §10.4）
 *
 * default：--card 底 + --border + 圆角 12 + --shadow-sm + 内边距 16
 * section：卡头浅底带（color-mix(--bg-2 60%, --card)）+ 底分隔线，
 *           标题 14/700 + --text-3 说明（desc）+ 右侧操作区（#actions）
 * 旧 neon 发光 / 2px 粗边框 / :root.theme-* 覆盖已移除
 *
 * @example
 * <Card variant="section" desc="最近 24 小时">
 *   <template #header>📊 Bin 分布</template>
 *   内容区域
 * </Card>
 */

interface Props {
  variant?: 'default' | 'section'
  desc?: string
}

withDefaults(defineProps<Props>(), {
  variant: 'default',
  desc: ''
})
</script>

<style scoped>
.dp-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: var(--shadow-sm);
  padding: 16px;
  transition: box-shadow 0.25s ease, border-color 0.25s ease;
}

/* Section 卡：卡头浅底带 */
.dp-card--section {
  padding: 0;
  overflow: hidden;
}

.dp-card--section .dp-card__header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: color-mix(in srgb, var(--bg-2) 60%, var(--card));
  border-bottom: 1px solid var(--border);
}

.dp-card__title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
}

.dp-card__desc {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-3);
}

.dp-card__actions {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.dp-card__body {
  padding: 16px;
  color: var(--text-2);
}

.dp-card--default .dp-card__body {
  padding: 0; /* default 变体卡身已含 16 内边距 */
}

.dp-card__footer {
  padding: 12px 16px;
  border-top: 1px solid var(--border);
  background: color-mix(in srgb, var(--bg-2) 60%, var(--card));
  color: var(--text-2);
}
</style>
