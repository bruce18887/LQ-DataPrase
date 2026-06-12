# LQ-DataPrase Streamlit 项目完整功能清单

> **版本**: v0.2.0 Alpha  
> **代码规模**: ~12,000+ 行 Python  
> **页面**: 5 个主要页面 + 登录 + 用户管理  
> **支持格式**: CTA8290D / CTA8280F / ETS88 / STS8200

---

## 一、用户认证与权限系统 (`src/layout/login_page.py`, `src/login/login.py`)

| 功能 | 说明 |
|------|------|
| 登录页面 | 精心设计的渐变背景+圆角卡片式登录表单，带版本号/安全提示/页脚 |
| 用户名/密码认证 | SHA256 密码哈希 + `hmac.compare_digest` 防时序攻击 |
| 角色管理 | 3 种角色：`administrator` / `user` / `viewer` |
| 权限矩阵 | 9 项功能权限 (upload_data / view_data / analyze_data / export_data / manage_users / manage_settings / sftp_browser / delete_file / batch_management)，按角色白名单控制 |
| 账户锁定 | 5 次失败锁定 15 分钟，自动解锁 |
| 会话管理 | 30 分钟超时自动清除，login_time 追踪 |
| 密码复杂度 | 至少 8 位，含大小写字母和数字 |
| 用户存储 | SQLite 数据库 (`Data/.users.db`)，含 WAL 模式 |
| 用户数据隔离 | 每个用户独立目录 `Data/users/<username>/`，包含上传文件、设置、批次数据 |
| JSON 迁移 | 自动检测旧 `users.json` 并迁移到 SQLite |
| SFTP 密码存储 | XOR 加密存储用户 SFTP 凭据到同一 SQLite 库 |

### 用户管理页面（管理员专属）

| 功能 | 说明 |
|------|------|
| 概览面板 | 总用户数 / 活跃 / 锁定 / 管理员 四个 KPI 卡片 |
| 用户列表 | 表格展示所有用户（角色图标 + 状态圆点 + 创建/登录时间） |
| 添加用户 | 用户名+密码+显示名+角色，含密码复杂度校验 |
| 编辑用户 | 修改状态(active/locked/disabled)、显示名称、角色 |
| 重置密码 | 管理员可重置任意用户密码为 `123456` |
| 删除用户 | 管理员可删除用户（不能删除自己） |
| 管理员概览 | 侧边栏展开面板查看所有用户的文件分布 |

---

## 二、数据源与文件管理 (`src/layout/sidebar.py`, `src/pages/data_management.py`)

### 2.1 侧边栏（数据入口）

| 功能 | 说明 |
|------|------|
| 多文件上传 | 拖拽或选择 CSV，支持多选，自动解析格式 |
| 上传进度条 | 逐文件显示处理进度 |
| 自动设当前文件 | 上传后自动将首个文件设为当前活动文件并导航到仪表板 |
| 已有文件列表 | 显示用户目录下已有文件，格式标签 |
| 文件恢复 | 登录后自动扫描 `Data/users/<name>/uploads/` 恢复会话语境 |
| 批次 ZIP 导入 | 上传 ZIP 自动解压，识别批次目录结构（子批次子目录）→ 自动导航到仪表板 |
| 批次目录手动输入 | 文本输入框指定本地 `FullData` 目录路径 |
| 退出登录 | 清除 session_state，返回登录页 |

### 2.2 文件管理页面

| 功能 | 说明 |
|------|------|
| 文件卡片浏览 | 网格布局展示所有已上传文件（文件名/格式/尺寸），3 列自适应 |
| 设为当前文件 | 点击按钮切换当前分析目标文件，自动重新解析 |
| 文件删除 | 有 `delete_file` 权限的用户可删除文件（物理删除+清除状态） |
| 当前文件标识 | ✓ 标记当前激活的文件 |

---

## 三、仪表板 (`src/pages/dashboard.py`, `src/pages/dashboard_entry.py`)

### 3.1 单文件仪表板

