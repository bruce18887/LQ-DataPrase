# quest.txt 需求实施计划

> 任务 ID: `0607-2w2f` ｜ 来源: `quest.txt` 5 条需求
> 已确认决策: 1=后端+加密 / 3=全部4图表 / 4=仅新上传采集mtime / 5=分页+搜索+产品分组+批量删除

---

## 需求1：SFTP 配置安全修复 + 自定义命名

**现状（安全漏洞）**：密码以**明文**存在浏览器 `localStorage`（`SftpConnectionPanel.vue:122-124`）；后端 `configs`/`save_config` 为空桩（`apps/sftp/views.py:464-470`），无模型。

**方案：迁移到后端 + 加密存储**

### 后端
- [ ] `apps/sftp/models.py` 新增 `SftpConfig` 模型：`owner(FK User)`、`name`、`host`、`port`、`username`、`password_encrypted`、`created_at`、`updated_at`；`unique_together=(owner, name)`（每用户名称唯一）
- [ ] 新增 `apps/sftp/crypto.py`：基于 `cryptography.Fernet`，密钥从 `settings.SFTP_CONFIG_KEY`（派生自 `SECRET_KEY` 或独立环境变量）读取；`encrypt()/decrypt()`
- [ ] `apps/sftp/serializers.py` 新增 `SftpConfigSerializer`：`password` 只写不读（write_only），列表/详情不返回明文密码
- [ ] 重写 `apps/sftp/views.py` 的 `configs`(GET 列表)、`save_config`(POST 创建/更新)，新增 `delete_config`/`load_config`；全部 `queryset.filter(owner=request.user)` 强制按用户隔离
- [ ] `apps/sftp/migrations/` 新增迁移
- [ ] `requirements/base.txt` 显式加入 `cryptography>=42`（当前 48.0.0 已随 paramiko 安装）

### 前端
- [ ] `SftpConnectionPanel.vue`：删除 localStorage 读写，改调 `sftpApi.getConfigs/saveConfig/deleteConfig`（`api/sftp.ts:53-58` 已定义未用）
- [ ] 命名输入：将 `prompt()` 替换为正式的 `el-dialog` + `el-input`（用户自定义命名，校验非空/重复）
- [ ] 加载配置时密码不回显（后端不返回），连接时需用户补填或后端代连
- [ ] dark/light 双主题适配新对话框

### 测试
- [ ] 后端单测：未登录拒绝、用户A不能读/改用户B配置、密码加密存储不落明文
- [ ] e2e：保存配置→列表显示→加载→删除

---

## 需求2：侧边栏菜单顺序

