<script setup lang="ts">
import { useZoom } from './composables/useZoom'
import ZoomIndicator from './components/common/ZoomIndicator.vue'
import AppAboutDialog from './components/common/AppAboutDialog.vue'

useZoom()
</script>

<template>
  <router-view />
  <ZoomIndicator />
  <AppAboutDialog />
</template>
