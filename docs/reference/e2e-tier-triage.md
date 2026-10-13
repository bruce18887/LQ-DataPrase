# e2e 用例分诊清单

判据定义见 `docs/superpowers/specs/2026-09-26-e2e-tier-and-affected-gate-design.md` 的「三层判据」节。
本清单是那条判据的**存量普查**：397 例逐条标层，用来定量「可下沉比例」而不是猜。

## 权威分母（`playwright test --list --reporter=json` 实测，2026-09-26）

397 例 / 74 文件（`--list` 报的 399 含 setup 项目 2 例）。按项目：Edge 15 · P0 15 · P1 228 · P2 141。

| 模块 | 文件 | 例数 | 占全量 | 单例成本 |
|---|---|---|---|---|
| analysis | 37 | 149 | 37.5% | ≈5.4 s（必须 `workers=1`） |
| data | 9 | 87 | 21.9% | ≈5.4 s |
| sftp | 4 | 38 | 9.6% | **≈20 s**（真连 paramiko SFTP，冷连接一次 ~22 s） |
| settings | 10 | 37 | 9.3% | ≈5.4 s |
| global | 4 | 21 | 5.3% | ≈5.4 s |
| dashboard | 1 | 14 | 3.5% | ≈5.4 s |
| auth | 1 | 13 | 3.3% | ≈5.4 s |
| exports | 2 | 11 | 2.8% | ≈5.4 s |
| batch | 2 | 7 | 1.8% | ≈5.4 s |
| theme | 1 | 6 | 1.5% | ≈5.4 s |
| smoke | 1 | 5 | 1.3% | ≈5.4 s |
| admin | 1 | 5 | 1.3% | ≈5.4 s |
| electron | 1 | 4 | 1.0% | ≈5.4 s |

下沉收益的排序应当是 **例数 × 单例成本**，所以 `sftp`（38 例但 20 s/例，约占全量墙钟的三分之一）
优先级高于 `analysis` 里那些 5 秒用例 —— 这一点在分诊开始前是反直觉的。

## 分诊进度：全部 397 例已分诊（6 个代理并行 + 主代理抽样复核）

行数口径：`playwright test --list --reporter=json` 的 397（参数化 `for` 展开按展开后的例计）。
六个切片之和 73+76+92+42+60+54 = 397 ✓ 与分母吻合。

| 档 | 例数 | 占比 | 处置含义 |
|---|---|---|---|
| T3 浏览器不可替代 | 163 | 41.1% | 留，无需动作 |
| T1+T3 混合 | 128 | 32.2% | 拆薄：数值判据下沉，e2e 留接线证明 |
| T1 纯后端可判 | 30 | 7.6% | 整条可搬 |
| T2 前端纯函数 | 25 | 6.3% | 整条可搬（其中仅少数零重构成本） |
| 待定（判据缺档） | 32 | 8.1% | **无处可落，需决策** |
| T1 已有后端覆盖（纯重复） | 9 | 2.3% | 直删，不需要新落点 |
| T0 陈旧/无判据 | 9 | 2.3% | 删或补强 |
| 工具型（@tool） | 1 | 0.3% | 不计回归 |

### 三个改变结论的数字

1. **「整条搬走/删掉」的上限 = 30 + 25 + 9 + 9 ≈ 73 例（18%）**，按 5.4 s/例只省约 6.6 分钟；
   而混合档 128 例（32%）拆薄**几乎不省墙钟** —— 单例成本由 `gotoApp` 冷启动、
   `waitForTimeout`、轮询等待决定，**不由断言数量决定**（`sftp/search.spec.ts` 18 例 ≈ 23 s/例，
   是平均值的 4 倍，差在 `connectAndOpenSearch` 的连接与轮询，不在断言条数）。
   → 拆薄混合例的价值是「判据落在对的层、后端能独立自证」，**不是提速**；想提速必须整条删或砍前置。
2. **32 例无处可落，三个代理各自独立撞到同一堵墙**：见下方「判据缺口」，需你决策后才能继续搬。
3. **成本集中度高于数量集中度**：`sftp` 38 例（9.6% 用例数）约占全量墙钟三分之一；
   `batch/batch.spec.ts` 6 例里有 4 例是死代码。按「例数 × 单例成本」排，
   性价比第一梯队是 **砍掉 sftp 版式 4 例的无用连接**（零判据损失，见 E1，**已做：112s→24s**）。

### 模块级汇总（其余 324 例）

| 切片 | 例数 | T1 | T1重复 | T2 | T3 | T0 | T1+T3 | 待定 |
|---|---|---|---|---|---|---|---|---|
| analysis 第 1–19 文件 | 73 | 2 | — | 12 | 28 | 0 | 22 | 9 |
| analysis 第 20–37 文件 | 76 | 1 | — | 0 | 40 | 1 | 24 | 10 |
| data + smoke | 92 | 24 | — | 2 | 27 | 1 | 26 | 12 |
| settings + admin | 42 | 2 | — | 4 | 7 | 1 | 27 | 1 |
| sftp + batch + exports + electron | 60 | 0 | 9 | 3 | 21 | 6 | 21 | 0 |
| auth + dashboard + global + theme | 54 | 1 | — | 4 | 40 | 0 | 8 | 0 |

