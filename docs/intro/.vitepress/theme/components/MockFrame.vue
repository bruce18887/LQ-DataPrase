<script setup lang="ts">
defineProps<{ title: string }>()
</script>

<template>
  <div class="mock">
    <div class="mock-bar">
      <span class="dots"><i></i><i></i><i></i></span>
      <b>{{ title }}</b>
      <span class="badge">复刻 · 可操作</span>
    </div>
    <div class="mock-body"><slot /></div>
  </div>
</template>