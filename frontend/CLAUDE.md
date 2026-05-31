# DataPhrase 前端架构文档

## 技术栈

- **框架**: Vue 3.5.34 (Composition API)
- **语言**: TypeScript 6.0.2
- **构建工具**: Vite 8.0.12
- **UI 框架**: Element Plus 2.14.0
- **表格组件**: ag-grid-vue3 35.3.0
- **图表库**: ECharts 6.1.0, vue-echarts 8.0.1
- **状态管理**: Pinia 3.0.4
- **路由**: Vue Router 4.6.4
- **HTTP 客户端**: Axios 1.16.1
- **工具库**: lodash-es 4.17.21, dayjs 1.11.13

## 项目结构

```
frontend/
├── src/
│   ├── api/                    # API 调用层
│   │   ├── index.ts           # Axios 实例配置（JWT 拦截器）
│   │   ├── auth.ts            # 认证 API
│   │   ├── datafiles.ts       # 数据文件 API
│   │   ├── analysis.ts        # 分析 API
│   │   ├── batch.ts           # 批次报表 API
│   │   ├── buyoff.ts          # 买断 API
│   │   ├── gage.ts            # 量具 API
│   │   └── sftp.ts            # SFTP API
│   │
│   ├── pages/                  # 页面组件
│   │   ├── auth/              # 登录页面
│   │   │   └── LoginPage.vue
│   │   ├── dashboard/         # 仪表板
│   │   │   └── DashboardPage.vue
│   │   ├── data/              # 数据管理
│   │   │   ├── DataManagementPage.vue
│   │   │   └── BatchReportPage.vue
│   │   ├── analysis/          # 数据分析（核心功能）
│   │   │   ├── AnalysisPage.vue
│   │   │   ├── components/    # 分析子组件
│   │   │   │   ├── HistogramTab.vue
│   │   │   │   ├── WaferMapPanel.vue
│   │   │   │   ├── CorrelationPanel.vue
│   │   │   │   ├── MultiLotPanel.vue
│   │   │   │   ├── BoxPlotPanel.vue
│   │   │   │   ├── ParameterTrendPanel.vue
│   │   │   │   ├── ParetoPanel.vue
│   │   │   │   └── BatchExportPanel.vue
│   │   │   └── composables/   # 可组合函数
│   │   │       ├── useHistogram.ts
│   │   │       ├── useCorrelation.ts
│   │   │       └── useExport.ts
│   │   ├── admin/             # 用户管理
│   │   │   └── UserManagementPage.vue
│   │   ├── settings/          # 系统设置
│   │   │   └── SettingsPage.vue
│   │   ├── sftp/              # SFTP 浏览器
│   │   │   └── SftpBrowserPage.vue
│   │   └── roadmap/           # 功能路线图
│   │       └── RoadmapPage.vue
│   │
│   ├── layouts/               # 布局组件
│   │   └── MainLayout.vue     # 主布局（侧边栏导航）
│   │
│   ├── components/            # 通用组件
│   │   └── ...
│   │
│   ├── stores/                # Pinia 状态管理
│   │   ├── auth.ts           # 认证状态
│   │   └── analysis.ts       # 分析状态
│   │
│   ├── router/               # 路由配置
│   │   └── index.ts          # 路由定义
│   │
│   ├── types/                # TypeScript 类型定义
│   │   └── index.ts          # 共享类型
│   │
│   ├── App.vue               # 根组件
│   ├── main.ts               # 应用入口
│   └── style.css             # 全局样式
│
├── public/                   # 静态资源
├── vite.config.ts           # Vite 配置
├── tsconfig.json            # TypeScript 配置
├── package.json             # 依赖和脚本
└── index.html               # HTML 入口
```

## 核心架构

### 1. API 层 (`src/api/`)

**Axios 实例配置** (`api/index.ts`):
```typescript
const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器 - 自动添加 JWT token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器 - 处理 401 未授权
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('access_token')
      router.push('/login')
    }
    return Promise.reject(error)
  }
)
```

**API 模块化** (`api/*.ts`):
- `auth.ts` - 登录、登出、用户信息、用户设置
- `datafiles.ts` - 文件上传、列表、激活、删除、数据浏览
- `analysis.ts` - 直方图、晶圆图、相关性、多批次对比等
- `batch.ts` - 批次报表
- `sftp.ts` - SFTP 文件浏览