| 功能 | 说明 |
|------|------|
| **KPI 指标卡片** | 总记录数 / Pass 数量 / Yield% / 数据格式，4 列渐变色卡片 |
| **Bin 详细统计表** | 按 Site × Bin 交叉统计（Site1/Site2... + ALL Site），百分比 |
| **Bin 分布饼图** | ECharts 环形饼图，支持滚动图例 |
| **Site Yield 柱状图** | 各 Site 良率柱状图，红(<90%)/黄(≥90%)/绿(≥95%) 条件着色 |
| **Yield 仪表盘** | ECharts Gauge 仪表盘，红黄绿三区段(90%/95%)，含最高/最低/差异指标 |
| **Fail 测试项 Top 10** | 横向柱状图，渐变色 |
| **Fail 测试项统计表** | 完整 Fail 项列表（测试项名称/Fail数量/占比），总Fail次数汇总 |
| **数据质量概览** | 数值测试项数 / 有Limit项数 / Site数 / Bin种类 / Fail Bin数 / Top Fail项 |
| **已上传文件列表** | 显示所有文件（当前文件⭐标记），含格式/行数/列数 |
| **解析历史** | 最近 10 条解析记录 + 总次数 + 今日次数指标 |
| **HTML 报表下载** | 一键生成静态 HTML 报表（含图表 + 数据表），支持离线查看 |

### 3.2 批次良率报表 Tab (`src/pages/batch_dashboard.py`)

| 功能 | 说明 |
|------|------|
| 批次/子批次选择 | 从 `Data/Data/FullData/` 目录扫描，结构：批次→子批次→Phase(CP1/FT1/QA1...) |
| 批次概览表 | 各 Phase 的 Total/Pass/Fail/Yield 汇总表，Fail 行标红 |
| Site 通过率柱状图 | 各 Phase 中每个 Site 的 Pass 数量分组柱状图 |
| Bin 分布图 | 每个 Phase 的 Bin 分布饼图 |
| Phase 趋势 Yield 折线图 | 各 Phase 各 Site 良率趋势折线 |
| 测试时间段分析 | 扫描文件中的 StartTime/EndTime 计算耗时 |
| LotID 自动提取 | 从文件行/列中智能识别 LotID |
| 批量详情文件列表 | 显示每 Phase 对应的 CSV 文件名、行数 |
| 测试批量报表导出 | 调用 generate_batch_report_excel 生成 Excel 批量报表下载 |

---

## 四、数据分析页面 (`src/pages/analysis_page.py`, `src/view/view.py`)

### 4.1 单文件分析

#### 直方图数值分布模式

| 功能 | 说明 |
|------|------|
| 参数选择 | SelectBox + 上一个/下一个按钮（↑↓ 键盘导航） |
| **范围类型选择器** | 6 种：RowDataLimit / Data Range / 3Sigma / 4Sigma / 6Sigma / CustomLimit |
| 范围对比表 | DataGap 对比表，当前选中行蓝色高亮 |
| **图表配置复选框** | Limit 线 / 3σ线 / 4σ线 / 6σ线 / 正态分布曲线，5 个独立开关，全局记忆 |
| 直方图（ECharts） | 按 Site 分组条形图 + markLine 标注 LSL/USL/σ线 + 正态拟合曲线 |
| 直方图（Matplotlib） | 可选切换引擎，支持 Site 分组 + LSL/USL/σ标注 |
| 统计摘要 | Range / Mean / STD / CPK / N，CPK 按 A(优秀≥1.67)/B(良好≥1.33)/C(一般≥1.0)/D 分级着色 |
| Site 统计表 | 每 Site 的 Yield / FailCount / ExceedMin / ExceedMax，Fail 行红色高亮 |
| **批量导出分布图** | 多选参数 → 生成直方图或均值柱状图 → 导出为 PPT 或 Excel 单文件 |
| **导出测试项 Limit** | 选择 3/4/6 Sigma 级别，导出测试项的 Limit 值和规格 Excel，可选只导出有效 Limit 项、过滤无数据项 |
| 忽略无Limit选项 | 全局开关，隐藏未设 Limit 的测试项 |

#### 序列分布模式

| 功能 | 说明 |
|------|------|
| 序列散点图 | 按 Site 分组，Serial 为 X 轴，参数值为 Y 轴 |
| 连续 Serial | X 轴补全缺失 Serial（int 型），散点悬停显示值 |
| Limit 线覆盖 | 与数值分布模式共用图表配置 |