**现状**：`Sidebar.vue:82-91` 数组顺序为 仪表板/数据管理/**SFTP/数据分析**（后两项颠倒）。

- [ ] `Sidebar.vue` 调换 `/analysis` 与 `/sftp` 两项顺序 → 仪表板、数据管理、数据分析、SFTP浏览器
- [ ] （可选）同步 `router/index.ts` 路由声明顺序，保持一致
- [ ] e2e：断言菜单顺序

---

## 需求3：批次报表复用单文件分析图表（全部4个）

**目标**：批次报表 `BatchYieldTab.vue` 的【Bin 分布】【Site 通过率】→ 替换为
【Site 良率分布 & Yield 分析】+【Bin × Site 交叉表】+【Bin × Site 柱状图】+【UPH 效率分析】。

**复用评估**：`SiteYieldAnalysis.vue`、`BinSiteCrossTable.vue`(含交叉表+柱状图)、`UphCard.vue`(已支持 `uphData` 批次模式) 均可复用。

### 后端 `apps/batch_report/views.py` (`batch_yield_data`)
- [ ] 新增**批次级 Bin×Site 聚合**：累加各 `phases[].bin_info[].sites` → 生成 `bin_table_data` + `bin_site_columns`（复刻单文件 `apps/dashboard/views.py:compute_bin_site_table`）
- [ ] 新增**批次级 UPH 聚合**：汇总各 `phases[].uph`（总测试数、总耗时 → 整体 UPH + by_site）输出单个 `UphData`
- [ ] `site_pass_data` 已有，前端转换即可（无需后端改）

### 前端 `BatchYieldTab.vue`
- [ ] 移除 `AggregatedBinChart` + 内联 `renderSiteChart`
- [ ] 引入 `SiteYieldAnalysis`：转换 `site_pass_data`→`{Site,Yield,Total,PassCount}`
- [ ] 引入 `BinSiteCrossTable`：绑定后端新增 `bin_table_data`/`bin_site_columns`
- [ ] 引入 `UphCard`：以 `uphData` 传入批次聚合结果
- [ ] 检查文件行数（`BatchYieldTab.vue` 现 516 行），逼近 600 行需拆子组件
- [ ] dark/light 双主题校验

### 测试
- [ ] 后端单测：bin×site 聚合数值正确（与逐phase求和一致）
- [ ] e2e：批次报表渲染4个新图表

---

## 需求4：文件列表强化（原始mtime + 产品分类）

**现状**：`DataFile` 模型只有 `created_at`（上传时间），**无原始文件 mtime**；无产品码提取。文件名确认含 `B*_` 前缀（BPD60320/BN281/BPC50338）。
**决策**：mtime 仅新上传采集，历史文件该列留空。

### 后端
- [ ] `DataFile` 模型新增 `source_mtime`(DateTimeField, null=True)
- [ ] `FileUploadView`(`apps/datafiles/views.py:175-225`) 上传时采集源文件 mtime 写入（注意浏览器上传拿不到原始 mtime → 从前端传 `lastModified`；解压归档文件用磁盘 mtime）
- [ ] 新增**产品码提取**工具：正则 `^(B[A-Z0-9]*)_` 从 filename 提取 → 存 `product_code` 字段（新增）
- [ ] `DataFileListSerializer` 增加 `source_mtime`、`product_code`
- [ ] 列表接口支持按 `product_code` 过滤（`filterset_fields`）
- [ ] 迁移文件

### 前端 `DataManagement.vue`
- [ ] 文件列表新增列：原始修改时间（`source_mtime`，空显示「—」）
- [ ] 新增产品分类：按 `product_code` 分组展示 或 顶部下拉筛选
- [ ] dark/light 双主题

### 测试
- [ ] 产品码提取单测（各样例文件名）
- [ ] e2e：列表显示 mtime 列 + 产品筛选

---

## 需求5：大量文件的上传/列表管理（分页+搜索+产品分组+批量删除）

**现状**：列表无分页UI、无搜索、无筛选（后端 `PageNumberPagination`/`SearchFilter` 已具备，前端 `/files/` 一次性全拉）。

### 后端 `apps/datafiles/views.py` (`DataFileViewSet`)
- [ ] 配置 `search_fields=['filename','batch_name','program_name']`、`filterset_fields=['product_code','format_type','file_type']`、`ordering_fields`
- [ ] 新增**批量删除**动作 `@action bulk_delete`（接收 id 列表，按 owner 校验，删 DB 记录 + 磁盘文件）

### 前端 `DataManagement.vue`
- [ ] 文件列表接入分页控件（`el-pagination`，分页参数传后端）
- [ ] 顶部搜索框（按文件名，防抖）
- [ ] 产品分组/筛选下拉（与需求4联动）
- [ ] 表格多选 + 批量删除按钮（二次确认）
- [ ] 文件行数监控（现 586 行）→ 接近 600 行拆出 `FileListTab` 子组件
- [ ] dark/light 双主题

### 测试
- [ ] 后端单测：bulk_delete 仅删自己的、删除同时清磁盘
- [ ] e2e：搜索/分页/筛选/批量删除全流程

---

## 执行顺序建议

1. **需求2**（最简，独立）→ 立即可做
2. **需求4 + 需求5**（同属数据管理，模型/序列化器/列表页耦合，合并实施减少冲突）
3. **需求1**（SFTP 独立模块，前后端联动）
4. **需求3**（批次报表，后端聚合 + 前端组件复用，工作量最大）

> 约束遵守：单文件 ≤600 行（BatchYieldTab/DataManagement 需关注拆分）；测试放 test 目录；所有改动维护 e2e 与 dark/light 双主题。

---

## 进度

- [x] **需求2 侧边栏顺序** — 完成。`Sidebar.vue:82-91` 调换 analysis/sftp；router 同步；e2e 加断言（`global.spec.ts`）。type-check 通过。
- [x] **需求4+5 数据管理** — 完成。
  - 后端：`DataFile` 加 `source_mtime`/`product_code`；`utils.extract_product_code`；迁移 0004（product_code 回填，mtime 不回填）；上传采集 mtime（归档磁盘 mtime + 浏览器 `last_modified`）；ViewSet `search_fields`/`filterset_fields`/`ordering_fields` + `bulk_delete` + `product_codes` 动作。8 个单测通过。
  - 前端：`api/datafiles.ts` 加 `listFiles/bulkDelete/getProductCodes` + 上传带 `last_modified`；拆出 `FileListTab.vue`(406行) 含分页/搜索/产品筛选/多选批量删除；新增 产品/原始修改时间 列；dark/light 用 CSS 变量；e2e `data/data.spec.ts` 5 用例。type-check 通过，所有文件 <600 行。
- [x] **需求1 SFTP 安全** — 完成。
  - 后端：新增 `SftpConfig` 模型 + `crypto.py`(Fernet, 密钥优先 `SFTP_CONFIG_KEY` 否则 PBKDF2 派生自 SECRET_KEY) + `SftpConfigSerializer`(password write_only, 返回 has_password) + `config_views.py` mixin；`configs`/`save_config`/`delete_config` 全部 owner-scoped；`connect` 支持 `config_name`/`config_id` 服务端解密直连（密码不到浏览器）。15 单测通过。
  - 前端：`api/sftp.ts` 加 `deleteConfig` + connect 支持 config_name；`SftpConnectionPanel.vue` 删除 localStorage、改 el-dialog 自定义命名、has_password 锁标签、空密码用已存配置直连。无 localStorage 残留。258 行。
- [x] **需求3 批次报表 4 图表** — 完成。
  - 后端：`apps/batch_report/aggregation.py`(新) `aggregate_bin_site_table`+`aggregate_uph`；`batch_yield_data` 响应新增 `bin_table_data`/`bin_site_columns`/`uph`（向后兼容，旧 key 保留）。11 单测通过。
  - 前端：拆出 `batch/BatchAnalysisCharts.vue`(93行)，复用 `SiteYieldAnalysis`/`BinSiteCrossTable`/`UphCard`；`BatchYieldTab.vue` 516→441 行、移除旧 Bin分布+内联Site图；`UphCard.vue` 识别 `source==='batch'` 显示「批次汇总」标签。e2e `dashboard.spec.ts` 更新。

## Review

### 交付总览（全部 4 项需求完成，5 项 quest 条目）
| 需求 | 状态 | 测试 |
|---|---|---|
| 1 SFTP 安全+自定义命名 | ✅ | 21 后端单测 |
| 2 侧边栏顺序 | ✅ | e2e 断言 |
| 3 批次报表 4 图表 | ✅ | 11 后端单测 + e2e |
| 4 文件列表 mtime+产品分类 | ✅ | 8 后端单测 + e2e |
| 5 大量文件管理 | ✅ | （含于 4 的套件）+ e2e |

**最终验证**：后端 40 测试全过（`apps.sftp/datafiles/batch_report`）；前端 `vue-tsc --noEmit` 退出 0；迁移 `makemigrations --check` 无待生成；所有改动文件 <600 行。

### 代码审查结论（两路并行审查）
- **无 BLOCKING 问题**。SFTP owner 隔离在每条路径（含 connect 的 config_id/IDOR 路径）均已验证；密码不在任何响应/日志中出现；前端无 localStorage 密码残留；bin×site 与 UPH 聚合数学正确且与单文件实现一致。
- **已修**：save_config 增加服务端 port 范围校验(1..65535)，+6 测试。

### 已知遗留（先存问题/范围外，建议后续处理）
1. `connect` 把明文密码写入 Django cache 1 小时（先于本任务存在）——若 cache 换成共享 Redis 会落明文。建议存加密 token 或用服务端会话密钥。
2. 生产环境应设置真实 `SECRET_KEY` 与 `SFTP_CONFIG_KEY`（当前 SECRET_KEY 是 django-insecure 默认值；改 SECRET_KEY 会使已存密码无法解密——已优雅降级为 400）。
3. `extract_product_code` 的 `B[A-Z]{1,2}\d+` 可能把 `BF22_` 这类相位前缀误判为产品码（若产品码不含 BF 前缀可收紧）。
4. `BatchYieldTab.vue` 的 `exportExcel` 仍是占位（传数组索引而非真实 file_id），先于本任务存在。
5. `config/settings/__init__.py` 有一份精简的 REST_FRAMEWORK，与 base.py 分叉——当前激活的是 `development`(继承 base)，不影响功能，但若切到 `config.settings` 会丢失 SearchFilter/OrderingFilter。

### .gitignore 修复
`Data/` → `/Data/`（锚定根目录）。根 `Data/` 仍忽略，`frontend/src/pages/data/` 与 `frontend/e2e/data/` 不再被误忽略，`media/data` 由独立 `media/` 规则继续忽略。
