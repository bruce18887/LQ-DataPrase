<template>
  <div class="main-layout">
    <a href="#main-content" class="skip-link">跳转到主内容</a>
    <Sidebar />
    <div class="main-content">
      <Topbar />
      <!-- App 级常驻搜索条（计划 Task 17 Step 4）：挂在这一层而不是 SftpBrowser 内部，
           切到任何页面都还在 —— 这是「搜索运行状态跨页面驻留」唯一的可见落点。 -->
      <ActiveSearchChip />
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
import ActiveSearchChip from '../components/common/ActiveSearchChip.vue'
</script>

<style scoped>
.main-layout {
  display: flex;
  height: 100vh;
  height: 100dvh;
  background-color: var(--bg);
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
  background-color: var(--bg);
  /* 上 16 / 其余 24：指南 §5 只约束「页面左右 24–28」，上边距无规定。
     内容区首块此前被 24 留白 + 40 tab 条 + 15 pane 内边距推到 y≈79 才起，
     分析页的 sticky 工具栏每多 1px 就同时从首屏和滚动后各扣一次。 */
  padding: 16px 24px 24px;
  scrollbar-width: thin;
  scrollbar-color: var(--border-2) var(--bg);
}

.content-area::-webkit-scrollbar {
  width: 8px;
}

.content-area::-webkit-scrollbar-track {
  background: var(--bg);
}

.content-area::-webkit-scrollbar-thumb {
  background: var(--border-2);
  border-radius: 4px;
}

.content-area::-webkit-scrollbar-thumb:hover {
  background: var(--text-3);
}
</style>