#### 统计子页面

| 功能 | 说明 |
|------|------|
| Fail Bin 饼图 + 统计表 | 环形饼图 + Site×Bin 交叉表 + Yield 分析报告（最高/最低/差异）|
| Fail 测试项统计 | 各测试项 Fail 次数和占比表，总 Fail 次数 |

### 4.2 晶圆图 (`render_wafer_map_page`)

| 功能 | 说明 |
|------|------|
| **晶圆散点图** | ECharts scatter 模拟晶圆图，rect symbol 表示 Die |
| Pass/Fail 着色 | 绿色(Pass) vs 红色(Fail)，带透明度 |
| 按 Site 着色 | 8 色调色板按测试站点分组着色 |
| 判定参数 | 可选择单参数判定或全部参数全局判定 |
| **晶圆圆形边界** | 虚线圆圈模拟晶圆边缘，含底部 Notch 缺口标记 |
| Notch 标记 | 底部小缺口角标（圆周离散点） |
| **Tooltip 详情** | 悬停显示 X/Y 坐标 + Serial/Bin/Site/Value/Result |
| 图例过滤 | 可隐藏 Wafer Edge，保留 Pass/Fail 或 Site 分组 |
| 缩放/平移 | ECharts dataZoom（内置缩放+滑动条） |
| 工具箱 | 保存图片 / 区域缩放 / 还原 |
| Yield 统计 | 标题栏显示 Total/Pass/Fail/Yield% |
| 高度可调 | 滑块控制图表高度（400-900px） |
| 按需加载 | 用户点击"加载晶圆图"按钮才触发计算 |

### 4.3 相关性分析 (`_render_correlation_analysis`)

| 功能 | 说明 |
|------|------|
| **Pearson 散点图** | 选择 X/Y 两个测试项，按 Site 分组着色 |
| 相关系数 | Pearson r 值显示在标题副标题 |
| **坐标轴范围控制** | 3 种模式：数据分布(5%扩展) / 西格玛(3/4/6σ) / 自定义范围 |
| 相关性矩阵 | 所有有 Limit 测试项的 pearson 相关系数矩阵表 |
| 数据指标 | 相关系数 / 数据点数 |

### 4.4 多 Lot 对比分析

| 功能 | 说明 |
|------|------|
| 文件选择 | 多选已有文件（最多 5 个），< 2 个时提示 |
| **共同测试项** | 自动计算所选文件的所有共同数值测试项 |
| 参数导航 | 上下按钮在共同参数间切换 |
| **多 Lot 直方图** | 各 Lot 数据按共同 bins 叠加条形图对比 |
| 统计摘要表 | 每 Lot 的 Count/Mean/STD/Min/Max/Yield/Fail |
| CPK 和规格限 | 复用单 Lot 的图表配置 |
| 数据缓存 | `multi_lot_cache` 避免重复解析 |

---

## 五、数据浏览与导出 (`src/pages/data_management.py`, `src/export/export.py`)

### 5.1 数据浏览 Tab

| 功能 | 说明 |
|------|------|
| **AgGrid 表格** | 企业级数据表格，显示行数，Fail 单元格自动标红 |
| 列名搜索 | 关键词筛选显示列 |
| 测试项搜索 | 按列名筛选单列 |
| Pass/Fail 筛选 | 仅显示 Pass / Fail / 全部行 |
| 列宽自适应 | 适应内容宽度 / 适应网格宽度 / 手动调整 |
| 固定列 | 输入列名将列钉在左侧 |
| Fail 检测 | 首次加载时缓存 Fail 行/列/单元格映射，切换 Pass/Fail 无需重算 |
| 表头增强 | 列头含 Unit + [Min, Max] 信息 |
| 表头字号 | 可配置（用户设置）|

### 5.2 数据导出

