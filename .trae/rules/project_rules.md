---
alwaysApply: false
---
# DataPhrase 开发规范（重构后）

## 1. 项目状态速览

| 模块 | 状态 |
|------|------|
| accounts（认证/用户管理） | ✅ 完成 |
| datafiles（文件管理/ATE解析器） | ✅ 完成 |
| analysis（统计分析服务） | ⚠️ services/statistics.py 有完整逻辑，views 全是占位桩 |
| dashboard/analysis 前端 | ⚠️ 占位页面，等待视图对接 |
| batch_report/buyoff/gage/export/sftp | ⚠️ 骨架桩 |
| ECharts/AgGrid 组件 | ❌ 未创建 |
| Pinia stores（除 auth 外） | ❌ 未创建 |

---

## 2. 技术栈（实际）

| 层级 | 技术 | 备注 |
|------|------|------|
| 后端 | Django 6.0 + DRF + SimpleJWT + Celery + Redis | 项目在根目录，不在 `backend/` |
| 数据库 | PostgreSQL 16（生产）/ SQLite（本地开发） | `development.py` 覆盖为 SQLite |
| 前端 | Vue 3 + TS + Element Plus + vue-echarts | **未安装 ag-grid-vue** |
| 图表 | vue-echarts（前端）/ Matplotlib（服务端导出） | ECharts option 构建放 `utils/chart-config.ts` |
| 状态 | Pinia（Composition API 风格） | 当前仅 `stores/auth.ts` |
| API文档 | drf-spectacular Swagger | `/api/schema/swagger/` |
| 部署 | Docker Compose（db+redis+backend+celery） | 无 nginx/MinIO |

---

## 3. 后端开发规范

### 3.1 设置文件

- **`config/settings/base.py`** — 唯一权威配置，所有通用设置在此
- **`config/settings/development.py`** — 从 `base` 导入，覆盖 `DEBUG=True` + 数据库为 SQLite
- **`config/settings/__init__.py`** — **已废弃**，不要修改
- `AUTH_USER_MODEL = 'accounts.User'`

### 3.2 Django App 结构

每个 app 标准文件：

```python
apps/<name>/
├── models.py       # Django Models
├── views.py        # ViewSet / APIView
├── serializers.py  # DRF Serializer
├── services.py     # 业务逻辑（或 services/ 包）
├── urls.py         # Router 注册
├── tasks.py        # Celery 异步任务（如需要）
├── tests.py        # 测试
└── admin.py
```

### 3.3 URL 注册模式

每个 app 的 `urls.py` 使用 DRF Router：

```python
from rest_framework.routers import DefaultRouter
from .views import SomeViewSet

router = DefaultRouter()
router.register(r'prefix', SomeViewSet, basename='prefix')

urlpatterns = router.urls
```

根 `config/urls.py` 中注册：
```python
path('api/v1/', include('apps.<name>.urls')),
```

### 3.4 视图开发模式

- **简单 CRUD** → `ModelViewSet` + `serializer_class`
- **自定义操作** → `GenericViewSet` + `@action(detail=False, methods=['post'])`
- **独立端点** → `APIView` 子类
- 每个 action 必须加 `@extend_schema(summary='...')` 用于 Swagger
- 权限默认 `IsAuthenticated`；管理员操作用 `FeaturePermission`

### 3.5 业务逻辑层

- 复杂计算逻辑放在 `services.py`（或 `services/` 包），**不在 views 中直接写**
- 参照 `apps/analysis/services/statistics.py` 的纯函数模式
- 视图只做：参数校验 → 调 service → 序列化返回

### 3.6 ATE 解析器

- 新增格式：在 `apps/datafiles/parsers/` 创建文件，继承 `BaseATEParser`
- 在 `__init__.py` 的 `PARSER_REGISTRY` 中注册
- 大文件解析通过 Celery 异步（参照 `tasks.py` 中的 `parse_data_file_task`）

---

## 4. 前端开发规范

### 4.1 项目结构

```
frontend/src/
├── api/          # axios 请求封装，按模块拆分
│   └── index.ts  # 共享实例：baseURL=/api/v1，自动 Bearer token，401 跳登录
├── components/   # 通用组件（待建）
│   ├── charts/   # ECharts 图表组件
│   ├── table/    # 表格组件
│   └── common/   # 通用 UI 组件
├── composables/  # 组合式函数（待建）
├── layouts/      # 页面布局 MainLayout.vue
├── pages/        # 页面视图，按模块目录
├── router/       # 路由 + 守卫
├── stores/       # Pinia，Composition API 风格，按模块拆分
├── types/        # TS 类型定义
└── utils/        # 工具函数（待建）
    └── chart-config.ts  # ECharts option 构建
```

### 4.2 新增页面

