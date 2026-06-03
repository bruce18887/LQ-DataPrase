# Lessons Learned

## 后端重构 — views.py 按职责拆分

- **问题**: analysis/views.py 1383 行，gage/views.py 638 行，buyoff/views.py 482 行，export/views.py 525 行。一个文件混了请求解析、业务逻辑、Excel 布局三种职责。
- **方案**: 薄 View（请求解析+响应组装）+ Service（纯业务逻辑）+ Layout Builder（Excel/PPTX 构建）。平均 views.py 从 757→288 行（-62%）。
- **模式参考**: `apps/accounts/views.py`（178 行，clean DRF）+ `apps/datafiles/services.py`（服务层模式）+ `apps/export/excelize_helpers.py`（共享样式）。已有良好模式先例。
- **Rule**: views.py 超过 300 行时，应检查是否混入了非 HTTP 层的业务逻辑或格式化代码，按"View → Service → Builder"三层分离。
- **Rule**: 导出类功能使用 excelize 库（Go 绑定），不要回退到 openpyxl。
- **Rule**: 提取函数时要验证 return dict key 完全匹配，特别是 stat key 这种长列表。

## Excel 导出 — DataFrame 索引与 enumerate 不匹配

- **Bug**: `to_excel` 中 `detect_fail_data()` 返回原始 DataFrame 索引（如 `{5, 12, 30}`），但写入 Excel 的循环用 `enumerate` 生成 `0,1,2,...` 连续索引。经过 site/passfail 过滤后，DataFrame 索引不连续，导致 `r_idx in fail_set` 永远为 False，所有标红失效。
- **Fix**: 在 `detect_fail_data()` 前调用 `export_df.reset_index(drop=True)` 保证索引连续。
- **Rule**: 任何时候对 DataFrame 做行过滤（site、passfail），之后需要重置索引才能用 `enumerate` 访问。

## Excel 导出 — 空字符串过滤器清空数据（"只有列名没有数据"）

- **Bug**: 前端 `DataBrowser.vue` 的 `passfail`/`siteFilter` 默认值是空字符串 `''`（未选择），但后端 `to_excel` 的判断是 `if site_filter != '全部':`。`'' != '全部'` 为 True，于是按 `site == ''` 过滤 → 没有任何行匹配 → `export_df` 变 0 行 → 导出只有表头、无数据。`export_to_xlsx_optimized` 本身完全正常。
- **复现/验证**: `test/test_excel_highlight_export.py` 直接调用导出函数读回 xlsx 校验行数；复刻 view 过滤逻辑证明 `site_filter=''` → 0 行，`'全部'` → 2301 行。
- **Fix**: 守卫真值——`if site_filter and site_filter != '全部':`、`if passfail and passfail != '全部':`，并把 passfail 的 `else` 改成显式 `elif passfail == 'Pass':`，避免空串落入 Pass 分支。
- **Rule**: 后端 `request.data.get(k, default)` 的 default 只在键缺失时生效；前端若显式发送空串，default 不会触发。哨兵值判断必须先做真值守卫（`if v and v != SENTINEL`），不能假设"非哨兵=有效过滤"。
- **Rule**: 导出/过滤类 bug 必须读回产物（openpyxl 读 xlsx）断言真实行数，不能只看函数返回非空 bytes。

## UPH 端点 — 前端已建、后端缺失（404）

- **Bug**: `GET/POST /api/v1/analysis/uph/` 返回 404。前端 `UphCard.vue` + `analysisApi.getUph` 已存在并约定了响应结构，但 `AnalysisViewSet` 没有 `uph` action，`statistics.py` 也没有 `compute_uph`。旧项目无此功能（全新特性）。
- **Fix**: 在 `statistics.py` 实现 `compute_uph`（并行站点吞吐模型：`UPH = 3600 × site_count / avg_test_time_sec`），在 `AnalysisViewSet` 加 `uph` action。
- **关键数据细节**: 各格式测试时间列名不同——CTA8290D=`Test_Time`(秒)、ETS88=`Test Time`(ms)、STS8200=`T_TIME`(ms)。必须按 `metadata['units']` 判断 `ms`→÷1000 归一到秒。ETS88 的 Site 列混入日期字符串，需 `pd.to_numeric(...).dropna()` 过滤。
- **Rule**: 前端有 API 调用 + 类型接口但后端 404 时，先确认是"缺端点"还是"缺整个功能"。缺功能要按前端 interface 字段反推后端响应结构，逐字段实现。
- **Rule**: 涉及多格式的统计计算，必须用真实文件逐格式验证数值合理性（FT ~1600/ETS ~728/CP ~25673 UPH），并跑一次 `APIRequestFactory + force_authenticate` 的全链路 200 校验，不能只验证 URL 能 resolve。

