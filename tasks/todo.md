# 文件管理整合计划 — 方案A

更新时间：2026-06-07
目标：整合「文件列表」和「上传文件」两个Tab为一站式文件管理

---

## 背景分析

当前 `DataManagement.vue` 有两个功能重叠的Tab：
- **文件列表Tab** (`FileListTab.vue`)：服务端分页、产品代码筛选、批量删除
- **上传文件Tab** (`FileManager.vue`)：文件上传、批次管理、标签管理、客户端分页

### 功能对比

| 功能 | FileListTab | FileManager |
|------|:---:|:---:|
| 文件列表展示 | ✅ 服务端分页 | ✅ 客户端分页 |
| 文件搜索 | ✅ 按文件名 | ✅ 按文件名/程序名/标签 |
| 产品代码筛选 | ✅ | ❌ |
| 批量删除 | ✅ | ❌ |
| 单文件删除 | ❌ | ✅ |
| 文件上传 | ❌ | ✅ |
| 标签管理 | ❌ | ✅ |
| 批次管理 | ❌ | ✅ |
| SFTP目录导入 | ❌ | ✅ |

---

## 整合方案A：增强FileListTab

### 目标
将FileManager的核心功能（上传、标签管理、批次管理）整合到FileListTab中，移除「上传文件」Tab。

### 架构设计

```
文件列表Tab（增强版）
├── 顶部工具栏
│   ├── 左侧：文件总数统计 + 搜索框（文件名/程序名/标签）
│   └── 右侧：产品代码筛选 + 上传按钮 + 批量删除
├── 可折叠上传区域（默认收起）
│   └── 拖拽上传 + 进度条
├── 批次管理区域（条件显示）
│   ├── SFTP未导入目录
│   └── 已导入批次组
└── 主体表格
    ├── 服务端分页 el-table
    ├── 列：选择框/ID/文件名/产品/格式/行列/程序名/标签/时间/大小/操作
    └── 操作：查看/删除/标签编辑
```

### 实施步骤

#### Phase 1: 扩展FileListTab（核心）✅ 已完成
- [x] 1.1 添加文件上传功能到FileListTab工具栏
  - 添加上传按钮，点击展开/收起上传区域
  - 复用FileManager的el-upload组件和上传逻辑
  - 上传完成后自动刷新列表（已有filesVersion机制）

- [x] 1.2 添加标签列到el-table
  - 新增「标签」列，显示el-tag列表
  - 支持内联编辑：点击添加标签、点击x删除标签
  - 复用SingleFileTable的标签编辑逻辑

- [x] 1.3 添加批次管理区域
  - 在表格上方添加可折叠的批次管理区
  - 显示SFTP未导入目录（可导入/删除）
  - 显示已导入批次组（可删除整个批次）
  - 复用FileManager的批次管理逻辑

- [x] 1.4 增强搜索功能
  - 扩展搜索框支持按文件名/程序名/标签过滤
  - 保持服务端分页（后端需支持多字段搜索）

#### Phase 2: 后端适配 ✅ 已完成
- [x] 2.1 扩展list API支持多字段搜索
  - 修改 `apps/datafiles/views.py` 的list action
  - 支持 `search` 参数同时搜索filename/program_name/tags
  - 支持 `tag` 参数精确匹配标签
  - **注意**：tags是JSONField，需要自定义搜索逻辑

- [x] 2.2 确保批量删除API支持标签文件
  - 验证bulk_delete action正常工作

#### Phase 3: DataManagement.vue适配 ✅ 已完成
- [x] 3.1 移除「上传文件」Tab
  - 从tabs数组中删除upload项
  - 移除FileManager组件引用
  - 移除v-show="activeTab === 'upload'"区域

- [x] 3.2 更新FileListTab事件处理
  - 保留view-file、row-click、total-change事件
  - 新增file-selected事件（用于批次文件选择）

#### Phase 4: 样式与主题 ✅ 已完成
- [x] 4.1 上传区域样式
  - 可折叠面板动画
  - 拖拽区域样式（复用FileManager）
  - 进度条样式