纯 T3 的 163 例不逐条列行（处置是「留」，列出不产生决策）；它们集中在
`tab-independent-files`(7)、`view-data`(10)、`fonts`(6)、`night-visibility`(6)、`smoke/pages`(5)、
`dashboard`(11)、`dock-resize`(5)、`toolbar-sticky`(3)、`table-zoom-fit`(3)、`kde-curve`(3) 等文件，
判据形态为 canvas/SVG 出图、ag-grid 虚拟化、bbox 像素、双主题 computed style、pageerror 采集、
`data-*`/`aria-*` 契约本体。

## 可执行清单（本轮据此清理）

### A. 直删：零判据或纯重复，且**主代理已逐条核实**

| 目标 | 例 | 核实依据 |
|---|---|---|
| `analysis/boxplot-bool-params.spec.ts` 整文件 | 2 | 本轮已搬 `test/backend/test_boxplot_nonnumeric_params.py`（5 例 / 10 ms 实跑绿） |
| `batch/batch.spec.ts:39/62/95/170` 死 skip | 4 | `grep test.skip(` 实测 39/62/95 是 `test.skip('标题', …)` 形态（永久跳过），:170 判据是 `status<500` 永真；/batch 路由已重定向 |
| `analysis/sw-bin-qqplot-repro.spec.ts:51` 诊断脚本 | 1 | 我逐行核过：全例只有 1 条 `expect` = 切 tab 前置，其余是 `console.log` + `page.screenshot` 写盘 |

A 组的共同点：**删除不改变任何执行结果**（要么已 skip，要么判据已在更便宜的层成立且实跑过），
所以不需要一轮 e2e 来背书。

### B. 直删：T1 侧已存在同名后端用例（引用已核实存在）

| e2e 目标 | 后端对应用例（已 grep 确认存在） |
|---|---|
| `settings/export-timeout.spec.ts:70` 三个非法值 400 | `apps/accounts/tests.py:393/397/401` 三条同名 |
| `settings/cpk-thresholds.spec.ts:141` 警报文案内插 B 阈 | `apps/analysis/tests_cpk_thresholds.py:216` |
| `auth/auth.spec.ts:99` refresh 轮换 + 重放 401 | `apps/accounts/tests.py:144 TokenRefreshTests`（:162 rotates） |
| `sftp/sftp.spec.ts:153` 重名就地更新不新增 | `apps/sftp/tests.py:216 test_update_in_place_no_duplicate` |
| `exports/exports.spec.ts:189` 缺工位报错 | `test/backend/test_gage_site_filter.py:100` |
| `global/error-handling.spec.ts:44` 网络中断文案 | `frontend/test/unit/error.spec.ts:31`（**逐字同断言**，本轮我写的） |
| `exports/html-report.spec.ts:15/36` 报告内容 | `test/backend/test_html_report_single.py:55/64` 等（:59/:69 未逐条核） |

⚠ B 组删除**要求一轮 e2e 背书**：理由不是怀疑后端用例，而是这些文件里其余用例可能与被删用例
共享前置（`describe.serial` 链、种子数据、账号设置），删错会让后面的用例失去前置。
代理已就 `repair-center` 系列明确给出这个警告：其第 5 例的前置是前 3 例执行后的清理结果。

### C. 需先重构才能下沉（**不是搬代码，是动产品代码**）

T2 侧零重构成本的只有三个已导出函数：`formatAxisValue`（`chart-bar.ts:77`）、
`getMaxBarWidthPercent`（`:42`）、`formatPercent`（`:62`）。其余被点名的判据
**全都长在 `.vue` 里没导出**：`rangeOfPoints`（`SerialChart.vue:108`，已核实是组件内局部
function）、`expectedTier` 档表、`MultiFileTab.vue:259-293` 图例提名、`FileSelect.vue`
`highlightMatch`/比较器、`TableSettingsForm.vue:99 toggleGroup`、
`ExportTemplateSettings.vue:107 previewOf`、`TestItemOverviewSection.vue:180` 排序器、
`useSerialChartSettings`、`Sidebar.vue:86-93 menuItems`。
→ 每一条都要先做「把判据函数提出为可导入模块」的无行为改动重构，工作量必须计入，
不能按"直接下沉"估。

### E. 砍前置不砍判据（**性价比第一**）

- **E1 ✅ 已做（2026-10-13）`sftp/search-layout.spec.ts` 的 L1/L2/L3/L6 四例根本不需要连 SFTP**：
  条件卡的几何只依赖 roots 里有没有那枚 tag，不依赖会话 —— `connectAndOpenSearch` 是共用流程层
  顺带塞进来的成本。改为新增的 `openSearchForm()`：`gotoApp('/sftp/search')` + `addTag` 手工补一枚
  `/batch1`（做法抄 `search.spec.ts:430-432` 那条「未连接」用例，它已经这么干了）。
  **实测（workers=1，同机同负载）**：这四例 22.0s/例 → **0.60–0.70s/例**；只跑这四例 112s → 24s；
  整份文件 8 passed，全量 **1.2 分钟**。判据一条没动，且 L1/L6 条件卡高度改前改后都是 **559px**
  —— 数字一模一样，证明补 tag 与面包屑预填是同一份版式。L4/L5 仍走真链路（要跑一次搜索才有对象）。
- E2 ✅ **已做（2026-10-13）** `multi-file.spec.ts:334`「每个文件显示独立的 limit 线（含独立图例）」
  与 `:307`「Limit 线标注包含文件名和规格限类型」断言**逐行相同**（只差一句注释），标题承诺的
  「独立图例」从来没有被断言过 → 删 `:334`，留标题与断言相符的那条。