1. 在 `pages/<模块>/` 创建 `XxxPage.vue`
2. 在 `router/index.ts` 添加路由（`MainLayout` children 下），设置 `meta: { title: '...' }`
3. 使用 `<script setup lang="ts">` + Composition API
4. API 调用必须通过 `api/` 封装，不得在组件内直接 `fetch`/`axios`

### 4.3 Pinia Store

```typescript
// 参照 stores/auth.ts 的模式
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useXxxStore = defineStore('xxx', () => {
  const data = ref<SomeType | null>(null)

  async function fetchData() {
    const { data } = await xxxApi.list()
    ...
  }

  return { data, fetchData }
})
```

- 按模块拆分 store（`auth`, `datafiles`, `analysis`, `settings`），禁止单一全局 store

### 4.4 ECharts 图表组件

- 每个图表类型一个组件：`HistogramChart.vue`, `WaferMap.vue`, `PieChart.vue` 等
- option 构建逻辑抽到 `utils/chart-config.ts`，组件仅负责渲染
- 使用 `<VChart>` (vue-echarts) 组件

### 4.5 API 封装

- 在 `api/<module>.ts` 中导出命名对象（参照 `api/datafiles.ts`）
- 使用 `api/index.ts` 的共享 axios 实例

---

## 5. 数据处理规范

- 文件上传：当前为整文件上传（非分片），若需分片上传再扩展
- 解析流程：上传 → Celery 解析 → 更新 DataFile 状态（pending → parsing → ready/error）
- 缓存：使用 Redis（`django.core.cache` + `@st.cache_data` 已剥离）
- 文件存储：`media/` 目录（框架级），暂未接入 MinIO/S3

---

## 6. 部署规范

### Docker Compose（开发/小团队）

```yaml
# 4 个服务：db(postgres) + redis + backend(runserver) + celery_worker
# docker compose up -d 即可启动全部
```

- 环境变量通过 `.env` 注入，**禁止硬编码密钥**
- `SECRET_KEY` 和数据库密码从环境变量读取

### 生产环境（待完善）

- 需添加：nginx（静态文件 + 反向代理）、gunicorn 替代 runserver
- 建议添加：MinIO/S3 对象存储用于文件

---

## 7. 开发优先顺序（下一步）

1. **完善 `settings/__init__.py`**：删除或合并到 `base.py`，消除设置分歧
2. **补充 `requirements/` 目录**：创建 `base.txt` 和 `production.txt`（Dockerfile 需要）
3. **创建缺失的前端目录**：`components/`, `composables/`, `utils/`
4. **对接 analysis views**：将 `services/statistics.py` 的业务逻辑接入到占位 views 中
5. **创建 ECharts 图表组件**：`HistogramChart.vue`, `WaferMap.vue`, `PieChart.vue` 等
6. **完善 DashboardPage**：对接真实 API
7. **完善 AnalysisPage**：直方图、序列分布、晶圆图、多 Lot 对比
8. **批量实现其余骨架 app**：buyoff → gage → batch_report → export → sftp

---

## 8. 禁例

- ❌ view 中直接写业务计算逻辑 → 放 `services.py`
- ❌ 组件中直接 `axios.post('/api/v1/...')` → 放 `api/` 封装
- ❌ ECharts option 在组件内硬编码 → 放 `utils/chart-config.ts`
- ❌ 新建单一全局 Pinia store → 按模块拆分（`datafiles`, `analysis`, `settings` 等）
- ❌ 硬编码密钥/密码 → 环境变量
- ❌ 修改 `config/settings/__init__.py` → 已废弃
- ❌ API 返回未序列化的 Django Model → 必须用 DRF Serializer

## 9. 常见运行时警告修复规范

### 9.1 Element Plus `el-statistic` 的 `value` 类型

- `el-statistic` 的 `value` prop 要求类型为 `Number | Object`，禁止传入字符串
- 若后端返回或计算结果为字符串，需用 `Number()` 转换或保持数值类型到模板绑定前再格式化
- ❌ 错误示例：`:value="max.toFixed(2)"`（toFixed 返回字符串）
- ✅ 正确示例：`:value="max"`，让组件内部处理格式化；或 `:value="Number(max.toFixed(2))"`

### 9.2 ECharts `color: 'auto'` 已废弃

- ECharts 5.x+ 中 `color: 'auto'` 已被废弃，控制台会报 `[ECharts] DEPRECATED: color: 'auto' is deprecated; use color: 'inherit' instead.`
- 所有 ECharts option 中涉及 `color: 'auto'` 的地方（常见于 gauge 的 `axisTick`、`splitLine`、`detail` 等）必须替换为 `color: 'inherit'`
- ❌ 错误示例：`axisTick: { lineStyle: { color: 'auto' } }`
- ✅ 正确示例：`axisTick: { lineStyle: { color: 'inherit' } }`
