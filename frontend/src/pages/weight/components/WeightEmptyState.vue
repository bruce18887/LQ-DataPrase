<script setup lang="ts">
import WeightActionButton from './WeightActionButton.vue'

const emit = defineEmits<{ (e: 'pick'): void }>()
</script>

<template>
  <div class="weight-empty-wrap">
    <section class="weight-empty-card" data-testid="weight-empty-hint">
      <div class="weight-empty-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 3v18h18" />
          <path d="m7 15 4-5 3 3 5-7" />
          <circle cx="7" cy="15" r="1.4" />
          <circle cx="11" cy="10" r="1.4" />
          <circle cx="14" cy="13" r="1.4" />
          <circle cx="19" cy="6" r="1.4" />
        </svg>
      </div>

      <h2>载入权重文件开始画图</h2>
      <p>选择本地 C 风格权重声明文件，每个测试项会生成一张独立缩放的曲线图；同名多次声明自动编号，并给出逐点均值。</p>

      <div class="weight-empty-snippet">
        double&nbsp;&nbsp;WT0001[16] = {-0.00002, -0.00428, -0.00784, …};
      </div>

      <WeightActionButton variant="primary" @click="emit('pick')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 7h6l2 2h10v10H3z" />
        </svg>
        选择权重文件
      </WeightActionButton>

      <div class="weight-empty-foot">
        支持 .csv / .txt / .h / .c · 单文件 ≤ 2,000,000 字符 · 数据只在本页使用，刷新即丢
      </div>
    </section>
  </div>
</template>

<style scoped>
.weight-empty-wrap {
  display: flex;
  justify-content: center;
  padding: 44px 0 64px;
}

.weight-empty-card {
  width: min(720px, 100%);
  padding: 40px 40px 34px;
  border: 1px solid var(--border);
  border-radius: var(--p-radius-lg);
  background: var(--card);
  box-shadow: var(--shadow-sm);
  text-align: center;
}

.weight-empty-icon {
  display: grid;
  place-items: center;
  width: 58px;
  height: 58px;
  margin: 0 auto 16px;
  border: 1px solid color-mix(in srgb, var(--brand) 24%, transparent);
  border-radius: var(--p-radius-xl);
  background: color-mix(in srgb, var(--brand) 11%, transparent);
  color: var(--brand);
}

.weight-empty-icon svg {
  width: 28px;
  height: 28px;
}

.weight-empty-card h2 {
  margin-bottom: 8px;
  font-size: var(--p-fs-title);
  font-weight: 800;
  color: var(--text);
}

.weight-empty-card p {
  max-width: 50ch;
  margin: 0 auto 18px;
  font-size: var(--p-fs-small);
  line-height: 1.7;
  color: var(--text-2);
}

.weight-empty-snippet {
  margin-bottom: 20px;
  padding: 10px 12px;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--p-radius-md);
  background: var(--bg-2);
  color: var(--text-2);
  font-family: var(--font-mono);
  font-size: var(--p-fs-micro);
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.weight-empty-foot {
  margin-top: 12px;
  font-size: var(--p-fs-micro);
  color: var(--text-2);
}

@media (max-width: 760px) {
  .weight-empty-card {
    padding: 28px 22px;
  }
}
</style>