- E3 ✅ **一半已做，一半原判据错**（逐条实测后的结论，见下）：
  - `auth:40`（admin 顶栏徽标）⊂ `global:186`（同 `loginAs('admin')` + 同 `.user-role` 断言，
    还多一条侧边栏菜单可见）→ 删 `auth:40`。两条都在 P1 project（`grep: /@p1/` 命中标题），
    判据没有掉档。
  - ❌ ~~`auth:48` ≡ `auth:141`~~ **判错**：`:48` 断言「停在 /login 且 access_token 为 null」，
    `:141` 断言「内联 `.error-msg--invalid_credentials` 可见 + 含『次尝试』」，两条注释甚至互相
    矛盾（前者说全局拦截器抢在内联提示之前跳转，后者说 LoginPage 自己 try/catch 展示）。
    两条都通过 → 观测路径不同、判据不同，**都保留**。
  - ❌ ~~`sftp.spec.ts:404` ≡ `reconnect:292`~~ **判错**：前者是 `env-gated`（未设 `SFTP_HOST`
    即 skip）的**真机冒烟**，后者跑本地 fixture。"通常不跑"不等于"重复"——那一族四条
    （`:155/:196/:270/:341`）是留给有凭据的人手跑的，删掉就没了这条能力。**保留**。
- E4 ❌ **不做**：`chart-renderer.spec.ts:45/63` 看着成对，实际断言**相反**（canvas 在场+svg 缺席
  vs svg 在场+canvas 缺席），`:63` 是 `:45` 的负对照 —— 缺了它就无法区分「渲染器设置生效」与
  「代码写死 canvas」。合并只省一次冷启动（≈5 s），代价是坏一半时看不出坏的是哪一半。

## 判据缺口 → 需要决策（三个代理独立撞到，非设想）

（下文 D1–D5 取代本节早期按切片写的 D1–D10 编号；合并去重后只剩五条，
其中前两条**必须你拍**，因为它们与 2026-09-26 设计时"不做组件层"的决定直接相关。）

- **D1「ECharts option 层断言」无档（约 22 例）**：判据读 `__echartsInstance__.getOption()`
  —— 既不是响应体（T1 不成立），也不是无 DOM 纯函数（T2 不成立，且这些组件在容器拿到非零尺寸前
  根本不 init），又从不比较像素（不是 T3① 的本义）。代理暂时并入 T3①，**这是判据表的结构性缺口**。
- **D2「前端出站请求体」无档（约 20 例，最大面积）**：`postData()` 含
  `"data_only_bin1":true` 长得极像 T1，但 Django 测不到前端发了什么；落 vitest 又缺可 import 的
  payload builder。→ 要么定义 **T1f + 抽出 `buildHistogramRequest()` 纯函数**，要么明确这类永留 e2e。
- **D3「组件内联逻辑」无档（约 14 例）**：条件渲染显隐、默认值、菜单顺序、`aria-expanded`、
  store 持久化。jsdom + @vue/test-utils 完全能复现，但**设计时你明确选了"不做组件/DOM 层"**。
  现状是这 14 例既进不了 T2（有 DOM）也不在 T3 五类里。
- **D4「负向请求计数」无档（3 例）**：`某端点被调用 0 次 / 恰好 1 次`（懒挂载、watch 去重）。
  五档皆不合，却确实是唯一防线 → 建议显式判为「浏览器独占·不可下沉」并补进 T3。
- **D5 处置需要第二维度**：`重复（后端已锁，可直删）／混合（拆）／唯一（留）`。
  五档把"搬走"和"删掉"混成了 T1，而两者成本与风险完全不同。

另有两条**不新增档位、直接采纳**的修法：`T1+T3` 推广为「任意低层 + T3」（本批 25 例实为
**T2+T3**：纯函数判据 + formatter 已挂载的接线证明）；以及允许 `T1+T2`（`histogram-fail-bins:48`
两半都可下沉、都不该留浏览器）。

## 主代理抽样复核（代理结论的使用边界）

已核实为真：逐文件例数与 `--list` 分母逐个吻合；`formatAxisValue`/`getMaxBarWidthPercent`/
`formatPercent` 确已导出；`test_s3_zooms_and_spreads_data`、`test_custom_limit_recomputes_cpk`、
`test_page_size_9999_returns_all_files`、`accounts/tests.py:393/397/401`、`TokenRefreshTests:144`、
`sftp/tests.py:216`、`test_gage_site_filter.py:100`、`test_tiny_percentage.py` 均存在。

已核实为**措辞过强，结论仍成立**（故其"可直删"一律不自动采信）：
- `file-switch-param-reset:143`、`chart-filter-switches:148` 被说成"全例唯一断言"，
  实际各还有一条 tab 可见性 `expect`（那是前置，不是判据）。
- `sw-bin-qqplot-repro:51` 被说成"全例无 expect"，实际有 1 条（切 tab 前置）。
- 任务书里给的「data 目录约 124 例」是我早期按 `test(` 行数的**错误口径**，
  代理按实测 87 + smoke 5 = 92 纠正 ✓。
- 代理 4 纠正了我给的 T0 举例：`admin.spec` 的中文「已禁用」断言**在当前代码里不存在**
  （断的是原始 `'disabled'`，与 `statusLabel()` 一致）；陈旧物是注释，不是断言。
  本轮 settings 实质 T0 只有 `settings.spec.ts:56`「5 个标签页」（实现 6 个，漏 🔌 SFTP 设置）。
