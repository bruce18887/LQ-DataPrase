# 通用组件（`frontend/src/components/common`）

跨页复用的展示型组件，共 19 个。**props 一律以各 SFC 的 `defineProps` 为准**，
本文件不再抄一遍参数表——上一版在这里写着 `Card variant="neon"`、
`Button variant="secondary"` 和一份 `#58a6ff` 硬编码色板，而 `Card.vue:24` 的注释记着
neon 变体早已随双主题 token 化移除：文档复述代码 = 必然漂移。

## 没有 barrel 文件

原先这里有 `index.ts` 桶文件，示例写着 `import { Card } from '@/components/common'`。
**两者都已删除**：全仓普查 0 个调用方走桶路径，全部按单文件 import。桶文件让
「谁在用哪个组件」从一次 grep 变成两次检索，也让「删掉某个组件」看起来比实际危险。

实际写法：

```typescript
import Card from '@/components/common/Card.vue'
import { Search } from '@element-plus/icons-vue'   // 图标同理：谁用谁 import
```

入口不再全局注册 EP 图标——`main.ts` 里那个把该包 586 个导出注册成全局组件的循环已删
（实测 37 个用 `<el-icon>` 的 `.vue` 逐个自带显式 import，模板里 6 处 `<component :is>`
传的都是组件对象，0 处依赖全局图标名）。

## 主题

- 组件内只写 CSS 变量（`var(--text)` / `var(--brand)` / `var(--p-fs-dense)` …），
  **禁止硬编码色值**。light/night 两份由 `src/styles/design-tokens.css` 提供。
- 设计口径的唯一事实来源：[`docs/reference/ui-design-guide.md`](../../../docs/reference/ui-design-guide.md)。
- ECharts 不认 CSS 变量：图表配色取 `useEChartsTheme()` 的 JS 语义色，别在这里拿 `var(--x)`。

## 组件清单

| 组件 | 用途 | 需要知道的坑 |
|---|---|---|
| `ActiveSearchChip` | SFTP 搜索运行中的常驻芯片 | 挂在 `MainLayout` 层，切到任何页面都还在 |
| `AppAboutDialog` | 「关于」对话框 | 兼作 Electron 菜单 `menu-about` 的监听者（仅挂载期间） |
| `AppLogo` | 品牌标 | 登录页与侧栏共用 |
| `Badge` | 通用小徽章 | |
| `Button` | 按钮 | `variant` 见 `Button.vue:24` |
| `Card` | 卡片壳 | `variant` 见 `Card.vue:34`；neon/elevated 那批旧变体已移除 |
| `CircularProgress` | 环形进度 | 内部定时器在 stop / 卸载 / 重入三条路径都清 |
| `CollapsibleSection` | 可折叠分区 | 收起 = 卸载重挂，是文档化的有意设计（不是 bug） |
| `CpkBadge` | CPK 等级徽章 | 阈值来自用户设置；A>B>C 的约束目前只在前端 |
| `Empty` | 空态 | |
| `ErrorBanner` | 错误横幅 | 文案由 `utils/error.ts` 的 `formatError` 归一 |
| `FileSelect` | 文件下拉：搜索 / 高亮 / 分组 / 元信息行 | 数据源上限 5,000 行（`api/datafiles.ts` 的 options limit）；高亮正则按查询词编译一次，`formatTime` 是 Intl 单例 |
| `JobProgressChip` | 导出作业进度芯片 | 与 `composables/useJobExport` + `jobPolling` 配套 |
| `Loading` | 加载态 | |
| `ThemeToggle` | 明/夜切换 | 样式只保留一层语义化规则，别再叠第二段 `:hover` |
| `YieldBadge` | 良率徽章 | |
| `ZoomIndicator` | 缩放指示 | 与 `composables/useZoom` 配套；CSS zoom 下 EP 浮层坐标要乘 (zoom−1) |
