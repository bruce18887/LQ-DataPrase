# 分析页四 tab 文件选择与数据筛选对齐单文件 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把晶圆图/相关性/多文件三个 tab 的文件选择与数据筛选对齐单文件 tab 的形态——文件选择统一在顶部 toolbar 行、数据筛选统一为 toolbar 第二行的 bar 内联（晶圆图按后端口径不展示筛选）。

**Architecture:** 零 store 改动、零组件 props/emit 变化。`AnalysisFilePicker` 与 `DataFilterSection variant="bar"` 全部复用现成实现，只移动模板位置：相关性把 DataFilterSection 从左栏卡片切到 toolbar 第二行；晶圆图与多文件自建顶部 toolbar 盒（复用提取出的共享 `.dp-analysis-toolbar` 样式）。e2e 契约属性（data-file-picker / data-filter / popper-class）零变化，但 7 处存量 spec 的 `.left-panel .el-select` 层级定位器必须同步迁移到契约属性定位。

**Tech Stack:** Vue 3 + Element Plus（前端）、Playwright（e2e）。

**Spec:** `docs/specs/2026-09-07-analysis-unified-toolbar-controls-design.md`（已批准，注意 docs/specs/ 在 .gitignore 中，不入 git）

**硬约束（项目规则）:**
- 单文件 ≤600 行：CorrelationToolsTab.vue 现 514 行、MultiFileTab.vue 现 445 行，删大于增，不越线
- dark+light 双主题：新增样式只认 `var(--xxx)` token（R7）
- `npm run build` = vue-tsc -b + vite build，唯一有效类型门禁（R8）
- e2e 跑完释放所有端口；e2e 前确认无未钉 `LQDP_SYSTEM_CONFIG_FILE` 的残留 runserver（lessons 9-05）
- 提交需用户授权——每批次 commit 前先向用户确认

**e2e 影响面（已 grep 确认）:**
- 多文件文件多选移出左栏 → 7 个 spec 的 `.left-panel .el-select`/`.first()` 定位全部改为 `[data-file-picker="multi"]` 契约定位：
  `file-select.spec.ts:102,134`、`multi-file.spec.ts:30`、`multi-file-filter.spec.ts:26`、`histogram-multiseries-clip.spec.ts:109`、`legend-color.spec.ts:66`、`axis-label-precision.spec.ts:259`、`tab-request-fanout.spec.ts:54`
- 相关性筛选从左栏卡片移到 toolbar → `multi-file-filter.spec.ts` 的 `filterControl` 用 `.el-tab-pane:visible [data-filter=…]` 定位，层级无关，零改动
- 晶圆图文件选择从自绘 el-row 移入 toolbar 盒 → `pickTabFile(page, 'wafer', …)` 用 `[data-file-picker="wafer"]` 定位，层级无关，零改动
- `multi-file.spec.ts:282` 的范围类型定位（`.left-panel .el-card` filter hasText '范围类型'）不受影响（范围类型卡不动）

---

## Task 1: 提取共享 toolbar 盒样式

**Files:**
- Modify: `frontend/src/styles/utilities.css`（文件末尾追加）
- Modify: `frontend/src/pages/analysis/components/AnalysisTabLayout.vue:45-54`（改用共享 class）

- [ ] **Step 1.1: utilities.css 末尾追加共享样式**

```css
/* ========== 分析页顶部 toolbar 盒 ==========
 * AnalysisTabLayout 与晶圆图/多文件 tab 自建的顶部控件盒共用；
 * 全部语义 token，dark/light 自动生效。 */
.dp-analysis-toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: var(--bg-3, #f8f9fa);
  border-radius: 6px;
  border: 1px solid var(--border-2, #e4e7ed);
}
```

- [ ] **Step 1.2: AnalysisTabLayout.vue 的 `.toolbar` 改为挂共享 class**

模板改：`<div v-if="$slots.toolbar" class="toolbar dp-analysis-toolbar">`；
scoped 样式删掉 `.toolbar { ... }` 整块（display/gap/margin/padding/background/border-radius/border 7 行），scoped 里不再保留 `.toolbar` 规则。

改后模板行：

```html
    <div v-if="$slots.toolbar" class="toolbar dp-analysis-toolbar">
```

- [ ] **Step 1.3: 类型门禁**

```bash
cd frontend && npm run build
```

预期：BUILD 成功，无新增错误（grep 自己改的两个文件名确认无回归，R8②）。

- [ ] **Step 1.4: 快速 e2e 冒烟（toolbar 结构改动影响所有 tab）**