- ✅ 上述三条 T0 已在 2026-10-13 修完（改断言/改注释，不是删用例），见文末「T0 修正结果」。


## 切片：analysis 第 1–19 文件（73 例）

| 文件 | 例数 | T1 | T2 | T3 | T1+T3 | 待定 |
|---|---|---|---|---|---|---|
| analysis.spec.ts | 20 | 0 | 0 | 9 | 9 | 2 |
| axis-label-precision.spec.ts | 6 | 0 | 6 | 0 | 0 | 0 |
| boxplot-bool-params.spec.ts | 2 | 2 | 0 | 0 | 0 | 0 |
| chart-error-state.spec.ts | 2 | 0 | 0 | 2 | 0 | 0 |
| chart-filter-switches.spec.ts | 9 | 0 | 0 | 1 | 7 | 1 |
| correlation-file-switch-reset.spec.ts | 1 | 0 | 0 | 1 | 0 | 0 |
| correlation-inline.spec.ts | 2 | 0 | 0 | 1 | 0 | 1 |
| correlation-matrix-default-cap.spec.ts | 1 | 0 | 1 | 0 | 0 | 0 |
| correlation-matrix-linkage.spec.ts | 1 | 0 | 0 | 0 | 1 | 0 |
| custom-limit-cpk.spec.ts | 3 | 0 | 0 | 0 | 3 | 0 |
| dock-resize.spec.ts | 5 | 0 | 0 | 5 | 0 | 0 |
| file-list-completeness.spec.ts | 1 | 0 | 0 | 0 | 1 | 0 |
| file-select.spec.ts | 5 | 0 | 3 | 0 | 0 | 2 |
| file-switch-param-reset.spec.ts | 3 | 0 | 0 | 1 | 1 | 1 |
| gage-qqbox-repro.spec.ts | 2 | 0 | 0 | 1 | 0 | 1 |
| histogram-fail-bins.spec.ts | 1 | 0 | 0 | 0 | 0 | 1 |
| histogram-multiseries-clip.spec.ts | 5 | 0 | 2 | 3 | 0 | 0 |
| iqr-multiplier-propagation.spec.ts | 1 | 0 | 0 | 1 | 0 | 0 |
| kde-curve.spec.ts | 3 | 0 | 0 | 3 | 0 | 0 |
| **合计** | **73** | **2** | **12** | **28** | **22** | **9** |

本切片小结：**只有 2 例（2.7%）是纯 T1**，12 例（16%）含 T2 成分，22 例是混合待拆，
28 例确实不可替代。也就是说「把存量搬走」在这个模块里最多腾出约 19% 的用例量，
真正的收益要靠**新断言不再写进 e2e** —— 这与设计文档当初的推断一致，现已有数字。

### 逐例明细（本切片）