| 功能 | 说明 |
|------|------|
| **Excel 导出（带统计 + Fail 标红）** | `export_to_xlsx_optimized`：原始数据 Sheet（Fail 行/单元格红色），统计 Sheet（CPK 颜色分级） |
| CSV 导出 | UTF-8-BOM 编码，可选保留文件头部信息、格式匹配 |
| Site 筛选导出 | 按指定 Site 过滤后导出 |
| Pass/Fail 筛选导出 | 仅导出 Pass 或 Fail 行 |
| 保留头部信息 | CSV 导出时保留原始 Limit/Units 等头部 |
| 格式匹配 | 自动匹配原始文件列名和顺序 |

### 5.3 Batch 批量导出

| 功能 | 说明 |
|------|------|
| **批量分布图 Excel** | 多参数直方图批量导出到单 Excel（xlsxwriter + Matplotlib 嵌入图片） |
| **批量分布图 PPT** | 多参数直方图批量导出到 PPT（python-pptx） |
| 图表类型可选 | 分布直方图 / 均值柱状图 |
| Sigma Limit Excel | 按 3/4/6 Sigma 导出测试项 Limit 规格表 |

---

## 六、Buyoff Form (`src/buyoff/buyoff.py`)

| 功能 | 说明 |
|------|------|
| 角色分配 | 为每个文件分配 FT / QA1 / QA2 角色 |
| 共同测试项识别 | 自动识别所选文件中共同的测试项 |
| 部分共有项 | 识别只在部分文件中存在的测试项 |
| 独有测试项 | 识别每个文件独有的测试项 |
| **Buyoff Form Excel** | 生成多 Sheet Excel：摘要表 + 每角色独立 Sheet |
| 测试项统计 | 每测试项的 Count / Mean / STD / Cpk / Min / Max / FailCount / Yield% |
| CPK 颜色编码 | A(绿) / B(浅绿) / C(黄) / D(红) 条件着色 |
| **多文件对比表格** | 横向对比各角色（FT/QA1/QA2）在同一测试项上的 Mean/Cpk/FailCount |
| Bin 1 过滤 | 可选只保留 Bin=1 数据 |
| Fail 检测提示 | 生成前检测 Fail 数据并警告用户 |
| 摘要面板 | 共同/部分共有/独有测试项数量指标 |

---

## 七、Gage Summary (`src/gage/gage.py`)

| 功能 | 说明 |
|------|------|
| **多 Site 分配** | 8 个 Site 槽位 (_S1~_S8)，每个可选择文件 |
| Gage 规则解析 | 从 CSV 文件头解析 Gage 测试项和 Limits |
| **多 Sheet Excel** | 每站点/每测试项生成统计 Sheet |
| 站点数据过滤 | 按指定 Site 列过滤 |
| 统计指标 | Count / Mean / STD / Min / Max / Range / Cpk |
| 限制线 | LSL / USL 标线 |
| Bin 1 过滤 | 可选只分析 Bin1 数据 |
| Ignore No Limit | 可选忽略无 Limit 的测试项 |
| 进度条 | 处理过程显示进度 |

---

## 八、SFTP 浏览器 (`src/sftp/sftp.py`)

| 功能 | 说明 |
|------|------|
| 连接管理 | 主机/IP + 端口 + 用户名 + 密码 + 根路径，连接测试按钮 |
| 多配置管理 | 保存/加载/删除 SFTP 连接配置（JSON 文件） |
| **远程文件浏览器** | 递归展开目录树，显示文件名+大小+修改时间 |
| 文件下载 | 带进度条的单文件下载 |
| **目录批量下载** | 整个目录 ZIP 打包下载 |
| **下载并解析** | 远程文件直接下载到内存并解析为 DataFrame |
| 目录下载到本地 | 远程目录递归下载到本地目录，维护子目录结构 |
| 本地解析 | 本地化后调用 parse_data_file 解析 |
| 带进度回调 | `_download_file_with_progress` 使用 `SFTPClient.getfo` + 自定义回调更新进度 |
| Session State 管理 | SFTP 连接状态（host/port/username/password）保存在 session_state |

---

## 九、系统设置 (`src/pages/settings_page.py`, `src/core/settings_manager.py`)

