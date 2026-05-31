<template>
  <div class="p1-task-manager">
    <!-- 标题区域 -->
    <div class="manager-header">
      <h2 class="manager-title">
        <span class="title-icon">⚡</span>
        <span class="title-text">P1 紧接轮次任务</span>
        <span class="title-badge">{{ completedCount }}/{{ tasks.length }}</span>
      </h2>
      <p class="manager-subtitle">中优先级 · 下一轮次开发计划</p>
    </div>

    <!-- 任务网格 -->
    <div class="tasks-grid">
      <div
        v-for="task in tasks"
        :key="task.id"
        class="task-card"
        :class="{ 'task-completed': task.status === '✅', 'task-selected': selectedTask?.id === task.id }"
        @click="selectTask(task)"
      >
        <!-- 任务头部 -->
        <div class="task-header">
          <span class="task-id">{{ task.id }}</span>
          <span class="task-status" :class="`status-${task.status}`">{{ task.status }}</span>
        </div>

        <!-- 任务标题 -->
        <h3 class="task-title">{{ task.title }}</h3>

        <!-- 任务标签 -->
        <div class="task-tags">
          <span v-for="tag in task.tags" :key="tag" class="task-tag">{{ tag }}</span>
        </div>

        <!-- 任务进度指示器 -->
        <div class="task-progress">
          <div class="progress-bar" :style="{ width: task.progress + '%' }"></div>
        </div>

        <!-- 任务元数据 -->
        <div class="task-meta">
          <span class="meta-item">
            <span class="meta-icon">📁</span>
            {{ task.fileCount }} 文件
          </span>
          <span class="meta-item">
            <span class="meta-icon">⏱️</span>
            {{ task.estimatedDays }}天
          </span>
        </div>
      </div>
    </div>

    <!-- 任务详情面板 -->
    <transition name="slide-up">
      <div v-if="selectedTask" class="task-detail-panel">
        <div class="detail-header">
          <h3 class="detail-title">{{ selectedTask.title }}</h3>
          <button class="close-btn" @click="selectedTask = null">✕</button>
        </div>

        <div class="detail-content">
          <!-- 描述 -->
          <div class="detail-section">
            <h4 class="section-title">📋 任务描述</h4>
            <p class="section-text">{{ selectedTask.description }}</p>
          </div>

          <!-- 技术栈 -->
          <div class="detail-section">
            <h4 class="section-title">🔧 技术栈</h4>
            <div class="tech-stack">
              <span v-for="tech in selectedTask.techStack" :key="tech" class="tech-badge">{{ tech }}</span>
            </div>
          </div>

          <!-- 涉及文件 -->
          <div class="detail-section">
            <h4 class="section-title">📂 涉及文件</h4>
            <ul class="file-list">
              <li v-for="file in selectedTask.files" :key="file" class="file-item">
                <span class="file-icon">📄</span>
                <code class="file-path">{{ file }}</code>
              </li>
            </ul>
          </div>

          <!-- 实现步骤 -->
          <div class="detail-section">
            <h4 class="section-title">📝 实现步骤</h4>
            <ol class="steps-list">
              <li v-for="(step, index) in selectedTask.steps" :key="index" class="step-item">
                {{ step }}
              </li>
            </ol>
          </div>

          <!-- 依赖关系 -->
          <div v-if="selectedTask.dependencies.length > 0" class="detail-section">
            <h4 class="section-title">🔗 依赖任务</h4>
            <div class="dependencies">
              <span v-for="dep in selectedTask.dependencies" :key="dep" class="dependency-badge">
                {{ dep }}
              </span>
            </div>
          </div>

          <!-- 操作按钮 -->
          <div class="detail-actions">
            <button class="action-btn primary" @click="startImplementation(selectedTask)">
              <span class="btn-icon">🚀</span>
              开始实现
            </button>
            <button class="action-btn secondary" @click="viewDocumentation(selectedTask)">
              <span class="btn-icon">📖</span>
              查看文档
            </button>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

interface Task {
  id: string
  status: string
  title: string
  description: string
  tags: string[]
  progress: number
  fileCount: number
  estimatedDays: number
  techStack: string[]
  files: string[]
  steps: string[]
  dependencies: string[]
  section: string
}

const selectedTask = ref<Task | null>(null)