```
analysis.spec.ts:32 | 选择 CTA8280F 文件后进入分析并渲染直方图 | T3① | expectChartRendered → svg/canvas 非零尺寸 | 无
analysis.spec.ts:40 | 抽样 20 个参数，逐个断言直方图渲染 | T1+T3 | getByText(/Mean|均值|N\b/i) 可见 | 后端补 Mean/N 字段断言，留一条渲染
analysis.spec.ts:61 | 切换范围类型触发 histogram 重发并重渲染 | T1+T3 | postData().toContain('S3') | test/backend/test_histogram_range_type.py::test_s3_zooms_and_spreads_data（已存在）
analysis.spec.ts:95 | 开启 QQ 图后渲染 QQ 图 | T3① | locator('svg').count() >= 2 | 无
analysis.spec.ts:112 | 逐个抽样参数不应触发 4xx/5xx（空列名 + cross axisPointer） | T1+T3 | resp.status()<400；fatalErrors==[] | 后端补列名清洗；pageerror 段留 e2e
analysis.spec.ts:171 | 异常值处理默认为「不处理」 | T3⑤ | filterControl('outlier-handling') toHaveText | 无（默认值段可另立 vitest）
analysis.spec.ts:177 | 多文件分析范围类型默认为 RDL | 待定 | .el-select:has(#multi-range-type) toHaveText | 见决策点 D2
analysis.spec.ts:192×3 | 切换到 晶圆图/多文件/相关性 Tab 内容正常渲染 | T3③ | panel toBeVisible | 无（参数化展开 3 例）
analysis.spec.ts:203 | 切 Tab 后返回单文件分析直方图仍渲染 | T3① | expectChartRendered（display:none 恢复后重绘） | 无
analysis.spec.ts:218 | 加载 CP 数据后晶圆图 canvas 渲染 | T3① | expectChartRendered(可见 tabpane) | 无
analysis.spec.ts:240 | 箱线图 toggle 显示 | T1+T3 | resp.status()===200 + svg>=1 | apps/analysis/tests_api_contract.py（boxplot 200）
analysis.spec.ts:264 | 箱线图 groupBy 切换 | T1+T3 | expect(resp2.status()).toBe(200) | 同上（groupBy=bin 段）
analysis.spec.ts:294 | 箱线图离群点切换 | T3① | locator('.chart-wrapper--bottom svg').count()>=1 | 无（注释自陈不需新 API 调用）
analysis.spec.ts:317 | 箱线图参数切换显示 loading | T1+T3 | resp2.status()===200 + svg>=1 | 同上；标题与断言脱钩，见决策点 D4
analysis.spec.ts:351 | 相关性散点完整流程 | T1+T3 | r.status()===200；Number(nText)>0 | test/backend/test_correlation_scatter_pvalue.py（r/n）
analysis.spec.ts:394 | 西格玛模式出现倍数选择器 | 待定 | sigmaSel toBeVisible；yInputs.count()>=2 | 见决策点 D1（条件渲染）
analysis.spec.ts:447 | 单 SITE 图例显示 SiteN 而非「数据分布」 | T1+T3 | flat toMatch(/Site4/) | apps/analysis/tests_param_guards.py 已覆盖命名；图例段留 T3①
analysis.spec.ts:471 | gage_m_S1 单 Site1 文件图例也是 Site1 | T1+T3 | expect(flat).toMatch(/Site1/) | 同上
axis-label-precision.spec.ts:128 | 直方图 X 轴智能 4 位格式 | T2+T3 | formatter(12.34567)==='12.3457' | frontend/test/unit/chartBar.spec.ts（formatAxisValue 已导出 chart-bar.ts:77）
axis-label-precision.spec.ts:159 | QQ 图轴格式 + 字号取九档 | T2+T3 | axisLabel.fontSize===chartFontSize.micro | vitest + typography 快照
axis-label-precision.spec.ts:183 | 序列分布 Y 轴格式 + 8 色板 | T2+T3 | PALETTE_8 toContain(firstSeries) | vitest（getSiteColors8，chart-bar.ts:100 已导出）
axis-label-precision.spec.ts:205 | 相关性散点轴格式 | T2+T3 | assertSmartFormatter(container,'yAxis') | vitest（本例可整体搬走）
axis-label-precision.spec.ts:231 | 箱线图轴格式 + 箱体跟随主题主色 | T2+T3 | expect(borderColor).toBe('#2563eb') | vitest；主题色段属 T3② 应改读 token
axis-label-precision.spec.ts:252 | 多文件对比 X 轴格式 | T2+T3 | assertSmartFormatter(container,'xAxis') | vitest
boxplot-bool-params.spec.ts:30 | boxplot on Dut_Pass (bool) → 400 no_valid_params | T1 | status 400 + error + requested | ✅ 已搬 test/backend/test_boxplot_nonnumeric_params.py（本例成重复覆盖，待 e2e 可跑一轮后删）
boxplot-bool-params.spec.ts:89 | boxplot on Site # (str) → 400 no_valid_params | T1 | status 400 + error | ✅ 同上，可直接删
chart-error-state.spec.ts:23 | 请求失败显示错误横幅，重试后恢复 | T3③ | BANNER toContainText('直方图数据加载失败') | 无（route 拦截 + 错误态）
chart-error-state.spec.ts:61 | 切文件后旧失败横幅不残留 | T3③ | expect(BANNER).toHaveCount(0) | 无
chart-filter-switches.spec.ts:38 | Bin1 开关：请求携带且图表渲染 | T1+T3 | postData 含 "data_only_bin1":true | test/backend/test_analysis_filters.py（后端段）；出站段见决策点 D3
chart-filter-switches.spec.ts:71 | 仅 Fail / 仅低 CPK：参数列表收缩 | T1+T3 | listParams().length < allParams.length | test/backend/test_analysis_filters.py::test_filter_test_items_only_fail / only_low_cpk（已存在）
chart-filter-switches.spec.ts:125 | 忽略无测试值：请求携带开关 | T1+T3 | postData 含 "ignore_no_test_value":true | test/backend/test_analysis_filters.py
chart-filter-switches.spec.ts:148 | 序列分布勾选 Bin1 后重发 | 待定 | 有效断言仅 postData 含 data_only_bin1 | 见决策点 D3（无渲染段可留）
chart-filter-switches.spec.ts:172 | QQ 图请求携带开关且渲染 | T1+T3 | typeof qqBody.slope==='number' | 后端补 slope/intercept；dataZoom 段留 T3①
chart-filter-switches.spec.ts:235 | 箱线图请求携带 Bin1 且渲染 | T1+T3 | resp.url() 含 data_only_bin1=true | 后端补 bin1 过滤后统计值
chart-filter-switches.spec.ts:263 | 全 Pass 文件勾选 Bin1 后参数列表不变 | T1+T3 | expect(after).toEqual(before) | test/backend/test_gage_views_bin1.py（已覆盖）
chart-filter-switches.spec.ts:283 | 「忽略无Limit」位于首位 + 请求携带 | T1+T3 | .filter-section .el-checkbox first toContainText | 后端 ignore_no_limit 段；「首位」见决策点 D5
chart-filter-switches.spec.ts:316 | 柱宽 slider：barWidth 与实际柱宽像素同步 | T3① | getItemLayout(0).width>0 | 无（EP slider + 真实 layout）
correlation-file-switch-reset.spec.ts:17 | 切文件后散点/指标卡清空、选择器回占位 | T3③ | head-metric toHaveCount(0)；.el-empty 可见 | 无
correlation-inline.spec.ts:31 | 参数 chips 选择 + 卡头指标行 | T3⑤ | onCount===Math.min(12, chipCount) | 无（min(12) 数值段可下沉）
correlation-inline.spec.ts:89 | 抽样注记「抽样 N/M 点」 | 待定 | .sample-note toContainText('抽样') | 条件文案非五类，见决策点 D1
correlation-matrix-default-cap.spec.ts:25 | 参数>12 时默认只选 12 项 | T2 | expect(parsed.chosen).toBe(12) | vitest —— 但默认选中数当前在组件内，需先抽成纯函数
correlation-matrix-linkage.spec.ts:21 | 点非对角格就地更新散点 + 方法下拉生效 | T1+T3 | postDataJSON().method==='spearman' | 后端 method=spearman 段；convertToPixel 点格留 T3①
custom-limit-cpk.spec.ts:29 | CL 模式双 CPK 卡 + 范围表显示输入值 | T1+T3 | v2 not.toBe(v1)；td toHaveText(low.toFixed(5)) | test/backend/test_histogram_range_type.py::test_custom_limit_recomputes_cpk（已存在）；markLine 段留 T3①
custom-limit-cpk.spec.ts:130 | 二次修改 limit 后 CPK 重算 | T1+T3 | backendCustomCpk not.toBeNull() | 同上；「UI 应用响应」段留 e2e
custom-limit-cpk.spec.ts:200 | 快速连改 limit 最终反映最后一次 | T1+T3 | body 含最终 custom_high | 后端可锁重算；**竞态时序不可下沉**，整例应留
dock-resize.spec.ts:142 | 底部横条双向拖拽 → 4 图画布跟随 | T3① | |chart.h-host.h|<=4 | 无
dock-resize.spec.ts:167 | 横条高度进布局记忆，刷新后恢复 | T3③ | expect(bodyH()).toBe(h1) | 无（PUT 载荷段见决策点 D3）
dock-resize.spec.ts:230 | 行间拖拽条改占比 → 上下两行跟随 | T3① | panelHeight('hist') 变小 / 'serial' 变大 | 无
dock-resize.spec.ts:247 | 拖图合并行 → 占比归一、横条贴合 | T3① | expect(bottomGap()).toBeLessThanOrEqual(14) | 无
dock-resize.spec.ts:276 | 最大化可复原 | T3① | panels toHaveCount(1)→(3)→(4) | 无
file-list-completeness.spec.ts:57 | 分析页文件下拉与数据管理页总数一致 | T1+T3 | totalCount===api.singles | test/backend/test_file_pagination.py::test_page_size_9999_returns_all_files（已存在）
file-select.spec.ts:46 | 搜索过滤大小写不敏感 + 空态 | 待定 | items.count()).toBe(1) | 走 EP 内置 filterable，期望值依赖种子库，见决策点 D6
file-select.spec.ts:70 | 匹配段以 <mark> 渲染 | T2 | marks.first() toLowerCase()==='bpd' | vitest（需导出 FileSelect.vue 的 highlightMatch）
file-select.spec.ts:82 | 前缀优先排序 | T2 | firstText startsWith('BPD') | vitest（需导出比较器）
file-select.spec.ts:98 | 多选过滤 + 已选置顶 | 待定 | items.nth(1) toContainText | 依赖 EP 多选内部顺序，见决策点 D6
file-select.spec.ts:130 | 富信息行 program · format · 行数 | T2+T3 | text toMatch(/\S+ · \S+ · \d+ 行/) | vitest 断文案 + 保留 boundingBox 裁剪段（jsdom 无布局）
file-switch-param-reset.spec.ts:50 | 陈旧 param 不得再发给新文件 API | T1+T3 | qq.status()===200；apiErrors==[] | tests_param_guards.py 已锁 400；「不发陈旧请求」是前端态，留 e2e
file-switch-param-reset.spec.ts:143 | 未选参数时开 QQ/Box 再切文件不崩 | 待定 | expect(LAYOUT).toBeVisible() | 弱断言，建议补强而非删，见决策点 D7
file-switch-param-reset.spec.ts:170 | 切文件后直方图重新渲染（非空白） | T3① | expectChartRendered | 无
gage-qqbox-repro.spec.ts:25 | 文件/参数切换 + QQ/Box 开关压力测试 | T3 | expect(pageerror).toEqual([]) | 无（Vue 运行时崩溃仅浏览器可见；循环内 status 只 log 未断言）
gage-qqbox-repro.spec.ts:104 | 无数据时 BoxPlot 占位渲染 | 待定 | '.boxplot-placeholder, .chart-container' 任一可见 | OR 选择器 + 注释自陈空态未触达，见决策点 D7
histogram-fail-bins.spec.ts:48 | RDL 下超限 bin 保持原 series 颜色 | 待定 | bar.hasCustomStyletoBeFalsy；failBinCount>0 | T1×T2 混合且零浏览器段，见决策点 D8
histogram-multiseries-clip.spec.ts:76 | 8 站点 overflow/underflow bin 柱体渲染 | T3① | getItemGraphicEl(i).ignore===0 | 无（注释自陈只能真渲染）
histogram-multiseries-clip.spec.ts:101 | 多文件各系列柱体全部渲染 | T3① | expectNoIgnoredBars | 无（系列数/pad 可另立 vitest）
histogram-multiseries-clip.spec.ts:140 | 贴限 bin 不越过 USL 线 | T3① | maxRight<=uslPx+0.5（convertToPixel） | 无（轴像素，T3① 核心样本）
histogram-multiseries-clip.spec.ts:191 | 柱宽/重合 slider 联动 | T2 | aria-valuemax).toBe('10') | vitest（getMaxBarWidthPercent 已导出 chart-bar.ts:42，可整例搬走）
histogram-multiseries-clip.spec.ts:236 | Site 统计表格式 Yield=xx.xxx%(n) | T2 | site7Row toMatch(/\d+\.\d{3}%\(\d+\)/) | vitest（需把行格式化抽成纯函数）
iqr-multiplier-propagation.spec.ts:41 | 页头切「宽松 3.0x IQR」后以 3.0 重发 | T3③ | expect(seen.at(-1)).toBe(3) | 后端补 iqr_multiplier=3.0 边界；出站段见决策点 D3
kde-curve.spec.ts:45 | 默认勾选且图例含 KDE曲线，可切换 | T3① | legendText()).toContain('KDE曲线') | 无（ECharts SVG 图例文本）
kde-curve.spec.ts:77 | 「KDE含超限」默认关、可切换 | T3① | not.toHaveClass(/is-checked/) | 无
kde-curve.spec.ts:102 | 正态分布开关仍独立 | T3① | legendText()).not.toContain('正态分布') | 无
```

