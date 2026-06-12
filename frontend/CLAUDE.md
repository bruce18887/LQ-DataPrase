# LQ-DataPrase 前端架构文档

## 技术栈

- **框架**: Vue 3.5.34 (Composition API, `<script setup>`)
- **语言**: TypeScript 6.0.2
- **构建工具**: Vite 8.0.14
- **UI 框架**: Element Plus 2.14.0
- **表格组件**: ag-grid-vue3 35.3.0
- **图表库**: ECharts 6.1.0, vue-echarts 8.0.1
- **状态管理**: Pinia 3.0.4 (Composition API 风格)
- **路由**: Vue Router 4.6.4 (懒加载, 嵌套 children)
- **HTTP 客户端**: Axios 1.16.1
- **图标**: @element-plus/icons-vue 2.3.2
- **测试**: Playwright 1.60.0 (E2E)

## 项目结构

```
frontend/
├── e2e/                      # Playwright E2E 测试（fixtures/helpers/smoke等11个模块）
├── src/
│   ├── api/                  # 7个API模块 + index.ts（Axios实例）
│   ├── pages/                # 9个页面（Dashboard/DataManagement/Analysis等，见路由章节）
│   │   ├── analysis/         # 核心：30+子组件（correlation/distribution/trend子目录）
│   │   └── data/             # 7个页面（DataManagement/BatchReport/DataBrowser等）
│   ├── layouts/              # MainLayout.vue（Sidebar + Topbar + keep-alive router-view）
│   ├── components/           # 7个通用组件 + Sidebar/Topbar
│   ├── stores/               # 3个Pinia Store（auth/analysis/theme，见状态管理章节）
│   ├── router/               # 路由配置 + 守卫（见路由章节）
│   ├── types/                # TypeScript 类型定义（见类型章节）
│   ├── theme/                # 设计Token（colors/typography/spacing）
│   ├── styles/               # 全局样式（variables.css双主题/Element Plus覆盖/工具类）
│   ├── utils/                # echarts-theme.ts
│   ├── constants/            # icons.ts 图标映射
│   ├── App.vue               # 根组件（仅 <router-view />）
│   ├── main.ts               # 应用入口
│   └── style.css             # 全局样式入口
├── playwright.config.ts      # Playwright E2E 配置
├── vite.config.ts            # Vite 配置
├── package.json
└── index.html
```

## 核心架构

### 1. API 层 (`src/api/`)

**Axios 实例** (`api/index.ts`):
```typescript
const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  paramsSerializer: { indexes: null },  // 数组参数不带索引
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('access_token', 'refresh_token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)
```

**API 模块**: `auth.ts` | `datafiles.ts` | `analysis.ts`（14个方法）| `batch.ts` | `buyoff.ts` | `gage.ts` | `sftp.ts`

---

### 2. 路由配置 (`src/router/index.ts`)

**结构**: 嵌套 children + 懒加载（`/` → `MainLayout` → 各页面）。已登录访问 `/login` 自动跳转 `/dashboard`。

```typescript
// 路由守卫
router.beforeEach((to, _from, next) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.isLoggedIn) next('/login')
  else if (to.path === '/login' && auth.isLoggedIn) next('/dashboard')
  else next()
})
```

| 路由 | 页面 | 说明 |
|------|------|------|
| `/login` | `LoginPage` | 登录页 |
| `/dashboard` | `DashboardPage` | 仪表板 |
| `/data` | `DataManagement` | 数据管理 |
| `/sftp` | `SftpBrowser` | SFTP 浏览器 |
| `/analysis` | `AnalysisPage` | 数据分析（核心） |
| `/batch` | `BatchReport` | 批次报表 |
| `/admin/users` | `UserManagement` | 用户管理（管理员） |
| `/settings` | `SettingsPage` | 系统设置 |
| `/roadmap` | `RoadmapPage` | 功能路线图 |

---

### 3. 状态管理 (`src/stores/`)

全部 Composition API 风格（`defineStore('name', () => { ... })`）。

**认证 Store** (`auth.ts`): `token`, `refreshToken`, `user`, `isLoggedIn`, `isAdmin`, `login()`, `logout()`

**分析 Store** (`analysis.ts`): `selectedFileId`, `selectedParam`, `activeTab`, `chartMode`(distribution\|qqplot), `chartConfig`(\['limit','s6'\]), `rangeType`('RDL'), `barWidthPercent`(20), `ignoreNoLimit`, `customLow`/`customHigh`, `comparisonMode`('boxplot'|'multilot'), `reset()`

**主题 Store** (`theme.ts`): `currentTheme`('light'|'night'), `toggleTheme()`, `setTheme()`, watch 自动同步 DOM（`data-theme` + class）和 localStorage。

---

### 4. 页面组件架构

**主布局**: `<Sidebar />`（可折叠 240px/64px，含分组/管理员菜单控制）+ `<Topbar />`（面包屑/搜索/主题切换/通知/用户菜单）+ `<keep-alive>` 包裹的 `<router-view>`。

**分析页面** (`AnalysisPage.vue`): `el-select` 选文件 → 触发 `onFileChange` 获取参数列表 → `el-tabs` 5 个标签页（单参数分析 / 晶圆图 / 分布对比 / 趋势与失效 / 相关性工具），所有 tab 共享 `params` 数据源。

---

### 5. 双主题系统

CSS 变量 + `data-theme` 属性。light（白底灰字/蓝色品牌色）/ night（深色背景/霓虹蓝绿）。

**主题 Token 链**: `stores/theme.ts` → `data-theme` 属性 → `styles/variables.css` → `styles/element-plus-theme.css` → `utils/echarts-theme.ts`

