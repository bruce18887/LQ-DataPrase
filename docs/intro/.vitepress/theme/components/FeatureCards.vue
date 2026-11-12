<script setup lang="ts">
import { computed } from 'vue'
import { FEATURES } from '../data'
const props = defineProps<{ k: string; accent?: string }>()
const items = computed(() => FEATURES[props.k] || [])
</script>

<template>
  <div class="feat" :style="{ '--fc-accent': accent || 'var(--vp-c-brand-1)' }">
    <div v-for="(f, i) in items" :key="i" class="fc">
      <b><span class="fi">{{ i + 1 }}</span>{{ f.t }}</b>
      <p>{{ f.d }}</p>
      <div class="how"><em>怎么用：</em>{{ f.how }}</div>
    </div>
  </div>
</template>