```bash
cd frontend && npx playwright test e2e/analysis/tab-independent-files.spec.ts --project=P1
```

预期：全 PASS（该 spec 覆盖四 tab 文件选择器契约）。

- [ ] **Step 1.5: commit（先向用户确认）**

```bash
git add frontend/src/styles/utilities.css frontend/src/pages/analysis/components/AnalysisTabLayout.vue
git commit -m "refactor(analysis): 提取 .dp-analysis-toolbar 共享样式，AnalysisTabLayout 复用"
```

---

## Task 2: 相关性 tab——筛选从左栏卡片移入 toolbar 第二行

**Files:**
- Modify: `frontend/src/pages/analysis/components/CorrelationToolsTab.vue:5-26`（toolbar + 左栏）

- [ ] **Step 2.1: toolbar 扩成两行，左栏删 DataFilterSection**

模板 toolbar 段改为（两行结构对齐 SingleParamTab 的 control-panel）：

```html
    <!-- 工具栏：第一行文件选择 + 第二行数据筛选 bar（对齐单文件 tab 两行结构） -->
    <template #toolbar>
      <div class="control-panel">
        <div class="control-panel__main">
          <AnalysisFilePicker
            v-model="fileId"
            :files="files"
            scope="correlation"
            :loading="listLoading"
          />
        </div>
        <div class="control-panel__filters">
          <DataFilterSection
            variant="bar"
            scope="correlation"
            v-model:ignore-no-limit="ignoreNoLimit"
            v-model:ignore-no-test-value="ignoreNoTestValue"
            v-model:data-only-bin1="dataOnlyBin1"
            v-model:only-fail-test-item="onlyFailTestItem"
            v-model:only-low-cpk="onlyLowCpk"
            v-model:outlier-handling="outlierHandling"
            v-model:iqr-multiplier="iqrMultiplier"
          />
        </div>
      </div>
    </template>
```

左栏 `<template #left-panel>` 内删除整个 `<DataFilterSection scope="correlation" ... />` 块（CorrelationToolsTab.vue:17-26）。

- [ ] **Step 2.2: 追加 control-panel 样式**

`<style scoped>` 内追加（与 SingleParamTab 同款两行结构）：

```css
/* 顶部控件面板：两行（文件行 + 筛选行），嵌在共享 toolbar 盒内 */
.control-panel {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.control-panel__main {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.control-panel__main > .dp-analysis-filepicker {
  flex: 1;
  min-width: 240px;
}
.control-panel__filters {
  border-top: 1px dashed var(--border-2, #e4e7ed);
  padding-top: 8px;
}
```

- [ ] **Step 2.3: 行数检查**

```bash
grep -c "" frontend/src/pages/analysis/components/CorrelationToolsTab.vue
```

预期：≤600（原 514，删左栏块 + 增 toolbar/样式，预计 ~530）。

- [ ] **Step 2.4: 类型门禁**

```bash
cd frontend && npm run build
```

预期：BUILD 成功。

- [ ] **Step 2.5: e2e 回归（相关性 + 筛选传播）**

```bash
cd frontend && npx playwright test e2e/analysis/multi-file-filter.spec.ts e2e/analysis/iqr-multiplier-propagation.spec.ts e2e/analysis/tab-independent-files.spec.ts --project=P1
```

预期：全 PASS——`filterControl` 的 `.el-tab-pane:visible [data-filter=…]` 定位层级无关，相关性筛选挪位置不影响（9-05 契约设计兑现）。

- [ ] **Step 2.6: commit（先向用户确认）**

```bash
git add frontend/src/pages/analysis/components/CorrelationToolsTab.vue
git commit -m "refactor(analysis): 相关性 tab 数据筛选从左栏卡片移入 toolbar 第二行 bar（对齐单文件）"
```

---

## Task 3: 晶圆图 tab——文件选择移入顶部 toolbar 盒（无筛选行）

**Files:**
- Modify: `frontend/src/pages/analysis/components/WaferMapPanel.vue:3-19`（模板第一段）

- [ ] **Step 3.1: 模板改造**

原第一段：

```html
    <!-- 本 tab 自己选文件：与单文件分析/相关性/多文件四个 tab 互不影响 -->
    <el-row :gutter="12" style="margin-bottom: 10px" align="middle">
      <el-col :span="10">
        <AnalysisFilePicker
          v-model="fileId"
          :files="files"
          scope="wafer"
          :loading="listLoading"
        />
      </el-col>
      <el-col :span="14">
        <span class="wafer-note">
          本图按全部 die 的 Pass/Fail 判定，数据筛选不影响本图；
          可选参数取自直方图的测试项列表。
        </span>
      </el-col>
    </el-row>
```