### 抽样复核结论（主代理实测，非代理自述）

- 该切片的**逐文件例数**与 `--list` 权威分母逐个吻合（analysis 20 / axis-label 6 / boxplot 2 /
  chart-error 2 / chart-filter 9 …）✓
- 引用的 T2 落点函数真实且已导出：`formatAxisValue`（`chart-bar.ts:77`）、
  `getMaxBarWidthPercent`（`:42`）、`getSiteColors8`（`:100`）✓
- 引用的「后端已覆盖」测试真实存在：`test_s3_zooms_and_spreads_data`（`test_histogram_range_type.py:60`）、
  `test_custom_limit_recomputes_cpk`（`:107`）、`test_page_size_9999_returns_all_files`
  （`test_file_pagination.py:60`）✓
- **但代理有两处把前置 `toBeVisible` 说成"全例唯一断言"**（`file-switch-param-reset:143`、
  `chart-filter-switches:148`），实际各还有一条 tab 可见性断言。结论（弱断言 / 无渲染段）成立，
  措辞过强 —— 因此本清单里代理提的"可直删"一律不自动采信，逐条自己核。

## 判据缺口 → 需要决策（分诊过程中真实撞到的，不是设想）

这些不是分类学洁癖：每一条都对应一批用例**当前无处可落**，因而只能继续留在 5.4 s/例 的层。