| 功能 | 说明 |
|------|------|
| 每页显示行数 | 50/100/200/500 |
| 图表高度 | 300-800px 滑块 |
| 表格高度 | 500-1000px 选择 |
| 表头字号 | 8-18px 滑块 |
| 图表渲染引擎 | 交互式 ECharts / 静态 Matplotlib 切换 |
| 图表 DPI | 72-600 滑块（仅 Matplotlib 生效） |
| **CPK 三级阈值** | A级(≥1.67) / B级(≥1.33) / C级(≥1.0)，联动约束 |
| 保存/恢复默认 | 保存到 JSON 文件，可一键恢复默认 |
| 用户级设置 | 每个用户独立的 `settings.json`，登录后加载 |
| 最近文件 | 自动记录最近使用文件列表 |

---

## 十、核心共享模块

### 10.1 数据解析 (`src/analysis/analysis.py`)

| 函数 | 说明 |
|------|------|
| `find_column_by_pattern` | 按模式查找列名（如 `site`/`serial`/`xcoord`/`ycoord`）|
| `get_site_column` / `get_serial_column` / `get_coord_columns` | 智能列检测 |
| `get_columns_with_limits` | 过滤有有效数值 Limit 的列（排除 N/A/min/max 等占位符）|
| `detect_fail_data` | **核心**：遍历所有列与 Limit 对比，缓存 Fail 行/列/单元格映射 |
| `calculate_fail_bin_statistics` | 按 Bin 统计各值数量和占比 |
| `calculate_fail_test_item_statistics` | 按测试项统计 Fail 次数和占比（降序） |
| `compute_range_statistics` | 计算 6 种范围（RDL/DR/CL/S3/S4/S6）的 Min/Max/Gap |
| `compute_cpk` | CPK 计算 + A/B/C/D 分级 |
| `compute_histogram_bins` | 基于 Limit 范围计算 25 个 histogram bins |
| `compute_site_histogram_data` | 按 Site 分组计算 histogram 百分比 |
| `compute_wafer_fail_data` | 生成 Wafer Pass/Fail 掩码 + 统计 |
| `compute_site_yield_data` | Site × Bin 良率分析（含最高/最低/差异）|
| `compute_multi_lot_chart_data` | 多 Lot 对比数据聚合 |
| `parse_data_file` | 入口：自动识别格式 → 分派解析器 |
| `parse_data_file_generic` | 通用解析：读取头部(Units/Mins/Maxs) → pd.read_csv → 类型转换 → 提取 Program Name |
| `identify_data_format` | 从文件头识别 4 种 ATE 格式 |

### 10.2 图表构建 (`src/view/chart_builders.py`)

| 函数 | 说明 |
|------|------|
| `_build_histogram_chart` | 构建 ECharts 直方图 option（bar + markLine + 正态曲线 + 双 Y 轴）|
| `_build_serial_series` | 构建 Serial 序列散点图数据（Site 分组 + 连续 Serial 补全）|
| `_build_mark_series` | 构建 LSL/USL/σ线 markLine 数据 |

### 10.3 Matplotlib 渲染 (`src/view/mpl_renderer.py`)

| 函数 | 说明 |
|------|------|
| `render_mpl_histogram` | Matplotlib 直方图（Site 分组 + 规格线 + 正态拟合）|
| `render_mpl_serial_scatter` | Matplotlib 序列散点图 |
| `render_mpl_pie` | Matplotlib 饼图 |
| `render_mpl_bar` | Matplotlib 柱状图 |
| `render_mpl_boxplot` | Matplotlib 箱线图 |
| `render_mpl_multi_histogram` | Matplotlib 多 Lot 对比直方图 |

### 10.4 导出模块 (`src/export/export.py`)

| 函数 | 说明 |
|------|------|
| `export_to_xlsx_optimized` | Excel 双引擎导出（excelize Go 绑定 + openpyxl 回退），含统计 Sheet 和 Fail 标红 |
| `export_sigma_limit_excel` | Sigma Limit 规格表导出 |
| `export_batch_distribution_chart_excel` | 批量分布图到 Excel/PPT（Matplotlib 生成图表嵌入）|
| `_create_bar_chart` / `_create_histogram_chart` | Matplotlib 图表生成 |
| `_export_charts_to_pptx` | 批量图表 → PowerPoint |
| `_export_charts_to_xlsx` | 批量图表 → Excel |