替换为（toolbar 盒 = 共享 class；第二行原控件整体不动）：

```html
    <!-- 顶部 toolbar 盒：文件选择行（与单文件/相关性同位）。
         晶圆图不吃任何筛选（wafer_map 不读筛选字段），故无筛选行。 -->
    <div class="dp-analysis-toolbar wafer-toolbar">
      <AnalysisFilePicker
        v-model="fileId"
        :files="files"
        scope="wafer"
        :loading="listLoading"
      />
      <span class="wafer-note">
        本图按全部 die 的 Pass/Fail 判定，数据筛选不影响本图；
        可选参数取自直方图的测试项列表。
      </span>
    </div>
```

- [ ] **Step 3.2: 追加样式**

`<style scoped>` 追加：

```css
.wafer-toolbar {
  flex-wrap: wrap;
}
.wafer-toolbar > .dp-analysis-filepicker {
  flex: 0 0 360px;
  min-width: 240px;
}
```

- [ ] **Step 3.3: 类型门禁 + 晶圆图 e2e**

```bash
cd frontend && npm run build && npx playwright test e2e/analysis/wafermap-hidden-tab-init.spec.ts e2e/analysis/wafermap-model-not-found.spec.ts e2e/analysis/tab-independent-files.spec.ts --project=P1
```

预期：BUILD 成功、e2e 全 PASS（pickTabFile 用 `[data-file-picker="wafer"]` 定位，层级无关）。

- [ ] **Step 3.4: commit（先向用户确认）**

```bash
git add frontend/src/pages/analysis/components/WaferMapPanel.vue
git commit -m "refactor(analysis): 晶圆图文件选择移入顶部共享 toolbar 盒（不展示筛选）"
```

---

## Task 4: 多文件 tab——文件多选 + 筛选移入顶部 toolbar 盒

**Files:**
- Modify: `frontend/src/pages/analysis/components/MultiFileTab.vue:3-32`（左栏第一卡拆出）

- [ ] **Step 4.1: 模板改造**

`.multi-file-tab` 根内、`el-row.main-row` 之前插入 toolbar 盒：

```html
    <!-- 顶部 toolbar 盒：文件多选行 + 筛选行（对齐单文件两行结构）。
         敏感度仅作低 CPK 阈值（后端不消费裁剪口径），无「异常值处理」。 -->
    <div class="dp-analysis-toolbar multi-toolbar">
      <AnalysisFilePicker
        v-model="fileIds"
        :files="files"
        scope="multi"
        multiple
        label="数据文件 (最少 2 个)"
      />
      <DataFilterSection
        variant="bar"
        scope="multi"
        class="multi-toolbar__filters"
        v-model:ignore-no-limit="ignoreNoLimit"
        v-model:ignore-no-test-value="ignoreNoTestValue"
        v-model:data-only-bin1="dataOnlyBin1"
        v-model:only-fail-test-item="onlyFailTestItem"
        v-model:only-low-cpk="onlyLowCpk"
        v-model:iqr-multiplier="iqrMultiplier"
        :show-outlier="false"
      />
    </div>
```

说明：多文件 tab 不传 `loading`——文件列表是页面级拉取的、选择器常驻，无本 tab 参数请求加载态可显示。

左栏原第一卡（`el-card` 含 AnalysisFilePicker + custom-names）改为只留自定义图例名：

```html
        <el-card v-if="selectedFileObjs.length" shadow="hover" :body-style="{ padding: '12px' }">
          <div class="section-label">自定义图例名</div>
          <div v-for="f in selectedFileObjs" :key="f.id" class="name-row">
            <span class="name-dot" :style="{ background: colorOf(f.id) }" />
            <label :for="`file-name-${f.id}`" class="sr-only">{{ f.filename }} 图例名</label>
            <el-input
              :id="`file-name-${f.id}`"
              v-model="fileNames[f.id]"
              :placeholder="f.filename"
              size="small"
              clearable
            />
          </div>
        </el-card>
```

左栏原 `<DataFilterSection scope="multi" ... />` 块（MultiFileTab.vue:44-53）整体删除。

- [ ] **Step 4.2: 追加样式**

`<style scoped>` 追加：

