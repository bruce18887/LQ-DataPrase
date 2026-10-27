# LQ-DataPrase 前端架构文档

## 双主题系统

CSS 变量 + `data-theme` 属性。light（白底灰字/蓝色品牌色）/ night（深色背景/霓虹蓝绿）。

**主题 Token 链**: `stores/theme.ts` → `data-theme` 属性 → `styles/design-tokens.css` → `styles/element-plus-theme.css` → `utils/echarts-theme.ts`

## 命名约定

- 文件名 / 组件名：PascalCase（`AnalysisPage.vue`）
- 变量 / 函数：camelCase（`selectedFileId`, `fetchHistogram`）
- Composables / Store：use 前缀（`useHistogram`, `useAuthStore`）
- 页面文件：不含 Page 后缀（`DataManagement.vue`），例外：`LoginPage`, `DashboardPage`, `AnalysisPage`, `SettingsPage`, `RoadmapPage`

## E2E 测试 (Playwright)

跑哪一档的判据只有一份：`docs/reference/testing-gates.md`（§1 该跑哪一档 / §5 各入口速查）。
本节只留默认入口，不复制判据表。

```bash
cd frontend
npm run test:e2e:affected  # 默认档：每批 commit 前，按本次改动选例
npm run test:e2e:p0        # 冒烟
npm run test:e2e:ui        # UI 模式
```

`frontend/package.json` 里其余 e2e 脚本不要按名字猜档位：`npm run test:e2e`（裸 `playwright test`）
已被那份文档 §5 明令**不要用**；全量与并行、按模块定向（含 SFTP 用例该归哪个 project）都以 §5 为准。

e2e测试需要跑全量或者预估时间大于10分钟时需要询问我的意见

环境变量: `PW_NO_WEBSERVER=1`（不自动拉起前后端）, `PYTHON_BIN`（默认 `.venv/Scripts/python.exe`）, `PARAM_SAMPLE_COUNT`（默认 5）

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
修改颜色时同时维护 CSS 变量中 light 和 night 两套值：`design-tokens.css` + `echarts-theme.ts` + `element-plus-theme.css`

## 最佳实践

1. **组件拆分**: ≤ 300 行，复杂组件拆子组件