**典型 API 调用**:
```typescript
// api/analysis.ts
export const getHistogram = (params: {
  file_id: number
  param_x: string
  bins?: number
  spec_lower?: number
  spec_upper?: number
}) => {
  return api.post('/analysis/histogram/', params)
}
```

---

### 2. 路由配置 (`src/router/index.ts`)

**路由定义**:
```typescript
const routes = [
  { path: '/login', component: LoginPage, meta: { requiresAuth: false } },
  { path: '/dashboard', component: DashboardPage, meta: { requiresAuth: true } },
  { path: '/data', component: DataManagementPage, meta: { requiresAuth: true } },
  { path: '/analysis', component: AnalysisPage, meta: { requiresAuth: true } },
  { path: '/batch', component: BatchReportPage, meta: { requiresAuth: true } },
  { path: '/sftp', component: SftpBrowserPage, meta: { requiresAuth: true } },
  { path: '/settings', component: SettingsPage, meta: { requiresAuth: true } },
  { path: '/roadmap', component: RoadmapPage, meta: { requiresAuth: true } },
  { path: '/admin/users', component: UserManagementPage, meta: { requiresAuth: true, requiresAdmin: true } },
]
```

**路由守卫**:
```typescript
router.beforeEach((to, from, next) => {
  const authStore = useAuthStore()
  
  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    next('/login')
  } else if (to.meta.requiresAdmin && authStore.user?.role !== 'administrator') {
    next('/dashboard')
  } else {
    next()
  }
})
```

---

### 3. 状态管理 (`src/stores/`)

**认证状态** (`stores/auth.ts`):
```typescript
export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as User | null,
    token: localStorage.getItem('access_token'),
  }),
  
  getters: {
    isAuthenticated: (state) => !!state.token,
    isAdmin: (state) => state.user?.role === 'administrator',
  },
  
  actions: {
    async login(username: string, password: string) {
      const { data } = await authApi.login(username, password)
      this.token = data.access
      localStorage.setItem('access_token', data.access)
      await this.fetchProfile()
    },
    
    async logout() {
      await authApi.logout()
      this.token = null
      this.user = null
      localStorage.removeItem('access_token')
      router.push('/login')
    },
    
    async fetchProfile() {
      const { data } = await authApi.getProfile()
      this.user = data
    },
  },
})
```

**分析状态** (`stores/analysis.ts`):
```typescript
export const useAnalysisStore = defineStore('analysis', {
  state: () => ({
    selectedFile: null as DataFile | null,
    selectedParams: [] as string[],
    chartConfig: {
      height: 400,
      dpi: 100,
      theme: 'light',
    },
  }),
  
  actions: {
    setSelectedFile(file: DataFile) {
      this.selectedFile = file
    },
    
    setSelectedParams(params: string[]) {
      this.selectedParams = params
    },
  },
})
```

---

### 4. 页面组件架构

**主布局** (`layouts/MainLayout.vue`):
- 顶部导航栏（用户信息、登出）
- 左侧边栏（菜单导航）
- 主内容区（`<router-view>`）

**分析页面** (`pages/analysis/AnalysisPage.vue`):
```vue
<template>
  <div class="analysis-page">
    <!-- 文件选择器 -->
    <FileSelector v-model="selectedFile" />
    
    <!-- 参数选择器 -->
    <ParameterSelector v-model="selectedParams" :file="selectedFile" />
    
    <!-- 分析标签页 -->
    <el-tabs v-model="activeTab">
      <el-tab-pane label="直方图" name="histogram">
        <HistogramTab :file="selectedFile" :params="selectedParams" />
      </el-tab-pane>
      
      <el-tab-pane label="晶圆图" name="wafermap">
        <WaferMapPanel :file="selectedFile" :params="selectedParams" />
      </el-tab-pane>
      
      <el-tab-pane label="相关性分析" name="correlation">
        <CorrelationPanel :file="selectedFile" :params="selectedParams" />
      </el-tab-pane>
      
      <!-- 更多标签页... -->
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useAnalysisStore } from '@/stores/analysis'

const analysisStore = useAnalysisStore()
const selectedFile = ref(null)
const selectedParams = ref([])
const activeTab = ref('histogram')
</script>
```