```css
/* 顶部 toolbar 盒：多选行宽撑开，筛选行虚线分隔（对齐单文件 control-panel） */
.multi-toolbar {
  flex-wrap: wrap;
  align-items: flex-start;
  row-gap: 8px;
}
.multi-toolbar > .dp-analysis-filepicker {
  flex: 1 1 420px;
  min-width: 280px;
}
.multi-toolbar__filters {
  flex: 1 1 100%;
  border-top: 1px dashed var(--border-2, #e4e7ed);
  padding-top: 8px;
}
```

- [ ] **Step 4.3: 类型门禁 + 行数检查**

```bash
cd frontend && npm run build && grep -c "" src/pages/analysis/components/MultiFileTab.vue
```

预期：BUILD 成功；行数 ≤600（原 445，预计 ~460）。

- [ ] **Step 4.4: 迁移 7 处存量 spec 的左栏层级定位器**

以下位置统一把 `page.locator('<TAB> .left-panel .el-select').first()` 改为契约定位 `filePicker(page, 'multi')`（从 `../helpers/params` 导入，多数 spec 已导入其他 helper）：

1. `file-select.spec.ts:102`（`const select = page.locator(`${TAB} .left-panel .el-select`).first()` → `const select = filePicker(page, 'multi')`；文件头已 import `filePicker`）
2. `file-select.spec.ts:134`（同上）
3. `multi-file.spec.ts:30`（pickFiles 函数内；`TAB` 为 `.multi-file-tab`）
4. `multi-file-filter.spec.ts:26`（openMultiFile 内）
5. `histogram-multiseries-clip.spec.ts:109`
6. `legend-color.spec.ts:66`
7. `axis-label-precision.spec.ts:259`
8. `tab-request-fanout.spec.ts:54`

每处注意：原 `.el-select` 定位后代码用 `select.locator('input').first()` 输入过滤——`filePicker` 返回的根 div 内同样含 input（AnalysisFilePicker 根即该 div），下游代码不变。`file-select.spec.ts` 两处 import 已含 `filePicker`；其余 spec 需在 import 行补 `filePicker`。

- [ ] **Step 4.5: 多文件全链路 e2e**

```bash
cd frontend && npx playwright test e2e/analysis/multi-file.spec.ts e2e/analysis/multi-file-filter.spec.ts e2e/analysis/file-select.spec.ts e2e/analysis/legend-color.spec.ts e2e/analysis/histogram-multiseries-clip.spec.ts e2e/analysis/tab-request-fanout.spec.ts e2e/analysis/axis-label-precision.spec.ts --project=P1
```

预期：全 PASS。

- [ ] **Step 4.6: commit（先向用户确认）**

```bash
git add frontend/src/pages/analysis/components/MultiFileTab.vue frontend/e2e/analysis/file-select.spec.ts frontend/e2e/analysis/multi-file.spec.ts frontend/e2e/analysis/multi-file-filter.spec.ts frontend/e2e/analysis/histogram-multiseries-clip.spec.ts frontend/e2e/analysis/legend-color.spec.ts frontend/e2e/analysis/axis-label-precision.spec.ts frontend/e2e/analysis/tab-request-fanout.spec.ts
git commit -m "refactor(analysis): 多文件 tab 文件多选+筛选移入顶部 toolbar 盒；e2e 左栏层级定位迁契约属性"
```

---

## Task 5: 新增 e2e 断言（toolbar 形态契约）

**Files:**
- Modify: `frontend/e2e/analysis/tab-independent-files.spec.ts`（首测内追加断言）

- [ ] **Step 5.1: 在「页头不再有全局控件」用例内追加结构断言**

在 `await expect(filterControl(page, 'outlier-handling')).toBeVisible()` 之后追加：

```ts
    // 2026-09-07 统一 toolbar：单文件 tab 的筛选 bar 与文件选择同在顶部工具栏；
    // 晶圆图不吃筛选（wafer_map 不读筛选字段）→ 数据筛选不应出现在晶圆图 pane。
    // （相关性/多文件 tab 为 lazy 挂载，未访问时不在 DOM，须访问后再断言。）
    await page.getByRole('tab', { name: /晶圆图/ }).click()
    const waferPane = page.getByRole('tabpanel', { name: /晶圆图/ })
    await expect(filePicker(page, 'wafer')).toBeVisible({ timeout: 20_000 })
    await expect(waferPane.locator('[data-filter]')).toHaveCount(0)
```

并在文件末尾（describe 内）追加独立用例：