const tasks = ref<Task[]>([
  {
    id: 'TODO-07',
    status: '📝',
    title: 'Yield Trend 良率趋势分析',
    description: '实现良率趋势分析功能，包括时间序列分析、SPC 控制限计算（UCL/LCL）、趋势预测和异常检测。支持多批次对比和控制图展示。',
    tags: ['后端', 'SPC', '统计分析'],
    progress: 0,
    fileCount: 2,
    estimatedDays: 3,
    techStack: ['Python', 'Pandas', 'NumPy', 'SciPy'],
    files: [
      'apps/analysis/views.py',
      'apps/analysis/services/statistics.py'
    ],
    steps: [
      '在 statistics.py 中实现 compute_yield_trend() 函数',
      '计算移动平均、标准差和控制限（UCL/LCL）',
      '实现异常点检测逻辑（超出控制限的点）',
      '在 views.py 中创建 yield_trend API 端点',
      '返回时间序列数据、控制限和异常点标记'
    ],
    dependencies: [],
    section: '§2.1 / §2.2'
  },
  {
    id: 'TODO-08',
    status: '📝',
    title: 'YieldTrendChart 前端组件',
    description: '创建良率趋势图表组件，使用 ECharts 实现折线图展示，包含 UCL/LCL 控制线、异常点高亮、趋势线和交互式缩放功能。',
    tags: ['前端', 'Vue', 'ECharts'],
    progress: 0,
    fileCount: 1,
    estimatedDays: 2,
    techStack: ['Vue 3', 'TypeScript', 'ECharts', 'Element Plus'],
    files: [
      'frontend/src/pages/dashboard/components/YieldTrendChart.vue'
    ],
    steps: [
      '创建 YieldTrendChart.vue 组件',
      '配置 ECharts 折线图，添加数据系列',
      '添加 UCL/LCL 控制线（markLine）',
      '实现异常点高亮（markPoint）',
      '添加 dataZoom 组件支持时间范围选择',
      '集成到仪表板页面'
    ],
    dependencies: ['TODO-07'],
    section: '§2.2'
  },
  {
    id: 'TODO-09',
    status: '📝',
    title: 'Yield By Zone 分区良率',
    description: '实现晶圆分区良率计算，将晶圆划分为中心区、中间区、边缘区，分别统计各区域的良率，用于识别工艺问题的空间分布特征。',
    tags: ['后端', '空间分析', '统计'],
    progress: 0,
    fileCount: 1,
    estimatedDays: 2,
    techStack: ['Python', 'Pandas', 'NumPy'],
    files: [
      'apps/analysis/services/statistics.py'
    ],
    steps: [
      '实现 compute_zonal_yield() 函数',
      '根据坐标计算每个 die 到晶圆中心的距离',
      '定义区域划分规则（中心/中间/边缘）',
      '统计各区域的 Pass/Fail 数量和良率',
      '返回分区统计数据和可视化配置'
    ],
    dependencies: [],
    section: '§2.3'
  },
  {
    id: 'TODO-10',
    status: '📝',
    title: 'Wafer Map 分区高亮',
    description: '增强晶圆图组件，添加分区高亮功能，支持按区域着色、分区统计显示和交互式区域选择。',
    tags: ['前端', 'Vue', '可视化'],
    progress: 0,
    fileCount: 1,
    estimatedDays: 2,
    techStack: ['Vue 3', 'TypeScript', 'ECharts', 'Canvas'],
    files: [
      'frontend/src/pages/analysis/components/WaferMapPanel.vue'
    ],
    steps: [
      '在 WaferMapPanel.vue 中添加分区模式切换',
      '实现分区边界绘制逻辑',
      '添加分区统计信息面板',
      '实现区域点击交互和高亮效果',
      '集成 TODO-09 的后端 API'
    ],
    dependencies: ['TODO-09'],
    section: '§2.3'
  },
  {
    id: 'TODO-11',
    status: '📝',
    title: 'QQ Plot 正态性检验',
    description: '实现 QQ 图（Quantile-Quantile Plot）用于检验数据的正态性分布，帮助工程师判断参数分布是否符合正态假设。',
    tags: ['后端', '前端', '统计分析'],
    progress: 0,
    fileCount: 3,
    estimatedDays: 3,
    techStack: ['Python', 'SciPy', 'Vue 3', 'ECharts'],
    files: [
      'apps/analysis/views.py',
      'apps/analysis/services/statistics.py',
      'frontend/src/pages/analysis/components/QQPlotChart.vue'
    ],
    steps: [
      '在 statistics.py 中实现 compute_qqplot() 函数',
      '使用 scipy.stats.probplot 计算理论分位数',
      '在 views.py 中创建 qqplot API 端点',
      '创建 QQPlotChart.vue 前端组件',
      '使用 ECharts 散点图展示 QQ 图',
      '添加参考线和 R² 拟合度指标'
    ],
    dependencies: [],
    section: '§3.2 / §7.2'
  },
  {
    id: 'TODO-12',
    status: '📝',
    title: '多 Lot 良率对比增强',
    description: '扩展现有的 multi_lot 功能，添加良率对比分析，支持多个批次的良率趋势对比、统计显著性检验和异常批次识别。',
    tags: ['后端', '对比分析'],
    progress: 0,
    fileCount: 1,
    estimatedDays: 2,
    techStack: ['Python', 'Pandas', 'SciPy'],
    files: [
      'apps/analysis/views.py'
    ],
    steps: [
      '扩展 multi_lot API，添加 yield_comparison 模式',
      '计算各批次的良率和置信区间',
      '实现批次间显著性检验（卡方检验）',
      '识别异常批次（偏离均值 2σ 以上）',
      '返回对比数据和统计检验结果'
    ],
    dependencies: [],
    section: '§1.2'
  },
  {
    id: 'TODO-13',
    status: '📝',
    title: 'UPH 单位小时产量计算',
    description: '实现 UPH（Units Per Hour）计算模块，基于测试时间数据计算单位小时产量，用于评估测试效率和产能规划。',
    tags: ['后端', '效率分析'],
    progress: 0,
    fileCount: 1,
    estimatedDays: 2,
    techStack: ['Python', 'Pandas'],
    files: [
      'apps/analysis/services/efficiency.py'
    ],
    steps: [
      '创建 efficiency.py 模块',
      '实现 compute_uph() 函数',
      '从测试数据中提取 Test Time 字段',
      '计算平均测试时间和 UPH',
      '支持按 Site 分组统计',
      '返回 UPH 指标和效率分析数据'
    ],
    dependencies: [],
    section: '§5.2'
  }
])