### 10.5 批次报表 (`src/export/batch_report.py`)

| 功能 | 说明 |
|------|------|
| `PhaseSummary` | Phase 数据结构：Phase / LotID / StartTime/EndTime / 良率 / Site 分组 / Bin 信息 |
| `parse_csv_for_summary` | 解析单个 CSV 文件提取 Phase 统计 |
| `scan_batch_directories` | 扫描批次目录结构（批次→子批次→Phase）|
| `gather_batch_report` | 聚合生成 `BatchReport` |
| `generate_batch_report_excel` | 生成多 Sheet Excel：批次总览 + Bin 分布 + Site 良率对照 |

### 10.6 HTML 报表 (`src/export/dashboard_html.py`)

| 功能 | 说明 |
|------|------|
| `generate_single_file_html` | 生成自包含 HTML（Plotly CDN + 数据表格 + 元信息）|
| `generate_batch_report_html` | 批次报表 HTML |

### 10.7 核心工具 (`src/core/utils.py`)

| 功能 | 说明 |
|------|------|
| 颜色常量 | COLORS_SITE_8 / COLORS_SERIAL_8 / COLORS_BIN_10 / COLORS_WAFER_SITE_8 / COLORS_PIE_10 |
| Excel 样式常量 | HEADER_FILL / RED_FILL / GREEN_FILL / YELLOW_FILL / FAIL_FILL 等 |
| 图表颜色常量 | COLOR_LSL / COLOR_USL / COLOR_SIGMA_3/4/6 / COLOR_NORMAL |
| 数据工具 | `get_1d` / `get_1d_from` / `ensure_numeric` / `safe_int` / `safe_float` |
| 路径工具 | `get_project_root` / `get_data_dir` |

### 10.8 应用入口与打包 (`main.py`)

| 功能 | 说明 |
|------|------|
| PyInstaller 打包 | 检测 `sys.frozen` 判断是否为打包环境 |
| 配置文件加载 | `app_config.json` → 合并默认配置 |
| Data/Logs 目录 | 自动创建 |
| Streamlit 参数 | headless 模式、端口 8501 |

---

## 十一、测试体系 (`tests/`)

| 文件 | 说明 |
|------|------|
| `conftest.py` | 测试夹具配置 |
| `test_analysis.py` | 数据解析/统计分析测试 |
| `test_chart_builders.py` | ECharts option 构建测试 |
| `test_core_core.py` | 核心模块测试 |
| `test_core_utils.py` | 工具函数测试 |
| `test_core_version.py` | 版本模块测试 |
| `test_export.py` | 导出模块测试 |
| `test_history.py` | 解析历史测试 |

---

## 十二、技术特色总结

| 特色 | 说明 |
|------|------|
| **双图表引擎** | ECharts（交互式）+ Matplotlib（静态导出），用户可切换 |
| **Range 类型系统** | 6 种范围模式切换（RDL/DR/CL/3σ/4σ/6σ），含 DataGap 对比 |
| **Fail 检测缓存** | `st.cache_data` 缓存 Fail 行/列/单元格，Pass/Fail 筛选无需重算 |
| **晶圆图** | ECharts scatter 模拟 Wafer Map，rect symbol + 圆形边界 + Notch |
| **AgGrid 集成** | Fail 单元格自动标红（JsCode cellStyle），列头含 Limit 信息 |
| **CPK 四级分级** | A(≥1.67)/B(≥1.33)/C(≥1.0)/D，颜色编码 |
| **分批解析** | `parse_data_file_cached` 缓存解析结果，避免重复 IO |
| **PerfTimer** | 上下文管理器记录关键路径性能，输出日志 |
| **用户隔离** | 用户级文件目录+设置+SFTP 凭据，管理员可概览全用户 |
| **自适应编码** | 文件读取尝试多编码（utf-8/gbk/latin-1）|
| **空值安全** | `get_1d_from` 处理 DataFrame/Series 二义性，`safe_float` 回退 |
| **excelize + openpyxl 双引擎** | 性能与样式兼顾的 Excel 导出 |
| **WAL SQLite** | 多线程安全，支持并发读写 |
