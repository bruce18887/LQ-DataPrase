# QQ 图切换参数后空白 + histogram 500 / qqplot 400 修复

## 背景 / 现象
- gage_m_S4.csv → 数据分析 → 打开「显示QQ图」→ 切换测试项，QQ 图区域变空白（首次正常）。
- 控制台偶发：`POST /analysis/qqplot/ 400`、`POST /analysis/histogram/ 500`（切换文件时）。

## 根因（已用 Playwright + 后端脚本复现验证）
1. **主因 — QQ 图空白**：`frontend/src/composables/useChart.ts` 的 `ensureInit()` 在 `chartInstance` 已存在时直接 return，
   不处理「容器被 v-if/v-else 销毁后重建」的场景。`QQPlotChart.vue` 在 `loadQQPlot` 开头把 `qqResult=null`，
   导致图表 `<div ref=chartRef>` 被销毁；新数据到达后重建出**新 div**，但 useChart 仍对**绑定到旧（已脱离 DOM）节点的旧实例** setOption → 新 div 永远空白。
   （histogram 不复现是因为 histResult 从不被置 null，容器不销毁。）
2. **次因 — histogram 500**：切换文件瞬间，子组件 watcher 用上一文件的 stale param 发请求。
   `qqplot` 视图有 `if param not in df.columns -> 400` 守卫；`histogram` 视图**没有**，直接 `df[param]` → KeyError → 500。

## 修复方案（最小、根因）
- [x] `useChart.ts`：`ensureInit()` 检测当前实例绑定的 DOM 是否仍是 live 的 `chartRef`，否则 dispose 旧实例并在新容器重建。（修复 QQ 空白；对不切换容器的图表零行为变化）
- [x] `apps/analysis/views.py histogram`：循环内跳过不在 `df.columns` 的 param，避免 KeyError 500（与 qqplot 守卫行为一致）。
- [x] 后端测试：histogram 未知 param 返回 200 而非 500。
- [x] E2E：QQ 图开启后连续切换参数，图表 canvas/svg 持续渲染（不空白）。

## Review
- **改动文件**:
  - `frontend/src/composables/useChart.ts` — `ensureInit()` 检测容器重建并 dispose+重建旧实例（主修）。
  - `apps/analysis/views.py` — histogram 循环跳过不在 df.columns 的 param（防 500）。
  - `apps/analysis/tests.py` — 新增 `HistogramUnknownParamViewTests`（3 用例）。
  - `frontend/e2e/analysis/analysis.spec.ts` — 新增「连续切换参数 QQ 图持续渲染不空白」回归用例。
- **验证**:
  - 后端：`manage.py test apps.analysis.tests` 相关 8 用例全过。
  - 前端 e2e：还原 useChart 修复 → 用例 fail（2 failed）；恢复修复 → pass（4 passed）。证明回归测试有效。
  - 用户手动确认 QQ 图切换不再空白。
  - tsc 报错均为既有、与本次改动无关文件（YieldTrendChart/ExportToolsTab/FileManager）。
- **未做**: 前端 onFileChange 主动清 selectedParam（次因的另一层防护）。后端守卫已足以消除 500，qqplot 400 本就被前端 catch；保持最小改动，未额外引入。
- **临时文件**: 已删除 test/tmp_scan_*.py、test/tmp_gage.py、qq-state.png。用户自建 params_list.txt / tmp_test_qqplot.py 保留未动。
