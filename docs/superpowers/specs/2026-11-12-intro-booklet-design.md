# LQ-DataPrase 产品介绍书（docs/intro/）设计规格

- 日期：2026-11-12（v3 收口）
- 状态：已实施并实测；维护规则见 `.claude/CLAUDE.md`「产品介绍书定期维护」条
- 交付物：`docs/intro/index.html`（单文件）+ `docs/intro/assets/`（8 张合成数据截图）
- 防漂移检查：`node scripts/intro/check.mjs`

## 1. 背景与目标

面向半导体量产测试（CP/FT）工程师与评审者，用一份可离线分发的交互式介绍书展示平台全部功能「怎么用」。
原始需求四条：真实图片、点击动画/交互、目录、版本号。后续两轮反馈追加：

- v2 反馈：① 每章只介绍一个功能 → 改为全子功能巡礼；② 截图变形 → 修根因并让表格/表单页脱离截图；③ 部分页面可不用截图 → 可操作 HTML 复刻。
- v3 反馈：① 最大化右侧留白 → 宽屏流式居中；② 正式项目顶栏加入口（新标签页打开）；③ 快速上手加入服务器形态访问网址 `https://125.69.67.169:18124`。

## 2. 形态与分发（四形态同源）

单一事实源 = `docs/intro/`。不复制第二份内容进 frontend/public（防漂移）。

| 形态 | 路径 | 机制 |
| --- | --- | --- |
| 本地双击 | `docs/intro/index.html` | 自包含：内联 CSS/JS + 相对 assets，无外部资源 |
| dev / preview | `/intro/index.html` | `frontend/vite.config.ts` 的 `introBooklet()` 插件：dev 中间件挂 `/intro`（含穿越防护），build `closeBundle` 拷入 `dist/intro` |
| Electron 打包 | `file://…/dist/intro/index.html` | spec 整树打包 `frontend/dist` → `frontend_dist`；顶栏按钮相对 `document.baseURI` 解析 |
| 服务器单端口 | `/intro/index.html` | `config/urls.py` 的 `intro` 挂载（`_serve_frontend_file('intro')`），前缀让出 SPA catch-all |

顶栏入口：`frontend/src/components/layout/Topbar.vue` 的 `[data-testid=open-intro]` 书本图标按钮，
`window.open(new URL('intro/index.html', document.baseURI).href, '_blank', 'noopener')`。
浏览器形态 = 新标签页；Electron 形态 = 新窗口（无主进程改动）。

## 3. 内容模型

- 13 章：封面 / 概览 / 快速上手 / 仪表板 / 数据管理七页签 / 数据分析五视角 / SFTP / 权重 / 设置 / 用户与审计 / FAQ / 版本历程 / 术语表。
- **功能卡**（`.feat .fc`，78 张）：每子功能一张＝名称＋一句口径＋「怎么用」一行。章节覆盖度以源码页签清单为准，不以截图数量为准。
- **复刻界面**（`.mock`，15 个）：表格/表单类页面按真实列名、按钮、判定口径重建，可操作（过滤/右键菜单/向导/规则重判/互斥分配/CRUD＋撤销/审计筛选）。徽标「复刻 · 可操作」与真实截图徽标在 §01 图例区分。
- **真实截图**（8 张）：仅图表密集型页面（仪表板、单文件分析、3D、晶圆图、多文件、相关性、权重、夜间）。`img` 必须 `width/height` 属性 + CSS `height:auto` 锁纵横比（v1 变形根因：height 属性被当固定像素高度）。
- **热点标注**（29 个 `.hs`）：编号圆点 + 气泡 + 图下自动生成的标注清单；坐标为百分比，随图等比缩放。
- **交互演示**（4 个）：IQR 裁剪直方图（12 控件 + 拖框子集 + 导出 SVG）、晶圆图四着色/环带、相关性矩阵点格出散点、权重声明粘贴即解析。
- 附录：FAQ 12 条、版本时间线（git 核实）、术语 20 条。

## 4. 视觉系统

- 双主题：`html[data-theme]` + CSS 变量（light 蓝 / night 琥珀，与应用同源语义）；`localStorage('intro-theme')` 记忆。
- 章节色相 `--chap`（概览蓝 / 数据青 / 分析紫 / SFTP 青 / 权重品红 / 设置琥珀 / 管理红）驱动章号徽标、功能卡侧条、tab 下划线。
- 环境层：多 hue 光晕 + feTurbulence 细颗粒；自定义滚动条；封面分级入场；滚动显现；阅读进度条。
- 宽屏：主区 `margin-left:max(sidebar, (100vw+sidebar-1760)/2)`、`max-width:1760`；正文限宽 1000px，图表/表格/复刻随宽屏放大。
- 响应式断点 1080 / 860：抽屉目录、rail 横排、表格容器内部横向滚动（文档级零溢出）。

## 5. 数据与口径红线

