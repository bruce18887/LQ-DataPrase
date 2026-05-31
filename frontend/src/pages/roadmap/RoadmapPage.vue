<template>
  <div class="roadmap-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <h1 class="page-title">🗺️ ATE 指标实现路线图</h1>
      <p class="page-subtitle">
        基于 ATE_量产测试关键指标.md 的功能开发计划与实现状态
      </p>
    </div>

    <!-- 统计概览 -->
    <el-row :gutter="16" style="margin-bottom: 24px">
      <el-col :xs="24" :sm="6">
        <div class="stat-card stat-completed">
          <div class="stat-icon">✅</div>
          <div class="stat-value">{{ stats.completed }}</div>
          <div class="stat-label">已完成</div>
        </div>
      </el-col>
      <el-col :xs="24" :sm="6">
        <div class="stat-card stat-partial">
          <div class="stat-icon">⚠️</div>
          <div class="stat-value">{{ stats.partial }}</div>
          <div class="stat-label">部分完成</div>
        </div>
      </el-col>
      <el-col :xs="24" :sm="6">
        <div class="stat-card stat-todo">
          <div class="stat-icon">📝</div>
          <div class="stat-value">{{ stats.todo }}</div>
          <div class="stat-label">待开发</div>
        </div>
      </el-col>
      <el-col :xs="24" :sm="6">
        <div class="stat-card stat-blocked">
          <div class="stat-icon">🚫</div>
          <div class="stat-value">{{ stats.blocked }}</div>
          <div class="stat-label">不可实现</div>
        </div>
      </el-col>
    </el-row>

    <!-- 进度条 -->
    <el-card shadow="hover" style="margin-bottom: 24px">
      <template #header>
        <span style="font-weight: bold">📊 整体完成度</span>
      </template>
      <el-progress
        :percentage="completionRate"
        :color="progressColor"
        :stroke-width="24"
        :text-inside="true"
      >
        <template #default="{ percentage }">
          <span style="font-size: 14px; font-weight: bold">{{ percentage }}%</span>
        </template>
      </el-progress>
      <div style="margin-top: 12px; color: #606266; font-size: 14px">
        已完成 {{ stats.completed }} 项，部分完成 {{ stats.partial }} 项，待开发 {{ stats.todo }} 项
      </div>
    </el-card>

    <!-- P0 优先级 -->
    <div class="section-title priority-p0">🔥 P0 - 当前轮次应完成（高优先级）</div>
    <el-card shadow="hover" style="margin-bottom: 24px">
      <el-table :data="p0Tasks" stripe :border="true">
        <el-table-column prop="id" label="编号" width="100" align="center" />
        <el-table-column prop="status" label="状态" width="80" align="center">
          <template #default="{ row }">
            <span>{{ row.status }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="task" label="任务描述" min-width="300" show-overflow-tooltip />
        <el-table-column prop="files" label="涉及文件" min-width="200" show-overflow-tooltip />
        <el-table-column prop="section" label="对应章节" width="120" align="center" />
      </el-table>
    </el-card>

    <!-- P1 优先级 -->
    <div class="section-title priority-p1">⚡ P1 - 紧接轮次完成（中优先级）</div>

    <!-- 新的交互式任务管理器 -->
    <P1TaskManager style="margin-bottom: 24px" />

    <!-- 原有的表格视图（可选保留） -->
    <el-card v-if="showLegacyTable" shadow="hover" style="margin-bottom: 24px">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="font-weight: bold;">传统表格视图</span>
          <el-button size="small" @click="showLegacyTable = false">隐藏</el-button>
        </div>
      </template>
      <el-table :data="p1Tasks" stripe :border="true">
        <el-table-column prop="id" label="编号" width="100" align="center" />
        <el-table-column prop="status" label="状态" width="80" align="center">
          <template #default="{ row }">
            <span>{{ row.status }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="task" label="任务描述" min-width="300" show-overflow-tooltip />
        <el-table-column prop="files" label="涉及文件" min-width="200" show-overflow-tooltip />
        <el-table-column prop="section" label="对应章节" width="120" align="center" />
      </el-table>
    </el-card>

    <div v-else style="text-align: center; margin-bottom: 24px;">
      <el-button size="small" @click="showLegacyTable = true">显示传统表格视图</el-button>
    </div>

    <!-- P2 优先级 -->
    <div class="section-title priority-p2">📋 P2 - 后续迭代（低优先级）</div>
    <el-card shadow="hover" style="margin-bottom: 24px">
      <el-table :data="p2Tasks" stripe :border="true">
        <el-table-column prop="id" label="编号" width="100" align="center" />
        <el-table-column prop="status" label="状态" width="80" align="center">
          <template #default="{ row }">
            <span>{{ row.status }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="task" label="任务描述" min-width="300" show-overflow-tooltip />
        <el-table-column prop="files" label="涉及文件" min-width="200" show-overflow-tooltip />
        <el-table-column prop="section" label="对应章节" width="120" align="center" />
      </el-table>
    </el-card>

    <!-- 不可实现项 -->
    <div class="section-title priority-blocked">🚫 不可实现项（超出系统边界）</div>
    <el-card shadow="hover" style="margin-bottom: 24px">
      <el-collapse accordion>
        <el-collapse-item
          v-for="item in blockedItems"
          :key="item.id"
          :title="`${item.id} - ${item.title}`"
        >
          <div class="blocked-item-content">
            <p><strong>原因：</strong>{{ item.reason }}</p>
            <p><strong>替代方案：</strong>{{ item.alternative }}</p>
          </div>
        </el-collapse-item>
      </el-collapse>
    </el-card>

    <!-- 底部说明 -->
    <el-alert
      title="说明"
      type="info"
      :closable="false"
      style="margin-top: 24px"
    >
      <template #default>
        <ul style="margin: 0; padding-left: 20px">
          <li>✅ 已完成：功能已实现并可用</li>
          <li>⚠️ 部分完成：核心功能已实现，但需要增强或扩展</li>
          <li>📝 待开发：计划中的功能，尚未实现</li>
          <li>🚫 不可实现：受限于数据源、系统边界或技术复杂度，无法在当前架构下实现</li>
        </ul>
      </template>
    </el-alert>

    <p class="footer-text">
      📅 最后更新: {{ updateTime }} | DataPhrase ATE数据分析系统
    </p>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import P1TaskManager from './components/P1TaskManager.vue'

interface Task {
  id: string
  status: string
  task: string
  files: string
  section: string
}

interface BlockedItem {
  id: string
  title: string
  reason: string
  alternative: string
}

const updateTime = ref(new Date().toLocaleString('zh-CN'))
const showLegacyTable = ref(false)

// P0 任务列表
const p0Tasks = ref<Task[]>([
  {
    id: 'TODO-01',
    status: '✅',
    task: '相关性矩阵批量 API - analysis:correlation_matrix',
    files: 'apps/analysis/views.py',
    section: '§3.2 / §7.3'
  },
  {
    id: 'TODO-02',
    status: '✅',
    task: '前端 ParetoChart.vue（柱状图 + 累积折线 + 80% 参考线）',
    files: 'frontend/src/pages/analysis/components/ParetoChart.vue',
    section: '§4.2 / §7.5'
  },
  {
    id: 'TODO-03',
    status: '✅',
    task: '前端箱线图 BoxPlotChart.vue + 后端 analysis:boxplot',
    files: 'frontend/src/components/charts/BoxPlotChart.vue, apps/analysis/views.py',
    section: '§3.2 / §7.2'
  },
  {
    id: 'TODO-04',
    status: '✅',
    task: '参数趋势图 analysis:param_trend + ParamTrendChart.vue',
    files: 'apps/analysis/views.py, services/statistics.py, frontend',
    section: '§7.1'
  },
  {
    id: 'TODO-05',
    status: '✅',
    task: 'Cpk 计算扩展：返回 Cp + Pp + Ppk',
    files: 'services/statistics.py:compute_cpk()',
    section: '§3.1'
  },
  {
    id: 'TODO-06',
    status: '✅',
    task: 'Bin 趋势 API - analysis:bin_trend',
    files: 'apps/analysis/views.py',
    section: '§7.1'
  }
])

// P1 任务列表
const p1Tasks = ref<Task[]>([
  {
    id: 'TODO-07',
    status: '📝',
    task: 'Yield Trend 良率趋势 analysis:yield_trend + SPC 控制限',
    files: 'apps/analysis/views.py, services/statistics.py',
    section: '§2.1 / §2.2'
  },
  {
    id: 'TODO-08',
    status: '📝',
    task: '前端 YieldTrendChart.vue（折线图 + UCL/LCL 控制线）',
    files: 'frontend/src/pages/dashboard/',
    section: '§2.2'
  },
  {
    id: 'TODO-09',
    status: '📝',
    task: 'Yield By Zone 分区良率 compute_zonal_yield()',
    files: 'services/statistics.py',
    section: '§2.3'
  },
  {
    id: 'TODO-10',
    status: '📝',
    task: '前端 Wafer Map 分区高亮/分区统计',
    files: 'WaferMapPanel.vue',
    section: '§2.3'
  },
  {
    id: 'TODO-11',
    status: '📝',
    task: '前端 QQ Plot 组件 QQPlotChart.vue + 后端 analysis:qqplot',
    files: 'frontend + apps/analysis/views.py',
    section: '§3.2 / §7.2'
  },
  {
    id: 'TODO-12',
    status: '📝',
    task: '多 Lot 良率对比（扩展 multi_lot）',
    files: 'apps/analysis/views.py',
    section: '§1.2'
  },
  {
    id: 'TODO-13',
    status: '📝',
    task: 'UPH 计算 services/efficiency.py:compute_uph()',
    files: 'apps/analysis/services/efficiency.py',
    section: '§5.2'
  }
])

// P2 任务列表
const p2Tasks = ref<Task[]>([
  {
    id: 'TODO-14',
    status: '📝',
    task: 'GR&R 分析模块 services/grr.py',
    files: 'apps/analysis/services/grr.py',
    section: '§6.1'
  },
  {
    id: 'TODO-15',
    status: '📝',
    task: 'Golden Sample 管理 - 模型 + 基准值 + 漂移记录',
    files: 'apps/golden_sample/',
    section: '§6.2 / 陷阱'
  },
  {
    id: 'TODO-16',
    status: '📝',
    task: '裕量分析报告 services/guardband.py',
    files: 'apps/analysis/services/guardband.py',
    section: '§3.3'
  },
  {
    id: 'TODO-17',
    status: '📝',
    task: 'RTY 累积良率 - 多站流程模型 + 计算',
    files: 'apps/analysis/services/flow_yield.py',
    section: '§1.4'
  },
  {
    id: 'TODO-18',
    status: '📝',
    task: 'Box-Cox 正态性变换 - 扩展 compute_range_statistics',
    files: 'services/statistics.py',
    section: '§3.2'
  },
  {
    id: 'TODO-19',
    status: '📝',
    task: 'Multi-site 效率指数 services/efficiency.py',
    files: 'apps/analysis/services/efficiency.py',
    section: '§5.3'
  },
  {
    id: 'TODO-20',
    status: '📝',
    task: 'Cpk 数据截断/边界堆积检测',
    files: 'services/statistics.py',
    section: '§3.1 / 陷阱'
  },
  {
    id: 'TODO-21',
    status: '📝',
    task: '机台间相关性/偏差分析 - 跨文件 cross_tester action',
    files: 'apps/analysis/views.py',
    section: '§6.2 / §6.3'
  },
  {
    id: 'TODO-22',
    status: '📝',
    task: '样本量不足提醒 - 所有统计接口 < 30 条标记 confidence: low',
    files: 'apps/analysis/views.py 多个',
    section: '陷阱'
  },
  {
    id: 'TODO-23',
    status: '📝',
    task: 'Bin Trend 趋势 + 总良率 vs Bin 占比变化对比',
    files: 'apps/analysis/views.py',
    section: '§4.2 / 陷阱'
  },
  {
    id: 'TODO-24',
    status: '📝',
    task: 'Retest 列识别 - 解析器增强',
    files: 'apps/datafiles/parsers/',
    section: '陷阱'
  },
  {
    id: 'TODO-25',
    status: '📝',
    task: '边缘集中失效检测 detect_edge_concentration()',
    files: 'services/statistics.py',
    section: '§4.3'
  },
  {
    id: 'TODO-26',
    status: '📝',
    task: '目标线/Target Line 配置 - 前端 ChartConfigPanel 增加可配置阈值',
    files: 'ChartConfigPanel.vue',
    section: '§1 多处'
  }
])

// 不可实现项
const blockedItems = ref<BlockedItem[]>([
  {
    id: '🚫-1',
    title: '鱼骨图（Ishikawa Diagram）自动生成',
    reason: '鱼骨图是人工团队讨论和领域经验驱动的分析工具。自动生成需要理解生产上下文和具备半导体失效机理因果推理能力（LLM 级别的领域 AI）',
    alternative: '系统输出 Pareto 分析 + 各维度统计对比（按 Site/按 Batch/按时间/按参数），为工程师的人工鱼骨图分析提供数据输入'
  },
  {
    id: '🚫-2',
    title: 'Why-Why 分析自动生成',
    reason: 'Why-Why 是对话式的追问过程，每个"为什么"的答案都需要工艺知识和现场排查，系统没有这些信息源',
    alternative: '远期 P3+ 可考虑接入 LLM 模块（如 OpenAI API + RAG 半导体知识库），提供"Why-Why 辅助建议"'
  },
  {
    id: '🚫-3',
    title: '环境因素（温/湿度）关联分析',
    reason: '温度、湿度传感器数据完全不在 ATE 测试数据文件中。温度环境数据来自 Fab/车间 IoT 系统或 SCADA 系统，属于不同数据源',
    alternative: '如果未来接入车间 IoT 系统（如 MES/SCADA），可将温湿度数据作为独立维度导入，与测试数据进行时间戳对齐 Join'
  },
  {
    id: '🚫-4',
    title: '设备利用率（Availability / OEE / MTTR / SMED）',
    reason: '这些指标要求的数据源是设备运行/停机/维护日志（需要 MES 或 CIM 系统）、生产节拍和计划（需要 ERP/APS 系统）、维修工单和维修时间（需要 EAM/CMMS 系统）',
    alternative: '系统可以在有了 Multi-site Efficiency 和 Test Time 数据后，输出"测试站利用率估算"（Test Time 占比）'
  },
  {
    id: '🚫-5',
    title: 'ATE 机时费率与成本分析',
    reason: 'ATE 机时费率是商业/采购/运营数据（每小时几百到上千美元不等），不属于 ATE 测试数据文件',
    alternative: '系统可以计算并展示 Test Time，并提供"成本估算器"让用户手动输入机时费率'
  },
  {
    id: '🚫-6',
    title: '测试项裁剪决策（基于 CPK 自动去冗余测试项）',
    reason: '测试程序的修改是 ATE 测试工程师的编程工作，涉及测试向量的增删和控制流程变更。"冗余测试项"的判定不是纯统计问题',
    alternative: '系统输出"长期 CPK 稳定项报告"（CPK > 2.0 且连续 30+ Lot 无超限的参数列表），作为测试工程师的辅助决策参考'
  },
  {
    id: '🚫-7',
    title: '测试向量压缩优化',
    reason: '向量压缩是 DFT（可测性设计）+ ATE 测试编程的专业工程领域，涉及 ATPG 工具（如 TetraMAX）、扫描链重组、压缩比选择等',
    alternative: '无。此项应标记为"超出系统边界"'
  },
  {
    id: '🚫-8',
    title: 'Golden Sample（金样）物理管理',
    reason: 'Golden Sample 是物理芯片，系统无法知道物理金样是否被调换或损坏、存储环境是否合规、是否被正确使用',
    alternative: '系统可以建立 GoldenSample 数据模型，记录该金样的基准参数值、最近校验日期、和最近若干次的测试数据'
  },
  {
    id: '🚫-9',
    title: '团簇缺陷自动识别（空间聚类算法）',
    reason: '自动空间聚类（如 DBSCAN）需要合理设定参数，而这些参数高度依赖具体产品和工艺。不同产品的 Wafer 布局差异很大，通用聚类效果不可靠',
    alternative: '保持当前可视化方式（工程师肉眼观察）；实现边缘集中失效检测（边缘 vs 中心的简单统计）；未来如果数据量足够大且有标注数据，可引入轻量空间统计'
  },
  {
    id: '🚫-10',
    title: '系统性重复失效模式自动检测',
    reason: '需要检测 Wafer 上以光罩（Reticle）为周期的重复失效模式。这要求知道该产品的 Reticle 尺寸（Field Size）并实现周期性模式检测算法（如 FFT/自相关分析）',
    alternative: '保持当前 Bin Map 可视化方式。工程师可以通过肉眼观察重复性模式'
  }
])

// 统计数据
const stats = computed(() => {
  const allTasks = [...p0Tasks.value, ...p1Tasks.value, ...p2Tasks.value]
  return {
    completed: allTasks.filter(t => t.status === '✅').length,
    partial: allTasks.filter(t => t.status === '⚠️').length,
    todo: allTasks.filter(t => t.status === '📝').length,
    blocked: blockedItems.value.length
  }
})

// 完成率
const completionRate = computed(() => {
  const total = stats.value.completed + stats.value.partial + stats.value.todo
  if (total === 0) return 0
  return Math.round(((stats.value.completed + stats.value.partial * 0.5) / total) * 100)
})

// 进度条颜色
const progressColor = computed(() => {
  const rate = completionRate.value
  if (rate >= 80) return '#67C23A'
  if (rate >= 50) return '#E6A23C'
  return '#F56C6C'
})
</script>

<style scoped>
.roadmap-page {
  padding-bottom: 30px;
}

.page-header {
  text-align: center;
  margin-bottom: 30px;
}

.page-title {
  color: #2c3e50;
  margin-bottom: 8px;
  font-size: 28px;
  font-weight: bold;
}

.page-subtitle {
  color: #7f8c8d;
  font-size: 14px;
}

.stat-card {
  padding: 24px;
  border-radius: 12px;
  text-align: center;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
  margin-bottom: 16px;
  transition: transform 0.3s;
}

.stat-card:hover {
  transform: translateY(-4px);
}

.stat-icon {
  font-size: 36px;
  margin-bottom: 8px;
}

.stat-value {
  font-size: 32px;
  font-weight: bold;
  margin-bottom: 4px;
}

.stat-label {
  font-size: 14px;
  opacity: 0.9;
}

.stat-completed {
  background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
  color: white;
}

.stat-partial {
  background: linear-gradient(135deg, #f9a825 0%, #ffd54f 100%);
  color: #5d4037;
}

.stat-todo {
  background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
  color: white;
}

.stat-blocked {
  background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
  color: white;
}

.section-title {
  font-size: 20px;
  font-weight: bold;
  color: #2c3e50;
  margin: 30px 0 16px 0;
  padding-left: 12px;
  border-left: 4px solid #667eea;
}

.priority-p0 {
  border-left-color: #f5576c;
  color: #f5576c;
}

.priority-p1 {
  border-left-color: #f9a825;
  color: #f9a825;
}

.priority-p2 {
  border-left-color: #4facfe;
  color: #4facfe;
}

.priority-blocked {
  border-left-color: #95a5a6;
  color: #95a5a6;
}

.blocked-item-content {
  padding: 12px;
  background: #f8f9fa;
  border-radius: 8px;
}

.blocked-item-content p {
  margin: 8px 0;
  line-height: 1.6;
}

.footer-text {
  text-align: center;
  color: #bdc3c7;
  font-size: 12px;
  margin-top: 30px;
  padding-bottom: 10px;
}

:deep(.el-table) {
  font-size: 13px;
}

:deep(.el-table th) {
  background-color: #f5f7fa;
  font-weight: 600;
}

:deep(.el-collapse-item__header) {
  font-weight: 500;
  padding-left: 12px;
}
</style>