const completedCount = computed(() => {
  return tasks.value.filter(t => t.status === '✅').length
})

const selectTask = (task: Task) => {
  selectedTask.value = task
}

const startImplementation = (task: Task) => {
  console.log('开始实现任务:', task.id)
  // TODO: 实现任务开始逻辑
}

const viewDocumentation = (task: Task) => {
  console.log('查看文档:', task.id)
  // TODO: 打开相关文档
}
</script>

<style scoped>
.p1-task-manager {
  padding: 24px;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
  border-radius: 16px;
  min-height: 600px;
}

/* 标题区域 */
.manager-header {
  text-align: center;
  margin-bottom: 32px;
  padding-bottom: 24px;
  border-bottom: 2px solid rgba(255, 255, 255, 0.1);
}

.manager-title {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  margin: 0 0 8px 0;
  font-size: 28px;
  font-weight: 700;
  color: #fff;
  font-family: 'SF Pro Display', -apple-system, BlinkMacSystemFont, sans-serif;
}

.title-icon {
  font-size: 32px;
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.1); }
}

.title-text {
  background: linear-gradient(135deg, #f9a825 0%, #ffd54f 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.title-badge {
  display: inline-block;
  padding: 4px 12px;
  background: rgba(249, 168, 37, 0.2);
  border: 1px solid #f9a825;
  border-radius: 20px;
  font-size: 14px;
  color: #ffd54f;
  font-weight: 600;
}

.manager-subtitle {
  margin: 0;
  font-size: 14px;
  color: rgba(255, 255, 255, 0.6);
  font-weight: 400;
}

/* 任务网格 */
.tasks-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 20px;
  margin-bottom: 32px;
}

.task-card {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  padding: 20px;
  cursor: pointer;
  transition: background-color 0.3s cubic-bezier(0.4, 0, 0.2, 1), border-color 0.3s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.task-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, #f9a825 0%, #ffd54f 100%);
  transform: scaleX(0);
  transform-origin: left;
  transition: transform 0.3s ease;
}

.task-card:hover {
  transform: translateY(-4px);
  background: rgba(255, 255, 255, 0.08);
  border-color: #f9a825;
  box-shadow: 0 8px 24px rgba(249, 168, 37, 0.2);
}

.task-card:hover::before {
  transform: scaleX(1);
}

.task-card.task-selected {
  border-color: #f9a825;
  background: rgba(249, 168, 37, 0.1);
}

.task-card.task-completed {
  opacity: 0.6;
  border-color: #11998e;
}

