<script setup lang="ts">
/**
 * 品牌符号。形状的唯一界面出口 —— 位图家族用 frontend/public/favicon.svg，
 * 两者的 d 必须一致，由 test/unit/brandMark.spec.ts 钉住。
 *
 * 刻意不做描边版：这枚标志的识别度全在实心剪影（spec §2.2）。
 */
import { computed } from 'vue'

const props = withDefaults(defineProps<{ size?: number }>(), { size: 28 })

// 48×46 非正方：按宽定高，避免被拉扁；computed 保证动态 :size 时宽高同步跟随
const height = computed(() => Math.round((props.size * 46) / 48))

const d = 'M25.946 44.938c-.664.845-2.021.375-2.021-.698L19.4 33.937a2.26 2.26 0 0 0-2.262-2.262H10.287c-.92 0-1.456-1.04-.92-1.788l7.48-10.471c1.07-1.497 0-3.578-1.842-3.578H1.237c-.92 0-1.456-1.04-.92-1.788L10.013.474c.214-.297.556-.474.92-.474h28.894c.92 0 1.456 1.04.92 1.788l-7.48 10.471c-1.07 1.498 0 3.579 1.842 3.579h11.377c.943 0 1.473 1.088.89 1.83L25.946 44.94z'
</script>

<template>
  <svg
    class="app-logo"
    :width="size"
    :height="height"
    viewBox="0 0 48 46"
    aria-hidden="true"
    focusable="false"
  >
    <path class="app-logo__mark" :d="d" />
  </svg>
</template>

<style scoped>
.app-logo {
  display: block;
  flex: 0 0 auto;
}

.app-logo__mark {
  fill: currentColor;
}
</style>