## Buyoff — 角色分配未传到后端

- **Bug**: 前端有 FT/QA1/QA2 角色选择 UI，但 `generateForm` 只发了 `file_ids` 数组。后端按数组顺序分配角色，若用户跳过一个角色（如只选 QA1、QA2），角色映射错乱。
- **Fix**: 前端发送 `role_map` 字典（`{"FT": 123, "QA1": 456}`），后端优先使用。
- **Rule**: 前后端接口要传递完整语义，不能依赖隐式顺序。

## Sigma Limit — 缺少旧版配色

- **Bug**: 新端点只输出纯文本数据，缺少旧版的蓝色背景（原 Limit）、红色/黄色（Sigma 对比）配色。
- **Fix**: 补上条件填充逻辑。
- **Rule**: 移植功能时要同步视觉细节，不能只移植数据逻辑。

## E2E / Playwright 测试框架

- **L1 选择器作用域冲突**: `getByRole('link', { name })` 会同时命中侧边栏菜单与 Topbar 面包屑（strict-mode 报错）。规则：侧边栏断言一律限定 `page.locator('aside.sidebar')`，已封装 `sidebarLink()`。
- **L2 storageState 只恢复 token、不恢复身份**: `App.vue` 仅 `<router-view>`，启动不调 `/auth/profile/`，`user` 仅 `login()` 时写内存。注入 token 能过路由守卫但 `isAdmin=false`、Topbar 用户名空。规则：角色相关用例清空 storageState 后用 `loginAs()` 实时登录，同会话内不刷新。
- **L3 全局 401 拦截器吞登录错误**: `api/index.ts` 对任意 401 都 `window.location.href='/login'`，错误密码登录会整页跳转，`LoginPage` 内联 `error-msg` 来不及渲染。规则：错误密码用例断言“停留 /login + token 为空”。
- **L4 后端依赖缺失阻断 webServer**: `apps/export/export_ppt.py` 顶层 `import matplotlib`，缺失则 Django 无法启动。规则：跑 E2E 前确保 `.venv` 装好 `requirements/base.txt`。
- **L5 登录按钮文案含空格**: `LoginPage.vue` 渲染「登 录」。用 `button.neon-button` 比文本匹配更稳。

## 性能审计 — Django 后端优化模式

- **缓存已在位**: `apps/datafiles/services.py` 已有 `@lru_cache(maxsize=64)` 的 `get_cached_parsed_file`，所有 views 已使用。审计时需先检查缓存是否存在，不必假设缺失。
- **DataBrowserView 分页优化**: 之前模式是 `df.to_dict(orient='records')` 转全部行 → Python 过滤 → 切片。优化为：pandas 级别过滤 → `df.iloc[start:end]` 切片 → 仅对分页行 `to_dict()`。大文件从 O(N) 降为 O(page_size)。
- **DataBrowserView bug**: `parser.get_bin_column_name()` 引用了未定义的 `parser`。修复：在方法内 `parser = get_parser(datafile.format_type)` 显式实例化。
- **废弃代码模式**: 同名的 `@action` 方法在 ViewSet 中，后面的定义会覆盖前面的。Python 类方法覆盖规则导致 ~400 行死代码。grep `"^def " | sort | uniq -d` 快速定位。
- **clean_data NaN 处理**: 递归遍历响应树把所有 NaN 替换为 0.0 会掩盖数据问题。改为 `return None`（JSON null），让前端感知缺失值。但更优方案是在 pandas 源头做 `.replace({np.nan: None})`。
- **Rule**: DRF `request.data` vs `request.query_params` — `request.data` 只在 POST/PUT/PATCH body 中有值。端点为 GET 时所有参数必须用 `request.query_params.get()` 或 `.getlist()`（Django QueryDict 支持重复 key 传列表）。