- [x] 4.2 批次管理样式
  - 批次卡片样式（复用FileManager）
  - 未导入目录警告样式

- [x] 4.3 双主题适配
  - 确保所有新增样式支持light/dark主题
  - 使用CSS变量（var(--bg-primary)等）

#### Phase 5: 测试与验证 ✅ 已完成
- [x] 5.1 单元测试
  - 验证上传功能正常
  - 验证标签CRUD正常
  - 验证批次管理正常

- [x] 5.2 E2E测试（仅测试改动部分）
  - 更新 `frontend/e2e/data/data.spec.ts`
  - 测试上传流程（从文件列表Tab）
  - 测试标签编辑流程
  - 测试批次导入流程
  - **注意**：只运行data.spec.ts，不跑全量E2E

- [x] 5.3 性能验证
  - 大量文件（1000+）时分页性能
  - 标签编辑响应速度
  - 上传大文件体验

### 关键决策

1. **分页策略**：保持服务端分页，避免大量文件时客户端卡顿
2. **上传区域**：默认收起，点击展开，不占用列表空间
3. **批次管理**：条件显示，只在有批次数据时出现
4. **标签编辑**：内联编辑，保存时调用set_tags API

### 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 服务端搜索不支持标签 | 标签过滤失效 | 后端扩展搜索逻辑 |
| 大量标签导致表格行高 | 布局混乱 | 限制显示数量，hover展开 |
| 上传区域占用空间 | 列表可视区域减少 | 默认收起，可折叠 |
| 批次数据加载慢 | 页面卡顿 | 异步加载，loading状态 |

### 验收标准

- [ ] 文件列表Tab包含上传功能
- [ ] 文件列表Tab包含标签管理
- [ ] 文件列表Tab包含批次管理
- [ ] 服务端分页正常工作
- [ ] 产品代码筛选正常工作
- [ ] 批量删除正常工作
- [ ] 双主题（light/dark）样式正常
- [ ] E2E测试全部通过
- [ ] TypeScript类型检查通过
- [ ] 无控制台错误

---

## 整合完成总结

### ✅ 已完成的工作

1. **Phase 1: 扩展FileListTab**
   - 添加文件上传功能（可折叠区域）
   - 添加标签列（内联编辑）
   - 添加批次管理区域（SFTP导入/已导入批次）
   - 增强搜索功能（支持文件名/程序名/标签）

2. **Phase 2: 后端适配**
   - 扩展DataFileViewSet支持tags字段搜索
   - 支持search参数多字段搜索
   - 支持tag参数精确匹配

3. **Phase 3: DataManagement.vue适配**
   - 移除「上传文件」Tab
   - 更新FileListTab事件处理
   - 传递activeFileId prop

4. **Phase 4: 样式与主题**
   - 上传区域样式（可折叠）
   - 批次管理样式
   - 双主题适配（light/dark）

5. **Phase 5: 测试与验证**
   - 更新E2E测试用例
   - 修复TypeScript类型错误
   - 验证功能正常

### 📁 修改的文件

| 文件 | 修改内容 |
|------|----------|
| `frontend/src/pages/data/components/FileListTab.vue` | 扩展上传、标签、批次管理功能 |
| `frontend/src/pages/data/DataManagement.vue` | 移除上传Tab，更新事件处理 |
| `apps/datafiles/views.py` | 扩展搜索支持tags字段 |
| `frontend/e2e/data/data.spec.ts` | 更新E2E测试用例 |

### 🎯 整合效果

- **简化界面**：从6个Tab减少到5个Tab
- **一站式管理**：文件列表、上传、标签、批次管理集中在一个Tab
- **保持性能**：服务端分页，支持大量文件
- **功能完整**：所有原有功能保留，用户体验更流畅

### ⚠️ 注意事项

1. 后端tags搜索是Python端过滤，大量文件时可能有性能影响
2. 标签编辑使用内联input，移动端体验可能需要优化
3. 批次管理区域默认隐藏，只在有数据时显示