---

### 5. Composables 模式 (`pages/analysis/composables/`)

**直方图 Composable** (`useHistogram.ts`):
```typescript
export function useHistogram() {
  const loading = ref(false)
  const chartData = ref(null)
  const statistics = ref(null)
  
  const fetchHistogram = async (params: {
    file_id: number
    param_x: string
    bins?: number
    spec_lower?: number
    spec_upper?: number
  }) => {
    loading.value = true
    try {
      const { data } = await analysisApi.getHistogram(params)
      chartData.value = data.data
      statistics.value = data.statistics
    } catch (error) {
      ElMessage.error('获取直方图数据失败')
    } finally {
      loading.value = false
    }
  }
  
  return {
    loading,
    chartData,
    statistics,
    fetchHistogram,
  }
}
```

**使用 Composable**:
```vue
<script setup lang="ts">
import { useHistogram } from './composables/useHistogram'

const { loading, chartData, statistics, fetchHistogram } = useHistogram()

const handleAnalyze = () => {
  fetchHistogram({
    file_id: selectedFile.value.id,
    param_x: selectedParam.value,
    bins: 50,
  })
}
</script>
```

---

### 6. ECharts 图表集成

**基本用法**:
```vue
<template>
  <v-chart :option="chartOption" :style="{ height: '400px' }" />
</template>

<script setup lang="ts">
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, BarChart, LineChart, GridComponent, TooltipComponent, LegendComponent])

const chartOption = computed(() => ({
  title: { text: '直方图' },
  tooltip: { trigger: 'axis' },
  xAxis: { type: 'category', data: chartData.value?.bins },
  yAxis: { type: 'value' },
  series: [{
    type: 'bar',
    data: chartData.value?.counts,
  }],
}))
</script>
```

---

### 7. ag-Grid 表格集成

**基本用法**:
```vue
<template>
  <ag-grid-vue
    class="ag-theme-alpine"
    :columnDefs="columnDefs"
    :rowData="rowData"
    :pagination="true"
    :paginationPageSize="50"
    @grid-ready="onGridReady"
  />
</template>

<script setup lang="ts">
import { AgGridVue } from 'ag-grid-vue3'
import 'ag-grid-community/styles/ag-grid.css'
import 'ag-grid-community/styles/ag-theme-alpine.css'

const columnDefs = ref([
  { field: 'id', headerName: 'ID', sortable: true, filter: true },
  { field: 'filename', headerName: '文件名', sortable: true, filter: true },
  { field: 'format_type', headerName: '格式', sortable: true, filter: true },
  { field: 'status', headerName: '状态', sortable: true, filter: true },
])

const rowData = ref([])

const onGridReady = (params) => {
  // 网格就绪后的操作
}
</script>
```

---

## 设计模式和约定

### 1. Composition API 模式

**推荐使用 `<script setup>`**:
```vue
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'

// 响应式状态
const count = ref(0)

// 计算属性
const doubleCount = computed(() => count.value * 2)

// 方法
const increment = () => {
  count.value++
}

// 生命周期钩子
onMounted(() => {
  console.log('组件已挂载')
})
</script>
```

### 2. Props 和 Emits 类型定义

```vue
<script setup lang="ts">
interface Props {
  file: DataFile | null
  params: string[]
  height?: number
}

interface Emits {
  (e: 'update:file', value: DataFile): void
  (e: 'analyze', params: AnalysisParams): void
}

const props = withDefaults(defineProps<Props>(), {
  height: 400,
})

const emit = defineEmits<Emits>()
</script>
```

### 3. 组件通信模式

**父子组件通信**:
```vue
<!-- 父组件 -->
<ChildComponent
  :data="parentData"
  @update="handleUpdate"
/>

<!-- 子组件 -->
<script setup lang="ts">
const props = defineProps<{ data: any }>()
const emit = defineEmits<{ (e: 'update', value: any): void }>()

const handleChange = (value: any) => {
  emit('update', value)
}
</script>
```

**跨组件通信（使用 Pinia）**:
```typescript
// 在任何组件中
const analysisStore = useAnalysisStore()
analysisStore.setSelectedFile(file)
```