```ts
  test('相关性/多文件 tab 的筛选 bar 在顶部 toolbar 内（非左栏卡片）', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await page.getByRole('tab', { name: /相关性对比/ }).click()
    await expect(filePicker(page, 'correlation')).toBeVisible({ timeout: 20_000 })
    // lazy 挂载后筛选控件可见，且其祖先链上存在 .dp-analysis-toolbar（顶部工具栏）
    const corrFilter = filterControl(page, 'data-only-bin1')
    await expect(corrFilter).toBeVisible({ timeout: 20_000 })
    await expect(corrFilter.locator('xpath=ancestor::div[contains(@class,"dp-analysis-toolbar")]')).toHaveCount(1)

    await page.getByRole('tab', { name: /多文件分析/ }).click()
    await expect(filePicker(page, 'multi')).toBeVisible({ timeout: 20_000 })
    const multiFilter = filterControl(page, 'data-only-bin1')
    await expect(multiFilter).toBeVisible({ timeout: 20_000 })
    await expect(multiFilter.locator('xpath=ancestor::div[contains(@class,"dp-analysis-toolbar")]')).toHaveCount(1)
  })
```

注意：单文件 tab 的筛选 bar 也在 `.dp-analysis-toolbar` 内（AnalysisTabLayout .toolbar 挂了共享 class），此用例同时钉住「三 tab 筛选同在顶部工具栏」形态。

- [ ] **Step 5.2: 跑该 spec**

```bash
cd frontend && npx playwright test e2e/analysis/tab-independent-files.spec.ts --project=P1
```

预期：全 PASS（原 5 用例 + 新 1 用例）。

- [ ] **Step 5.3: commit（先向用户确认）**

```bash
git add frontend/e2e/analysis/tab-independent-files.spec.ts
git commit -m "test(e2e): 断言四 tab 文件选择/筛选 bar 的顶部工具栏形态契约（晶圆图无筛选）"
```

---

## Task 6: 全量回归 + 手动双主题验证 + 收尾

- [ ] **Step 6.1: 前端全量类型门禁**

```bash
cd frontend && npm run build
```

预期：BUILD 成功。

- [ ] **Step 6.2: 分析页全量 e2e**

```bash
cd frontend && npx playwright test e2e/analysis --project=P1
```

预期：全 PASS 或仅存量 flake（对照 master 基线判定，R2③）。

- [ ] **Step 6.3: 释放端口**

```bash
netstat -ano | grep -E ":(8000|3000|45678)" | grep LISTEN
```

预期：e2e 自起进程已退出；若有残留监听（非用户 dev vite），向用户确认后 kill。

- [ ] **Step 6.4: 手动浏览器双主题验证（CLAUDE.md 硬性要求）**

dev 服务下四 tab 逐个走查：
- 单文件：两行 toolbar 不变（回归确认）
- 晶圆图：顶部盒内文件选择 + 说明文字；第二行控件原位；无筛选行；加载晶圆图正常出图
- 相关性：toolbar 两行；筛选开关点击仍触发散点/矩阵重算；左栏 5 卡不挤
- 多文件：顶部多选 + 筛选；勾 2 文件参数列表加载；图例名卡仍在左栏且可编辑
- dark/light 切换各看一遍：toolbar 盒背景/边框/虚线分隔双主题正常
- 用 browser-use MCP 或用户手动走查均可，截图留档 `test/screenshots_night/`（如适用）

- [ ] **Step 6.5: 更新 docs/tasks/todo.md（review 部分）+ lessons（如有新坑）**

todo.md 追加本次任务记录与结果；若 Step 6.2 出现新坑（如 popper 定位在 toolbar 内的意外行为），按「现象→根因→修复/规则」追加 lessons.md。

- [ ] **Step 6.6: 最终 commit（先向用户确认）**

```bash
git add docs/tasks/todo.md docs/tasks/lessons.md
git commit -m "docs(tasks): 四 tab 文件选择/筛选统一 toolbar 改造任务记录"
```

---

## 验收清单（对照 spec）

- [ ] 相关性筛选在 toolbar 第二行 bar 内联，左栏无 DataFilterSection 卡片
- [ ] 晶圆图顶部共享 toolbar 盒含文件选择，无任何筛选 UI
- [ ] 多文件顶部 toolbar 盒含多选 + 6 项筛选 bar（无异常值处理），左栏图例名卡保留
- [ ] 单文件 tab 视觉零变化（标杆回归）
- [ ] data-file-picker / data-filter / popper-class 契约零变化
- [ ] 7+1 处存量 spec 定位器迁移完成，全量 e2e 通过
- [ ] `npm run build` 通过；行数全部 ≤600
- [ ] dark/light 双主题走查通过