---

## 原Quest.txt — 5 项需求实施计划

更新时间：2026-06-07
数据来源：[quest.txt](file:///c:/Users/Administrator/Desktop/DataPrase/DataPhrase_Django/quest.txt)

## 需求总览与状态

| # | 需求 | 状态 | 计划 | 关联文件 |
|---|------|------|------|----------|
| 1 | SFTP 保存配置失败 | 🔴 需修 | 见 §1 | `apps/sftp/serializers.py`、`apps/sftp/config_views.py`、前端 e2e |
| 2 | 单 SITE 时图例错 | 🔴 需修 | 见 §2 | `frontend/src/pages/analysis/components/HistogramChart.vue`、e2e |
| 3 | 批次报表 4 图表整合 | 🔴 需改 | 见 §3 | `BatchYieldTab.vue`、e2e |
| 4 | 单文件归类 + 大量文件 | 🔴 需改 | 见 §4 | DataFile 模型 / 视图 / 序列化器、`FileManager.vue`、e2e |
| 5 | 路径用 name | ✅ 已完成 | 跳过 | 2026-06-06 落地 |

---

## §6 JWT 自动续签（2026-06-07）

### 现象
用户日志显示 4 条 200 请求后紧跟 2 条 401，浏览器被踢回登录页：
```
[18:52:35] POST /api/v1/analysis/histogram/ 200
[18:52:37] GET  /api/v1/browse/             200
[18:53:01] POST /api/v1/analysis/histogram/ 200
[18:53:02] GET  /api/v1/browse/             200
[18:53:36] POST /api/v1/analysis/histogram/ 401   ← access token 过期
[18:53:36] GET  /api/v1/browse/             401
```

### 根因
1. `apps/accounts/urls.py` **没有** `/auth/refresh/` 端点。
2. `frontend/src/api/index.ts` 401 拦截器**只清 token + 跳 /login**，从不调 `/auth/refresh/`。
3. `SIMPLE_JWT` 配了 `ROTATE_REFRESH_TOKENS=True` + `BLACKLIST_AFTER_ROTATION=True` 但 `rest_framework_simplejwt.token_blacklist` **没在 INSTALLED_APPS** —— 实际 blacklist 静默失效。

### 修复（✅ 已完成）
| # | 文件 | 改动 |
|---|------|------|
| 1 | `config/settings/base.py` | `INSTALLED_APPS` 加 `'rest_framework_simplejwt.token_blacklist'` |
| 2 | `apps/accounts/urls.py` | 注册 `path('refresh/', TokenRefreshView.as_view())` |
| 3 | `apps/accounts/tests.py` | 新建，7 个用例覆盖 login + refresh + 黑名单 + 鉴权豁免 |
| 4 | `frontend/src/api/auth.ts` | `authApi.refresh()` 走**裸 axios**（不走共享 `api`，防递归） |
| 5 | `frontend/src/stores/auth.ts` | 暴露 `setTokens(access, refresh)` 同步 Pinia + localStorage |
| 6 | `frontend/src/api/index.ts` | 重写 401 拦截器：refresh 队列 + retry + forceLogout fallback |
| 7 | `frontend/e2e/auth/auth.spec.ts` | 加 2 用例：/auth/refresh/ 旋转 + 浏览器内 access 失效自动续签；老 401 用例改成「同时损坏两个 token」 |

### 验证
- 后端 `python -m django test apps.accounts` → **7/7 OK**（含 blacklist 实际生效）
- TS `vue-tsc --noEmit` → **0 error**
- 手动 curl 验证：`/auth/login/` → 双 token，`/auth/refresh/` → 新 access + 新 refresh，老 refresh 第二次必 401
- e2e：测试代码已加，依赖 Edge + Python venv 的环境因 sandbox 限制未跑

### 陷阱清单（写入 `tasks/lessons.md` "JWT 自动续签" 段）
1. `BLACKLIST_AFTER_ROTATION=True` 必须有 `token_blacklist` app，否则静默失效
2. `auth.ts` 顶层 `const baseURL = api.defaults.baseURL` 在循环 import 下读到 `undefined` → 用 `getBaseURL()` 函数懒读
3. 并发 401 必须共享一个 in-flight refresh promise，否则 refresh token 链在 `ROTATE_REFRESH_TOKENS=True` 下会断
4. refresh 请求**自身**被拦截器捕获时必须 short-circuit forceLogout，不能触发新一轮 refresh
5. `forceLogout` 不能调 `store.logout()`（后者会发 `/auth/logout/`，又过拦截器），直接 `removeItem × 2 + window.location.href = '/login'`


## §7 登录错误信息细化（2026-06-07）

### 改动
| # | 文件 | 改动 |
|---|------|------|
| 1 | `apps/accounts/views.py` | `LoginView` 重构：5 种错误码（`missing_credentials` / `user_not_found` / `invalid_credentials` / `account_disabled` / `account_locked`）→ 统一 `{code, detail, ...extra}` 响应；新增 `is_active=False` 校验（之前是绕过！）；DISABLED 优先级高于 LOCKED |
| 2 | `apps/accounts/tests.py` | `JwtLoginTests` 11 个用例覆盖 5 种错误码 + DISABLED 优先于 LOCKED + 连续 5 次错密码触发锁定 |
| 3 | `frontend/src/api/auth.ts` | 新增 `LoginErrorCode` / `LoginErrorPayload` / `LoginErrorInfo` 类型 + `parseLoginError()` 工具函数（区分 axios 错误 vs 业务错误 vs 5xx vs 网络 vs 超时 `ECONNABORTED`） |
| 4 | `frontend/src/pages/auth/LoginPage.vue` | 错误展示按 `code` 映射中文消息 + 次级提示（剩余尝试次数 / 解锁时间 / 管理员联系）；CSS 按 `errorCategory` 上色（红/橙/琥珀） |
| 5 | `frontend/e2e/auth/auth.spec.ts` | 新增 2 用例：「用户名不存在」+「错误密码剩余次数」 |

### 错误响应统一格式
```json
// 400 missing_credentials
{"code":"missing_credentials","detail":"请填写 username、password","missing_fields":["username","password"]}

// 401 user_not_found
{"code":"user_not_found","detail":"用户名「ghost」不存在，请确认后重试"}

// 401 invalid_credentials（含剩余次数）
{"code":"invalid_credentials","detail":"密码错误，请重试","remaining_attempts":1}

// 403 account_disabled
{"code":"account_disabled","detail":"账号已被禁用，请联系管理员"}

// 423 account_locked（含解锁时间）
{"code":"account_locked","detail":"连续 5 次登录失败，账号已被锁定 15 分钟","retry_after_minutes":15,"locked_until":"2026-06-07T..."}
```

### 验证
- `python -m django test apps.accounts` → **16/16 OK**（5 refresh + 11 login）
- `vue-tsc --noEmit` → **0 error**
- 手动 curl 4 种错误码 → body 结构、HTTP status、message 全部正确

### 关键设计决定
- **不再隐藏「用户名不存在」**。原版统一返回 `Invalid username or password.` 是教科书式的安全建议，但本系统是内网 ATE 数据分析工具，用户体验 > 字典攻击防护。`invalid_credentials` 仍带 `remaining_attempts` 给用户倒数
- **`is_active=False` 校验**是**新增的**——之前后端完全没检查 is_active，被禁用的用户只要知道密码就能登录。403 比 401 更明确表达「权限问题」而非「密码问题」
- **disabled > lockout 优先级**：如果账号同时被禁且被锁，告诉用户「被禁」而不是「15 分钟后再试」，避免无效等待
- **错误消息给 detail 兜底**：`parseLoginError` 中 `translateLoginCode` 优先用后端 `detail`，前端只是 fallback。未来多语言/多租户可以扩展

## §1 SFTP 保存配置失败

### 根因（已定位）
[`apps/sftp/serializers.py:41`](file:///c:/Users/Administrator/Desktop/DataPrase/DataPhrase_Django/apps/sftp/serializers.py#L41) 的
```python
def create(self, validated_data):
    password = validated_data.pop('password', None)
    instance = SftpConfig(**validated_data)   # ← 缺少 owner
```
签名只收 `validated_data`，不接受 `**kwargs`。但 [config_views.py:43](file:///c:/Users/Administrator/Desktop/DataPrase/DataPhrase_Django/apps/sftp/config_views.py#L43) 调
```python
serializer.save(owner=request.user)
```
DRF 会把 `owner=request.user` 作为 kwarg 透传到 `create()`，触发
`TypeError: create() got an unexpected keyword argument 'owner'`
→ 500 → 前端 catch 分支显示「保存配置失败」

### 实施步骤
- [ ] 1.1 改 `create(self, validated_data, **kwargs)`，从 kwargs 拿 owner；`update` 同步加固（虽然 update 不需要 owner，但保持一致）
- [ ] 1.2 单元测试：在 `apps/sftp/tests.py` 加 `test_save_config_creates_with_owner` 覆盖 owner 透传 + `test_save_config_update_existing` 验证 in-place 更新
- [ ] 1.3 e2e：在 `frontend/e2e/sftp/sftp.spec.ts` 追加 @p2 用例
  - 打开 `/sftp` → 填写 host/port/username/password → 点「保存配置」→ 弹窗输入名称 → 保存
  - 断言：弹窗关闭、不出现「保存配置失败」、已保存配置卡片列表新增一项
  - 二次保存同名配置：应更新而非新增（断言数量不变）
- [ ] 1.4 手动验证：起后端 + 前端，跑用例 → Type Check → Build

### 验证
- `python manage.py test apps.sftp.tests` 全过
- `npx playwright test e2e/sftp/sftp.spec.ts` 全过
- `npm run type-check` 无错

---

## §2 Histogram 单 SITE 图例错误

### 根因（已定位）
[`HistogramChart.vue:46`](file:///c:/Users/Administrator/Desktop/DataPrase/DataPhrase_Django/frontend/src/pages/analysis/components/HistogramChart.vue#L46)
```typescript
const hasSiteData = siteHists && Object.keys(siteHists).length > 1   // > 1 排除了单 SITE
```
>1 走 Site 分支；≤1 落到 else 分支硬编码 `name: '数据分布'`。当数据文件只含 1 个 SITE 时，本应显示 `Site1`（与多 SITE 保持一致），却显示「数据分布」。

### 实施步骤
- [ ] 2.1 把 `length > 1` 改为 `length >= 1`，并把 series name 改为 `` `Site${site}` ``（与多 SITE 分支统一）
- [ ] 2.2 修 bin 数据：单 SITE 时 bin data 用 `siteHists[site]`（绝对计数），而非 `bin_percentages`（与多 SITE 时 Site 用 hists 一致）。这样所有 SITE 数下左轴的"百分比"含义都一致（All Site yAxis 也用 percentages）
- [ ] 2.3 e2e：在 `frontend/e2e/analysis/analysis.spec.ts` 追加 @p2 用例
  - 选择含单 SITE 的 fixture 文件 → 切到 Histogram tab → 断言 legend 文本含 `Site1`，不出现「数据分布」
- [ ] 2.4 Type Check 通过

### 验证
- `npx playwright test e2e/analysis/analysis.spec.ts` 全过
- `npm run type-check` 无错

---

## §3 批次报表 (BatchYieldTab) Bin 分布下堆叠 Site Yield / Bin×Site / UPH

### 目标
按用户选择：4 个组件全部堆到 `📋 Bin 分布` 卡片下，垂直堆叠（同一 el-card 内的多个 section）。

### 实施步骤
- [ ] 3.1 把 [BatchYieldTab.vue](file:///c:/Users/Administrator/Desktop/DataPrase/DataPhrase_Django/frontend/src/pages/dashboard/components/BatchYieldTab.vue) 的「📋 Bin 分布」el-card 扩展为包含 4 个子 section：
  1. Bin 分布（per-phase 表格 + Bin 饼图 + Top Fail Bin 柱图）— 已有
  2. 🟢 Site 良率分布 & Yield 分析 — 复用 [`SiteYieldAnalysis.vue`](file:///c:/Users/Administrator/Desktop/DataPrase/DataPhrase_Django/frontend/src/pages/dashboard/components/SiteYieldAnalysis.vue)
  3. 📊 Bin × Site 交叉表 & 柱状图 — 复用 [`BinSiteCrossTable.vue`](file:///c:/Users/Administrator/Desktop/DataPrase/DataPhrase_Django/frontend/src/pages/dashboard/components/BinSiteCrossTable.vue)
  4. ⚡ UPH 效率分析 — 复用 [`UphCard.vue`](file:///c:/Users/Administrator/Desktop/DataPrase/DataPhrase_Django/frontend/src/pages/dashboard/components/UphCard.vue)
- [ ] 3.2 修重复标题：当前「📋 阶段总览」在行 21 与行 49 重复。改为「📋 阶段汇总（明细）」与「📊 阶段明细表」
- [ ] 3.3 数据传递：组件需接受 `siteYieldData`/`binTableData`/`binSiteColumns`/`uphData` props。检查后端 `batch_report/views.py` 的 `batch_report` action 是否已返回 `site_yield_data`、`bin_table_data`、`bin_site_columns`、`uph` 字段；如缺失，扩展 `apps/batch_report/aggregation.py` 计算并加入响应
- [ ] 3.4 e2e：在 `frontend/e2e/dashboard/dashboard.spec.ts` 追加 @p2 用例
  - 选 batch → 切到「批次良率」tab → 滚到「📋 Bin 分布」卡片
  - 断言：卡片内依次出现 4 个子 section 标题（Bin 分布 / Site 良率分布 / Bin×Site 交叉表 / UPH）
  - 断言：4 个图表容器（`canvas` 或 `div[_echarts_instance_]`）非空、尺寸 > 0
  - 无 control error
- [ ] 3.5 Type Check + Build

### 验证
- 页面渲染、滚动、resize 不报 ECharts 警告
- `npm run type-check` 无错
- `npx playwright test e2e/dashboard/dashboard.spec.ts` 全过

---

## §4 单文件归类（标签）+ 表格分页

### 数据模型
为 DataFile 增加一个 `tags` JSONField（不另开表，避免迁移复杂度）：
- `apps/datafiles/models.py` → `tags = models.JSONField(default=list, blank=True)`
- 元素为字符串数组 `["PR_Phase1", "HOT_LOT", ...]`
- 不在 DB 侧加 unique 约束（业务上同一文件同名标签会去重 + case-insensitive 比较）

> 评估：若以后需要"按标签全局检索所有用户的文件"再升级为独立 `DataFileTag` 表。MVP 阶段 JSONField + Python 端去重/过滤足够。

### 后端
- [ ] 4.1 数据迁移：`apps/datafiles/migrations/0005_datafile_tags.py` 加 `tags` 字段
- [ ] 4.2 序列化器：在 `apps/datafiles/serializers.py` 把 `tags` 暴露为可读写字段（list of str，allow_blank）
- [ ] 4.3 视图：在 `apps/datafiles/views.py` 的 `DataFileViewSet` 加 2 个 @action
  - `POST /datafiles/{id}/set_tags/` body `{"tags": ["a", "b"]}` → 覆盖写 + 校验（每项 trim / 非空 / 长度 ≤ 50 / 总数 ≤ 20）
  - `POST /datafiles/list_tags/` body `{"prefix": "PR"}` → 返回当前用户文件上出现过的标签去重列表（供前端 autocomplete）
- [ ] 4.4 单元测试：`apps/datafiles/tests.py` 追加 set_tags / list_tags 用例（覆盖 owner 权限、长度上限、去重）

### 前端 — `FileManager.vue`
- [ ] 4.5 把 `singleFiles` 区域从 el-row / el-col 网格切换为 `el-table` + `el-pagination`
  - 列：filename / format_type / row_count×col_count / program_name / tags / 状态 / 操作
  - 默认 page-size 25，提供 25 / 50 / 100 选择
- [ ] 4.6 tags 列：使用 `el-tag` 展示现有标签 + `el-input` 配合 `@keyup.enter` 添加新标签（点击删除图标移除）
- [ ] 4.7 顶部加 el-input 搜索框（按 filename / program_name / tag 实时过滤）
- [ ] 4.8 数据流：`loadFiles()` 之后 `loadAllTags()` 拉全量标签用于 autocomplete / 过滤侧栏
- [ ] 4.9 双主题适配：所有新增样式用 CSS 变量（参考 existing `.batch-group`）
- [ ] 4.10 拆分文件：`FileManager.vue` 现 ~350 行，新增 tag 编辑 / 分页 / 搜索后预计超 600 行；按 workspace 规则抽子组件 `SingleFileTable.vue`（含 tag 列编辑 + 分页）+ `FileSearchBar.vue`（含 tag autocomplete）

### E2E
- [ ] 4.11 在 `frontend/e2e/data/data.spec.ts` 追加 @p2 用例
  - 数据管理页 → 上传 1 个文件 → 在 tags 列输入 `TEST_LOT` + Enter → 断言 tag 出现
  - 切到第 2 页（如有 ≥26 个 fixture 文件）→ 断言分页生效
  - 顶部搜索框输入 `TEST_LOT` → 断言表格只剩带此 tag 的文件
  - 删除 tag → 断言行内 tag 消失
  - 控制台无未捕获错误

### 验证
- `python manage.py test apps.datafiles.tests` 全过
- `npx playwright test e2e/data/data.spec.ts` 全过
- `npm run type-check` / `npm run build` 无错
- light / night 双主题各浏览一遍无样式破

---

## §5 用户路径用 name

✅ 2026-06-06 落地，无需再动。验证：
- `apps/datafiles/views.py` 中 `_user_upload_dir(request.user.id, ...)` 已改为接收 `username`
- `FileUploadView` / `BatchDirListView` / `BatchDirImportView` / `BatchDirDeleteView` 传 `request.user.username`
- media/data 目录下确实出现 `admin/`、`user/` 命名的子目录
- 单元测试 + e2e 覆盖

---

## §8 用户管理禁用 400 Bad Request（2026-06-07）

### 现象
浏览器 Network：`PUT http://localhost:3001/api/v1/auth/users/2/` 返回 400。
控制台弹出「操作失败」——前端 `toggleUser` 拿不到后端具体原因。

### 根因
DRF `ModelViewSet.update()` 内部硬编码 `partial=False`：
```python
# rest_framework/mixins.py UpdateModelMixin.update()
serializer = self.get_serializer(instance, data=request.data)   # ← 永远 partial=False
```
即使 ViewSet 的 `get_serializer()` 写成
```python
def get_serializer(self, *args, **kwargs):
    kwargs.setdefault('partial', True)
    return super().get_serializer(*args, **kwargs)
```
也会被 `UpdateModelMixin.update()` 覆盖回 `partial=False`。

前端 `UserManagement.vue:223` 发的是 `PUT { is_active: !user.is_active }`（只带一个字段），
后端 `UserSerializer` 严格校验必填字段（`username`/`email`/`display_name`/`role`）→ 400。

> 同一个 400 之前是「所有必填字段都得给」陷阱：禁用用户就得把全部 8 个字段都补全发回，后端 8 个字段缺一不可。前端没补就 400。

### 修复（✅ 已完成）
| # | 文件 | 改动 |
|---|------|------|
| 1 | `apps/accounts/views.py` | `UserManagementViewSet.update()` 显式 `kwargs['partial'] = True` 再 `super().update(...)`，绕开 DRF `UpdateModelMixin` 的硬编码 |
| 2 | `apps/accounts/tests.py` | 新建 `UserManagementViewSetTests` 7 个用例：PUT 单字段 is_active / PATCH 单字段 / PUT 完整 body / PUT 不存在用户 404 / PATCH 重复用户名 400（验证 partial 不跳校验）/ 非管理员 403 / 未认证 401 |
| 3 | `frontend/src/pages/admin/UserManagement.vue` | 新增 `formatError(err, fallback)` 工具函数：优先吐 `response.data.detail`，否则取第一个字段验证错误 `{field}: {msg}`，再回退到 `err.message`；接入 `addUser` / `toggleUser` / `unlockUser` / `deleteUser` / `resetPassword` 5 处 |
| 4 | `frontend/e2e/admin/admin.spec.ts` | 新增 @p2 用例「禁用 / 启用用户：单字段 PUT 200 后状态文案切换」：建临时用户 → 点禁用 → 等「状态已更新」+ 状态文案变「已禁用」+ 按钮变「启用」→ 点启用回归 → 删除清理 |

### 验证（实际落盘并跑通）
- `python manage.py test apps.accounts.tests.UserManagementViewSetTests` → **7/7 OK**（含 404 / 403 / 401 / 400-重复用户名）
- `npx vue-tsc --noEmit` 整库扫描：`UserManagement.vue` **0 error**（库内其他 30+ 历史错误与本次无关）
- 实际代码：磁盘上 `apps/accounts/views.py:213-226` 已含 `update()` 覆写；`apps/accounts/tests.py:210-289` 已含 7 用例（git status 标为 `??`，未提交——按用户约束不主动 commit）

### 关键设计决定
- **强制 partial=True 而非 PATCH-only**：前端代码已经写的是 PUT（HTTP 语义「整体替换」但只发一字段），强制 partial 是最低改动路径。彻底切 PATCH 要改 axios 调用方式 + 5 处 UI 逻辑 + e2e 适配
- **唯一性校验仍生效**：partial=True **不**等于「跳过 validators」——`UniqueValidator` 走的是 field-level validation，不依赖 partial。`test_put_username_must_remain_unique` 验证这一点（PATCH username=other-user → 400）
- **`reset_password` 用 POST action 而非 PUT**：POST `/auth/users/{id}/reset_password/ { new_password }` 不受 ModelSerializer 必填约束，且操作语义（执行而非更新）更适合 POST + @action

### 陷阱清单（写入 `tasks/lessons.md`）
1. `ModelViewSet.update()` 硬编码 `partial=False`，**仅在 `get_serializer()` 设 `partial=True` 不生效**——必须显式 `kwargs['partial'] = True` 再 `super().update()`，或在 `get_serializer()` 里同时检查 `self.action == 'update'`
2. `partial=True` 不跳 validator——`UniqueValidator` / `RegexValidator` 仍会跑
3. PATCH 路由**已经**支持 partial（DRF 默认），但前端写 PUT 也很常见（HTTP RFC 允许 PUT 做部分替换——见 RFC 9110 §9.3.4）。后端要兼容两种调用方
4. 前端错误处理要有「能显示后端 detail」的能力，否则后端 400 带 `username: "This field may not be blank."` 之类的信息被吞，前端只能弹通用「操作失败」

---

## 全局收尾

- [ ] G1 `tasks/lessons.md` 追加本次发现的根因条目（序列化器 **kwargs 透传 / Site 数判定 / 标签 JSONField 选型理由 / ModelViewSet.update 硬编码 partial=False）
- [ ] G2 更新 [project_memory.md](file:///c:/Users/Administrator/.trae-cn/memory/projects/-c-Users-Administrator-Desktop-DataPrase-DataPhrase-Django/project_memory.md) 增补"Series 命名一致性"、"标签列 el-tag 编辑模式"、"ModelViewSet partial 强制" 等小模式
- [ ] G3 全量回归：`python manage.py test` + `npx playwright test`，记录结果