### 4. 错误处理模式

**API 调用错误处理**:
```typescript
try {
  const { data } = await analysisApi.getHistogram(params)
  // 处理成功响应
} catch (error) {
  if (axios.isAxiosError(error)) {
    ElMessage.error(error.response?.data?.message || '请求失败')
  } else {
    ElMessage.error('未知错误')
  }
}
```

**全局错误处理**:
```typescript
// main.ts
app.config.errorHandler = (err, instance, info) => {
  console.error('全局错误:', err, info)
  ElMessage.error('应用发生错误，请刷新页面')
}
```

### 5. 加载状态模式

```vue
<script setup lang="ts">
const loading = ref(false)

const fetchData = async () => {
  loading.value = true
  try {
    const { data } = await api.getData()
    // 处理数据
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <el-button :loading="loading" @click="fetchData">
    加载数据
  </el-button>
</template>
```

---

## 命名约定

- **文件名**: PascalCase (如 `AnalysisPage.vue`, `HistogramTab.vue`)
- **组件名**: PascalCase (如 `<FileSelector>`, `<ParameterSelector>`)
- **变量/函数**: camelCase (如 `selectedFile`, `fetchHistogram`)
- **常量**: UPPER_SNAKE_CASE (如 `API_BASE_URL`, `MAX_FILE_SIZE`)
- **类型/接口**: PascalCase (如 `DataFile`, `AnalysisParams`)
- **Composables**: use 前缀 (如 `useHistogram`, `useAuth`)
- **Store**: use 前缀 + Store 后缀 (如 `useAuthStore`, `useAnalysisStore`)

---

## TypeScript 类型定义 (`src/types/index.ts`)

```typescript
// 用户类型
export interface User {
  id: number
  username: string
  display_name: string
  role: 'administrator' | 'user' | 'viewer'
  email?: string
}

// 数据文件类型
export interface DataFile {
  id: number
  filename: string
  file_path: string
  file_size: number
  format_type: 'CTA8290D' | 'CTA8280F' | 'ETS88' | 'STS8200'
  row_count: number
  col_count: number
  program_name?: string
  status: 'pending' | 'parsing' | 'ready' | 'error'
  created_at: string
  updated_at: string
}

// 分析参数类型
export interface AnalysisParams {
  file_id: number
  param_x: string
  param_y?: string
  bins?: number
  spec_lower?: number
  spec_upper?: number
}

// 统计结果类型
export interface Statistics {
  mean: number
  std: number
  min: number
  max: number
  cpk?: number
  cp?: number
  sigma?: number
}
```

---

## Vite 配置 (`vite.config.ts`)

```typescript
export default defineConfig({
  plugins: [vue()],
  
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          'element-plus': ['element-plus'],
          'echarts': ['echarts', 'vue-echarts'],
          'ag-grid': ['ag-grid-vue3', 'ag-grid-community'],
        },
      },
    },
  },
})
```

---

## 开发指南

### 启动开发服务器

```bash
# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 构建生产版本
npm run build

# 预览生产构建
npm run preview

# 类型检查
npm run type-check

# 代码格式化
npm run format
```

### 添加新页面

1. 在 `src/pages/` 创建新页面组件（如 `NewPage.vue`）
2. 在 `src/router/index.ts` 添加路由：
   ```typescript
   {
     path: '/new-page',
     component: () => import('@/pages/NewPage.vue'),
     meta: { requiresAuth: true },
   }
   ```
3. 在 `MainLayout.vue` 侧边栏添加菜单项

### 添加新的分析功能

1. 在 `src/api/analysis.ts` 添加 API 方法：
   ```typescript
   export const getNewAnalysis = (params: NewAnalysisParams) => {
     return api.post('/analysis/new_analysis/', params)
   }
   ```

2. 在 `src/pages/analysis/composables/` 创建 Composable：
   ```typescript
   // useNewAnalysis.ts
   export function useNewAnalysis() {
     const loading = ref(false)
     const data = ref(null)
     
     const fetchData = async (params: NewAnalysisParams) => {
       loading.value = true
       try {
         const { data: result } = await analysisApi.getNewAnalysis(params)
         data.value = result
       } finally {
         loading.value = false
       }
     }
     
     return { loading, data, fetchData }
   }
   ```