.task-card.task-completed::before {
  background: linear-gradient(90deg, #11998e 0%, #38ef7d 100%);
}

/* 任务头部 */
.task-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.task-id {
  font-size: 12px;
  font-weight: 600;
  color: #f9a825;
  font-family: 'Monaco', 'Courier New', monospace;
  letter-spacing: 0.5px;
}

.task-status {
  font-size: 18px;
}

/* 任务标题 */
.task-title {
  margin: 0 0 12px 0;
  font-size: 16px;
  font-weight: 600;
  color: #fff;
  line-height: 1.4;
  min-height: 44px;
}

/* 任务标签 */
.task-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 12px;
}

.task-tag {
  display: inline-block;
  padding: 3px 8px;
  background: rgba(79, 172, 254, 0.2);
  border: 1px solid rgba(79, 172, 254, 0.4);
  border-radius: 4px;
  font-size: 11px;
  color: #4facfe;
  font-weight: 500;
}

/* 任务进度 */
.task-progress {
  height: 4px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 2px;
  margin-bottom: 12px;
  overflow: hidden;
}

.progress-bar {
  height: 100%;
  background: linear-gradient(90deg, #f9a825 0%, #ffd54f 100%);
  border-radius: 2px;
  transition: width 0.3s ease;
}

/* 任务元数据 */
.task-meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.6);
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.meta-icon {
  font-size: 14px;
}

/* 任务详情面板 */
.task-detail-panel {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 12px;
  padding: 24px;
  backdrop-filter: blur(10px);
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.detail-title {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: #fff;
}

.close-btn {
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 6px;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: #fff;
  font-size: 18px;
  transition: color 0.2s, background-color 0.2s;
}

.close-btn:hover {
  background: rgba(255, 255, 255, 0.2);
  transform: rotate(90deg);
}

/* 详情内容 */
.detail-content {
  display: grid;
  gap: 20px;
}

.detail-section {
  padding: 16px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 8px;
  border-left: 3px solid #f9a825;
}

.section-title {
  margin: 0 0 12px 0;
  font-size: 14px;
  font-weight: 600;
  color: #ffd54f;
}

.section-text {
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.8);
}

/* 技术栈 */
.tech-stack {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tech-badge {
  padding: 6px 12px;
  background: rgba(17, 153, 142, 0.2);
  border: 1px solid rgba(17, 153, 142, 0.4);
  border-radius: 6px;
  font-size: 12px;
  color: #38ef7d;
  font-weight: 500;
}

/* 文件列表 */
.file-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  margin-bottom: 6px;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 6px;
  font-size: 13px;
}

.file-icon {
  font-size: 16px;
}

.file-path {
  font-family: 'Monaco', 'Courier New', monospace;
  color: #4facfe;
  font-size: 12px;
}

/* 步骤列表 */
.steps-list {
  margin: 0;
  padding-left: 20px;
  color: rgba(255, 255, 255, 0.8);
}

.step-item {
  margin-bottom: 8px;
  font-size: 13px;
  line-height: 1.6;
}

/* 依赖关系 */
.dependencies {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.dependency-badge {
  padding: 6px 12px;
  background: rgba(245, 87, 108, 0.2);
  border: 1px solid rgba(245, 87, 108, 0.4);
  border-radius: 6px;
  font-size: 12px;
  color: #f5576c;
  font-weight: 500;
  font-family: 'Monaco', 'Courier New', monospace;
}

/* 操作按钮 */
.detail-actions {
  display: flex;
  gap: 12px;
  margin-top: 8px;
}

.action-btn {
  flex: 1;
  padding: 12px 24px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.3s, color 0.3s;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: none;
}

.action-btn.primary {
  background: linear-gradient(135deg, #f9a825 0%, #ffd54f 100%);
  color: #1a1a2e;
}

.action-btn.primary:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(249, 168, 37, 0.4);
}

.action-btn.secondary {
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #fff;
}

.action-btn.secondary:hover {
  background: rgba(255, 255, 255, 0.15);
}

.btn-icon {
  font-size: 16px;
}

/* 动画 */
.slide-up-enter-active,
.slide-up-leave-active {
  transition: opacity 0.3s cubic-bezier(0.4, 0, 0.2, 1), transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.slide-up-enter-from {
  opacity: 0;
  transform: translateY(20px);
}

.slide-up-leave-to {
  opacity: 0;
  transform: translateY(-20px);
}
</style>
