<template>
  <div class="main-layout">
    <a href="#main-content" class="skip-link">跳转到主内容</a>
    <Sidebar />
    <div class="main-content">
      <Topbar />
      <main id="main-content" class="content-area" tabindex="-1">
        <router-view v-slot="{ Component }">
          <keep-alive :max="10">
            <component :is="Component" />
          </keep-alive>
        </router-view>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import Sidebar from '../components/layout/Sidebar.vue'
import Topbar from '../components/layout/Topbar.vue'
</script>

<style scoped>
.main-layout {
  display: flex;
  height: 100vh;
  height: 100dvh;
  background-color: var(--bg-primary);
  overflow: hidden;
}

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}

.content-area {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  background-color: var(--bg-primary);
  padding: 24px;
  scrollbar-width: thin;
  scrollbar-color: var(--border-default) var(--bg-primary);
}

.content-area::-webkit-scrollbar {
  width: 8px;
}

.content-area::-webkit-scrollbar-track {
  background: var(--bg-primary);
}

.content-area::-webkit-scrollbar-thumb {
  background: var(--border-default);
  border-radius: 4px;
}

.content-area::-webkit-scrollbar-thumb:hover {
  background: var(--border-emphasis);
}
</style>