---

### 6. ECharts 图表集成

渲染器：默认 SVG（清晰），大数据量切 Canvas。通过 `useEChartsTheme()` 自动跟随主题。

```vue
<script setup lang="ts">
import { use } from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([BarChart, LineChart, GridComponent, TooltipComponent, LegendComponent])
const { getBaseOption } = useEChartsTheme()

const chartOption = computed(() => ({
  ...getBaseOption.value,
  xAxis: { type: 'category', data: bins },
  yAxis: { type: 'value' },
  series: [{ type: 'bar', data: counts }],
}))
</script>
```

---

### 7. ag-Grid 表格集成

```vue
<script setup lang="ts">
import { AgGridVue } from 'ag-grid-vue3'
import 'ag-grid-community/styles/ag-grid.css'
import 'ag-grid-community/styles/ag-theme-alpine.css'

const columnDefs = ref([
  { field: 'id', sortable: true, filter: true },
  { field: 'filename', sortable: true, filter: true },
  { field: 'format_type', sortable: true, filter: true },
  { field: 'status', sortable: true, filter: true },
])
</script>

<template>
  <ag-grid-vue
    class="ag-theme-alpine"
    :columnDefs="columnDefs" :rowData="rowData"
    :pagination="true" :paginationPageSize="50"
    @grid-ready="onGridReady"
  />
</template>
```

---

## 设计模式和约定

### 组件模式

**Props / Emits 类型**:
```vue
<script setup lang="ts">
interface Props { fileId: number | null; params: string[]; loading: boolean }
interface Emits { (e: 'load', param: string, colorBy: string): void }
const props = withDefaults(defineProps<Props>(), { params: () => [] })
const emit = defineEmits<Emits>()
</script>
```

**组件通信**: Props down + Events up / 跨组件 Pinia Store

**错误处理**:
```typescript
try { const { data } = await api.getData() } catch (error) {
  if (axios.isAxiosError(error)) ElMessage.error(error.response?.data?.detail || '请求失败')
  else ElMessage.error('未知错误')
}
```

**加载状态**:
```typescript
const loading = ref(false)
const fetchData = async () => { loading.value = true; try { /* ... */ } finally { loading.value = false } }
```

### 命名约定

- 文件名 / 组件名：PascalCase（`AnalysisPage.vue`）
- 变量 / 函数：camelCase（`selectedFileId`, `fetchHistogram`）
- Composables / Store：use 前缀（`useHistogram`, `useAuthStore`）
- 页面文件：不含 Page 后缀（`DataManagement.vue`），例外：`LoginPage`, `DashboardPage`, `AnalysisPage`, `SettingsPage`, `RoadmapPage`

---

## TypeScript 类型定义 (`src/types/index.ts`)

```typescript
export interface User {
  id: number
  username: string
  email: string
  display_name: string
  role: 'administrator' | 'user' | 'viewer'
}

export interface UserSettings {
  page_size: number
  chart_height: number
  table_height: number
  chart_dpi: number
  cpk_a_threshold: number
  cpk_b_threshold: number
  cpk_c_threshold: number
  chart_engine: string
  chart_renderer: 'svg' | 'canvas'
}

export interface DataFile {
  id: number
  filename: string
  format_type: string
  row_count: number
  col_count: number
  program_name: string
  status: string
  created_at: string
}

export interface DashboardMetrics {
  total_rows: number
  pass_count: number
  yield_pct: number
  format: string
}

export interface BinStat {
  bin: number | string
  count: number
  percentage: number
}

export interface SiteYield {
  site: string
  yield: string
  pass: number
  total: number
}

export interface FailTestItem {
  name: string
  fail_count: number
  percentage: number
}
```

---

## Vite 配置

```typescript
export default defineConfig({
  plugins: [vue()],
  server: { host: '0.0.0.0', port: 3000, proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } } },
})
```

---

## E2E 测试 (Playwright)

```bash
cd frontend
npm run test:e2e           # 全量运行（自动拉起 Django:8000 + Vite:3000）
npm run test:e2e:p0        # 冒烟
npm run test:e2e:ui        # UI 模式
npx playwright test e2e/analysis  # 按模块
```

环境变量: `PW_NO_WEBSERVER=1`（不自动拉起前后端）, `PYTHON_BIN`（默认 `.venv/Scripts/python.exe`）, `PARAM_SAMPLE_COUNT`（默认 5）

---

## 开发指南

### 启动 / 构建

```bash
npm run dev         # → http://localhost:3000
npm run build       # vue-tsc + Vite 构建
```

### 添加新页面
1. `src/pages/` 创建组件
2. `router/index.ts` children 添加（懒加载 `() => import(...)`）
3. `Sidebar.vue` menuItems 添加菜单项（管理员权限设 `requiresAdmin: true`）

### 添加分析功能
1. `api/analysis.ts` 添加 API
2. `pages/analysis/composables/` 创建 Composable
3. `pages/analysis/components/` 创建 UI 组件
4. `AnalysisPage.vue` 添加 `<el-tab-pane>`

### 主题适配
修改颜色时同时维护 CSS 变量中 light 和 night 两套值：`variables.css` + `echarts-theme.ts` + `element-plus-theme.css`

---

## 最佳实践

1. **组件拆分**: ≤ 300 行，复杂组件拆子组件
2. **类型安全**: API 调用、Props、Emits 用 TypeScript 类型
3. **错误处理**: 所有 API 调用必须 try-catch
4. **加载状态**: 异步操作显示 loading
5. **代码复用**: 提取到 Composables
6. **双主题**: 任何前端改动维护 light 和 night 两套主题