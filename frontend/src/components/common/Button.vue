<template>
  <el-button
    :class="['dp-button', `dp-button--${variant}`, { 'dp-button--sm': size === 'small' }]"
    v-bind="$attrs"
  >
    <slot></slot>
  </el-button>
</template>

<script setup lang="ts">
/**
 * Button 按钮组件（扩展 Element Plus Button，指南 §10.2）
 *
 * 型：primary 品牌渐变 / ghost 描边 / danger 纯红实心 / text 链接式
 * 悬停统一 X 抬升（上移 1px + 阴影加深）；旧霓虹发光变体已移除
 *
 * @example
 * <Button variant="primary">主要按钮</Button>
 * <Button variant="ghost">次要按钮</Button>
 * <Button variant="danger" size="small">删除</Button>
 */

interface Props {
  variant?: 'primary' | 'ghost' | 'danger' | 'text'
  size?: 'default' | 'small'
}

withDefaults(defineProps<Props>(), {
  variant: 'primary',
  size: 'default'
})
</script>

<style scoped>
.dp-button {
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  padding: 8px 15px;
  transition:
    transform 0.12s ease,
    box-shadow 0.12s ease,
    background-color 0.12s ease,
    color 0.12s ease,
    border-color 0.12s ease;
}

.dp-button--sm {
  font-size: 12px;
  padding: 5px 11px;
  border-radius: 7px;
}

/* primary：品牌渐变 + 反色文字 */
.dp-button--primary {
  background: var(--grad-brand);
  border: none;
  color: var(--on-brand);
  box-shadow: var(--shadow-sm);
}

.dp-button--primary:hover {
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}

.dp-button--primary:active {
  transform: translateY(0);
}

/* ghost：卡底描边，悬停转品牌色 */
.dp-button--ghost {
  background: var(--card);
  border: 1px solid var(--border-2);
  color: var(--text-2);
}

.dp-button--ghost:hover {
  color: var(--brand);
  border-color: var(--brand);
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}

/* danger：纯红实心（弃用红色渐变） */
.dp-button--danger {
  background: var(--error);
  border: none;
  color: var(--on-brand);
  box-shadow: var(--shadow-sm);
}

.dp-button--danger:hover {
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}

/* text：链接式 */
.dp-button--text {
  background: transparent;
  border: none;
  color: var(--brand);
}

.dp-button--text:hover {
  color: var(--brand-2);
  text-decoration: underline;
}

/* 禁用：45% 透明去阴影 */
.dp-button.is-disabled,
.dp-button.is-disabled:hover {
  opacity: 0.45;
  box-shadow: none;
  transform: none;
}

/* 键盘焦点环 */
.dp-button:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  .dp-button:hover {
    transform: none;
  }
}
</style>