- **D1 条件渲染无处安放**（本切片 6 例：`analysis:394`、`correlation-inline:89`、默认值段等）。
  「勾选开关 → 控件出现/消失」jsdom 完全能复现，但按判据它既不是 T2（有 DOM）、
  也不在 T3 五类里。→ 要么承认新增一档 **T2b 组件级 jsdom**（与设计时"不做组件层"的决定相反），
  要么明确这类一律留 T3。
- **D2 锚点用 `id` 而非 `data-*`**（`analysis:177` 的 `#multi-range-type`）。这是产品契约决策，
  不该由测试单方面定：要么给它补 `data-filter`（升为 T3⑤），要么承认默认值属 D1 那档。
- **D3「前端出站请求体」整类无落点（本切片 10 例，最大面积）**。
  `postData()` 含 `"data_only_bin1":true` 长得极像 T1，但 Django 无从验证前端发了什么；
  要落 vitest 又缺一个可 import 的 payload builder（请求体在各 tab 内联拼装）。
  → 需要一档 **T1f 前端出站契约** + 把 histogram 请求体抽成纯函数。**不解决这条，
  `chart-filter-switches` 9 例里至少 6 例搬不走。**
- **D4 标题与断言脱钩**（`analysis:317`「显示 loading」全无 loading 断言等 3 例）。
  按标题路由会搬错，本清单已按实际 `expect` 落标。
- **D5 布局顺序算不算契约**（`chart-filter:283` 钉「忽略无Limit 在首位」，锚在 EP 内部类
  `.el-checkbox`，而同一区域**已经有** `data-filter`）。EP 升级即碎。要么产品明确顺序是契约，
  要么这条断言可直接删。
- **D6 期望值依赖种子库累积**（`file-select:46/98`）。`>=3`、`count()===1` 随共享 DB 漂移，
  注释自己承认"抗 DB 累积干扰"。这是**用例可信度**问题不是分层问题 —— 搬到哪档都会红。
- **D7 弱断言/恒真**（`file-switch-param-reset:143` 只断布局可见；
  `gage-qqbox-repro:104` 用 OR 选择器且注释自陈空态从未触达）。建议处置维度单列
  「补强 / 删」，不要靠"塞进 T3"给零判据用例发通行证。
- **D8 两半都可下沉、都不该留浏览器**（`histogram-fail-bins:48`：后端 bin 数值 + 前端 series
  组装，全经 `getOption()` 读 JS 配置对象，没读渲染结果）。建议允许 `T1+T2` 记法。
- **D9 记法**：`T1+T3` 应推广为「任意低层 + T3」，本切片 12 例实际是 **T2+T3**
  （纯函数判据 + 「已挂载」的接线证明）。不解决这档，`axis-label-precision` 6 例（≈32 s 串行）
  会原封不动留下。
- **D10 需要「处置」第二维度**：`重复（后端已锁，可直删）／混合（拆）／唯一（留）`。
  现在五档把"搬走"和"删掉"混成了 T1，而这两件事的成本与风险完全不同。

## 已下沉 / 待办

- ✅ `boxplot-bool-params.spec.ts` 两条 → `test/backend/test_boxplot_nonnumeric_params.py`
  （5 例 / 10 ms，另补 3 条语义）。e2e 侧整文件已在 A 组删除（`9fec0dd`，138 行）。