3. 在 `src/pages/analysis/components/` 创建组件：
   ```vue
   <!-- NewAnalysisPanel.vue -->
   <script setup lang="ts">
   import { useNewAnalysis } from '../composables/useNewAnalysis'
   
   const { loading, data, fetchData } = useNewAnalysis()
   </script>
   ```

4. 在 `AnalysisPage.vue` 添加标签页

### 使用 Element Plus 组件

```vue
<template>
  <!-- 按钮 -->
  <el-button type="primary" @click="handleClick">点击</el-button>
  
  <!-- 表单 -->
  <el-form :model="form" :rules="rules" ref="formRef">
    <el-form-item label="用户名" prop="username">
      <el-input v-model="form.username" />
    </el-form-item>
  </el-form>
  
  <!-- 对话框 -->
  <el-dialog v-model="dialogVisible" title="提示">
    <span>这是一段信息</span>
  </el-dialog>
  
  <!-- 消息提示 -->
  <el-button @click="ElMessage.success('操作成功')">
    显示消息
  </el-button>
</template>
```

---

## 关键文件路径

- **应用入口**: `src/main.ts`
- **路由配置**: `src/router/index.ts`
- **Axios 配置**: `src/api/index.ts`
- **认证状态**: `src/stores/auth.ts`
- **分析状态**: `src/stores/analysis.ts`
- **分析页面**: `src/pages/analysis/AnalysisPage.vue`
- **主布局**: `src/layouts/MainLayout.vue`
- **类型定义**: `src/types/index.ts`
- **Vite 配置**: `vite.config.ts`

---

## 最佳实践

1. **组件拆分**: 单个组件不超过 300 行，复杂组件拆分为子组件
2. **类型安全**: 所有 API 调用、Props、Emits 都使用 TypeScript 类型
3. **响应式数据**: 使用 `ref` 和 `reactive`，避免直接修改 props
4. **计算属性**: 派生状态使用 `computed`，而非在模板中计算
5. **副作用管理**: 使用 `watch` 和 `watchEffect` 处理副作用
6. **生命周期**: 合理使用 `onMounted`、`onUnmounted` 等钩子
7. **错误处理**: 所有 API 调用必须有 try-catch 或 .catch()
8. **加载状态**: 异步操作显示加载状态，提升用户体验
9. **代码复用**: 提取可复用逻辑到 Composables
10. **性能优化**: 
    - 使用 `v-show` 代替频繁切换的 `v-if`
    - 长列表使用虚拟滚动
    - 图表数据量大时进行采样或分页
    - 使用 `shallowRef` 和 `shallowReactive` 优化大对象

---

## 常见问题

### Q: 如何处理跨域问题？
A: 开发环境使用 Vite 代理（`vite.config.ts` 中的 `server.proxy`），生产环境由后端配置 CORS。

### Q: 如何刷新 JWT token？
A: 在 Axios 响应拦截器中检测 401 错误，调用刷新 token API，重试原请求。

### Q: 如何优化图表性能？
A: 
- 数据量大时进行采样（如每 10 个点取 1 个）
- 使用 ECharts 的 `dataZoom` 组件实现缩放
- 使用 `large: true` 和 `largeThreshold` 配置
- 考虑使用 Canvas 渲染代替 SVG

### Q: 如何实现主题切换？
A: 
- Element Plus 使用 CSS 变量实现主题
- ECharts 使用 `theme` 配置
- 在 Pinia store 中管理主题状态

### Q: 如何处理大文件上传？
A: 
- 使用 `FormData` 上传文件
- 显示上传进度（Axios `onUploadProgress`）
- 考虑分片上传（大于 100MB 的文件）

---

## 相关资源

- Vue 3 文档: https://vuejs.org/
- TypeScript 文档: https://www.typescriptlang.org/
- Vite 文档: https://vitejs.dev/
- Element Plus 文档: https://element-plus.org/
- ECharts 文档: https://echarts.apache.org/
- ag-Grid 文档: https://www.ag-grid.com/
- Pinia 文档: https://pinia.vuejs.org/
- Vue Router 文档: https://router.vuejs.org/