- 全部截图与复刻数据为合成演示数据（DEMO_* 文件、合成账号）；**不得**出现真实料号、私有样例文件名、外迁兄弟工程名、凭据字面量（check.mjs 红线扫描）。
- 文案口径以源码为唯一事实源：页签清单（DataManagement.vue / AnalysisPage.vue）、对比规则 A/B/C 与双侧容差（FileCorrelationControls.vue）、CPK 默认阈值（accounts 迁移）、Gage/Buyoff 最少文件数、设置生效方式（SettingsPage 各 Form）、「无导出中心页面」（jobPolling.ts 注释）。
- 版本号单一事实源 `frontend/package.json`；书面两处（顶栏徽标、封面芯片）由 check.mjs 钉同源。

## 6. 验证矩阵

- T1：`test/backend/test_static_assets.py::IntroBookletServingTests`（真实 URLconf：整页 200 且含 `id="cover"`、不含 `<div id="app">`；bare/斜杠/ png / 穿越 404 / catch-all 对照组）。跑法：`manage.py test test.backend.test_static_assets --settings=config.settings.standalone`。
- 构建门禁：`npm run build`（vue-tsc -b + vite build，顺带产出 dist/intro）。
- 浏览器实测清单：四形态可达；8 图加载且渲染比==原始比；热点/ tab / stepper / FAQ / 灯箱 / scrollspy；复刻交互逐组点验；1440 / 888 / 420 / 2545 四档零横向溢出；控制台零报错。
- 批次门禁：urls / Topbar / vite.config 命中全局清单 → 全量档（lint:e2e + vitest + 后端全量 + e2e 池）；判绿取日志 `RESULT:` 行。

## 7. 维护流程（定期维护触发与步骤）

**触发时机**：① 每次版本发布（版本号两处＋时间线新增节点）；② 任何改动 UI 页签/列名/按钮/判定口径的批次收口时；③ 新增主功能页或子页签；④ 每季度一次全量走读（对照应用逐章点验）。

**步骤**：
1. 改内容：直接编辑 `docs/intro/index.html`（功能卡/复刻/热点/文案）；新增截图走 §8 配方。
2. 同步版本：改顶栏徽标与封面芯片（或发布时统一替换），时间线追加节点。
3. `node scripts/intro/check.mjs` 必须 PASS。
4. 门禁：按 `docs/reference/testing-gates.md` 选档；涉及 serving 三文件（urls/vite.config/Topbar）走全量档。
5. 浏览器走读改动章节（桌面 + 420px），控制台零报错后提交。

**截图复现配方**（合成数据演示环境，scratch 脚本在 `tasks/intro-demo/`，gitignored；角色如下，丢失时按此重建）：
- `make_demo_data.py`：生成 DEMO_FT_LOTA–D / DEMO_CP_WAFER01 等合成 CSV；
- `seed_via_api.py` / `replace_files.py` / `patch_paths.py`：经 API 播种账号与文件、替换媒体、改存储路径到 slot；
- `sftp_server.py`：演示 SFTP（18222，合成目录树与 ShadowReg2 语料）；
- 起服务：后端 `LQDP_E2E_SLOT_DIR=<repo>/tasks/intro-demo/slot DJANGO_SETTINGS_MODULE=config.settings.e2e_slot PYTHONUTF8=1 .venv/Scripts/python.exe manage.py runserver 127.0.0.1:18231 --noreload`；前端 `E2E_PORT=18231 E2E_FRONTEND_PORT=18232 npm run dev`；
- 截图：chrome-devtools MCP，视口 2000×1127（图表页）/2560×1202（宽页），仅存 Temp 中转目录再 `mv` 进 assets；**严禁**真实数据入镜。
- 演进选项（未实施）：把上述配方脚本提升入库 `scripts/intro/`；内容数据化（JSON content block + 渲染器）降低编辑成本；不建议组件化进主应用（破坏离线单文件分发且增 bundle）。

## 8. 已知限制

- 单文件 2600+ 行：文案与框架混排，编辑需定位；复刻逻辑与_app_ UI 无自动联动，靠维护流程②人工同步（check.mjs 只钉结构/红线/版本，不钉语义）。
- 热点坐标手工标定：换截图必须重标（配方截图视口固定以复用坐标）。
- Electron 形态入口为新窗口而非标签页（壳无 tab 概念）；服务器形态自签证书需用户信任一次。

## 9. 验收记录

- v1（2026-11-12 上午）：18 截图 + 64 热点 + 目录/版本/双主题/直方图演示；桌面 + 420px 实测、控制台零报错。
- v2（同日下午）：修变形根因；10 张表格类截图换 15 复刻；78 功能卡；4 演示；2.1MB；三档宽度实测；修 `.tag` 窄屏竖排。
- v3（同日傍晚）：宽屏流式（2545 实测左右 259/259 对称）；顶栏入口四形态实测（preview 登录→新标签直达）；快速上手网址；T1 五例；check.mjs PASS。