- ⏳ 其余 324 例分诊。
- ⏳ 试点簇 #2 `custom-limit-cpk`（3 例 T1+T3，拆法已在上面标出）、#3 `settings/cpk-thresholds`。

## B 组执行结果（2026-10-13，已按「需要一轮 e2e 背书」的要求做完）

删了 5 条（每条删除前 grep 确认后端 / vitest 有同名判据）：
`settings/export-timeout.spec.ts:70`(20 行)、`auth/auth.spec.ts:99`(34 行)、
`sftp/sftp.spec.ts:153`(62 行)、`exports/exports.spec.ts:189`(28 行)、
`global/error-handling.spec.ts:44`(7 行)。392 → **387 例**，`--list` 无解析错误。

**2 条按判断不删**，与代理结论相反，理由记录在此以免下轮被当成重复清掉：

- `exports/html-report.spec.ts:15/36` —— 后端确实已覆盖**文件内容**四条断言，但只有这两例能证
  「仪表板按钮真触发了下载 + 落盘产物自包含」。整删等于把 T3④ 的接线证明一起丢掉。
- `settings/cpk-thresholds.spec.ts:141` —— 它防的回归是**前端把 1.33 写死**。后端用例断的是后端
  生成的文案；前端一旦不再消费该字段，会呈现后端全绿、界面显示错常量的局面。

背书账目（同一范围，`--retries=0`）：

| 轮 | workers | 结果 |
|---|---|---|
| 删除前基线 | 6（默认） | 85 passed / **1 failed** / 5 skipped = 91 |
| 删除后同范围 | 6 | 15 passed / 5 skipped / **8 did not run**（成片红） |
| 删除后仅改过的 5 文件 | 1 | 28 passed / 4 skipped / **0 failed** |
| 删除后同范围 | 1 | 81 passed / 5 skipped / **0 failed** = 91 − 5 ✓ |

两个副产品结论：

1. 第 2 行的成片红是**并发秩序污染**而非删除后果：`settings.spec.ts:158「恢复默认」`会在共享
   admin 账号上重置全部持久化设置，与 `export-templates` / `system-paths` 同批并发时把后者踩掉；
   串行即全绿。这条决定了**组合范围验证必须 `workers=1`**，否则任何删除都会被误判成回归。
2. 基线那 1 条 `settings/chart-renderer.spec.ts:45` 的红在 `workers=1` 下为绿 → 它是并行 flake，
   **不是存量回归，分诊表里不记 T0**。

## E 组执行结果（2026-10-13）

387 → **385 例 / 74 文件**，`--list` 0 解析错误；改过的文件串行真跑 27 passed / 0 failed。

| 动作 | 例数 | 墙钟实测（workers=1，同机同负载） |
|---|---|---|
| E1 版式四例砍掉 SFTP 连接 | 0 删 | 这 4 例 **22.0 s/例 → 0.60–0.70 s/例**；只跑四例 112 s → 24 s；整份文件 1.2 min |
| E2 `multi-file:334` 逐行重复 | −1 | 省一次 `multi_lot` 冷启动 + 多批次计算 |
| E3a `auth:40` ⊂ `global:186` | −1 | 省一次 UI 登录 |
| A/B 组删除留下的空 describe + 失效 import | 0 | — |

E 组里 **两条"重复"实测判错**（原文见上方 E2/E3/E4 条目）：`auth:48`/`auth:141` 断言的是互斥的
两种可观测行为；`sftp:341` 是 env-gated 真机冒烟，不是 fixture 用例的副本。这正是 R1 的老形状 ——
代理给的"可直删"标签必须先按内容实测一遍再落刀：分诊清单写的是**行号**，而 A/B 两组删除已经把
后面的行号整体前移过（`auth:176`→`:141`、`sftp:404`→`:341`），照号删会删错对象。

## T0 修正结果（2026-10-13）

三条都**改断言/改注释**，没有减少用例数（385 例不变）：

1. `settings.spec.ts` TABS 补第 6 项 `🔌 SFTP 设置`（`SettingsPage.vue:20` 早已有该 pane），
   标题「5 个标签页」→「6 个」。这条以前是**假窄**：新增 tab 不会被任何用例发现。
2. `settings.spec.ts:99` 的 `expect(response.request().method()).toBe('PUT')` 是同义反复
   （`waitForResponse` 的 predicate 已经按 PUT 过滤），换成**断请求体** `"chart_dpi":200` +
   响应 200；predicate 同时补 `postData` 过滤，与渲染器用例同一口径，避免并行 project 互抓 PUT。
   另补 `finally` 把 `chart_dpi` 恢复成默认 100 —— 它住在共享 admin 账号上，不复位会把 200
   漏给后面的渲染类断言（这也是 `settings.spec.ts:177「恢复默认」` 那类秩序污染的同一形状）。
   复原助手 `putSetting` 自带 `expect(status).toBe(200)`：fire-and-forget 的 finally 坏了没人知道。
3. `admin.spec.ts:176` 注释说断「已禁用」，body 实际断原始值 `disabled`（与 `statusLabel()` 一致）
   → 改注释，断言不动（代理 4 的纠正成立：陈旧物是注释，不是判据）。

背书：`settings.spec.ts` + `admin.spec.ts` 串行 `--retries=0` → 13 passed / 0 failed；
单跑 `settings.spec.ts` → 8 passed。端口已释放。
