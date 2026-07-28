# Lessons Learned

## 2026-07-28 ECharts 切换文件后空白

**现象**: 分析页加载第二个文件后，ECharts 图表区域变成空白。

**根因**: `frontend/src/composables/useChart.ts` 中，当容器初始尺寸为 0 时，`initEchartsWhenReady` 会异步初始化 ECharts 实例。`useChart` 的 source watcher 触发 `ensureInit()` 时实例尚未就绪，因此 `renderOption()` 被跳过；等轮询拿到实例后，只把实例赋给 `chartInstance` 却未再次调用 `renderOption()`，导致图表永远拿不到最新 option。

**修复**: 在异步初始化轮询里，实例就绪后补充调用 `renderOption()`。

**规则**:
- 异步初始化的图表必须在实例就绪后主动重渲染一次。
- 任何依赖 `chartInstance.value` 的渲染逻辑都要覆盖「同步就绪」和「异步就绪」两条路径。

## 2026-07-29 ECharts 切换 tab/路由缓存后空白

**现象**: 数据分析页切换 `el-tabs` 标签页，或从其它页面返回（`<keep-alive>`）后，ECharts 区域经常空白不渲染。

**根因**:
- `el-tabs` 非活动页用 `display:none` 隐藏，图表容器尺寸变为 0；重新显示时 ECharts 未收到 `resize()`，画布/SVG 尺寸未恢复。
- 页面被 `<keep-alive>` 缓存时，路由返回触发 `onActivated` 而非 `onMounted`；`useChart` 原只处理 `onMounted`，实例绑定在曾 detached 的 DOM 上，重绘失败。
- `lazyUpdate: true` 在隐藏期间调用 `setOption` 时渲染帧被跳过，恢复可见后没有强制重绘。

**修复**:
- `useChart` 增加持续 `ResizeObserver`：容器从 0 尺寸恢复时执行 `resize()` + 当前 option 重新 `setOption`。
- 增加 `onActivated` 生命周期钩子，在 keep-alive 重新激活时校验实例并强制 resize/重绘。
- `ensureInit()` 增加 `handle` 非空守卫，防止异步等待期间被重复调用产生冗余 observer。

**规则**:
- 所有图表容器必须持续监听尺寸/可见性变化，并在恢复可见时主动 `resize()`。
- 使用 `<keep-alive>` 的页面中的图表 composable 必须同时处理 `onMounted` 和 `onActivated`。
- 对 `lazyUpdate` 图表，容器恢复可见后应使用当前 option 强制同步渲染一次。
