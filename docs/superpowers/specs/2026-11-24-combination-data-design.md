# 组合数据（实验室调试数据集）设计

日期：2026-11-24
状态：待用户复核
范围：数据管理、文件标签、上传/导入、文件选择、分析下拉

## 1. 背景与目标

当前“批次数据”页管理的是 ZIP/目录导入的物理批次，不是独立的业务实体。`DataFile.batch_name` 来自 ZIP 名或目录名；`tags` 是文件上的 JSON 列表；单文件上传接口当前不接收标签，上传后只能整列表覆盖标签。

用户需要的“组合数据”是实验室调试数据集，例如 `gage`、`buyoff` 或任意自定义名称。它不等同于批次：

- 一个文件最多属于一个组合；
- 组合中的文件可以没有批次号；
- 手动标签保留并与组合标签共存；
- 加入组合后自动显示组合名标签；
- 有批次号时自动显示“组合名 / 批次号”标签；
- 组合名可随时修改，系统标签立即同步；
- 组合不改变文件物理位置，不替代现有批次报表。

本设计的目标是建立稳定的结构化归属，同时让标签成为自动同步的展示与搜索投影，避免把组合名、目录批次和 LotID 混为一谈。

## 2. 现状证据

- `apps/datafiles/models.py:34-50`：`DataFile` 只有 `file_type`、`batch_name`、`sub_batch`、`metadata`、`tags` 等字段；`tags` 是 JSONField，没有独立 Tag 表。
- `apps/datafiles/views/_helpers.py:367-423`：ZIP 名去扩展名后成为 `batch_name`，不是 LotID。
- `apps/datafiles/parsers/cta8290d.py:7-18`：解析器已映射 `LotID`，但 `apps/datafiles/views/_helpers.py:113-171` 注册文件时没有持久化该值。
- `apps/datafiles/views/file_views.py:525-595`：上传入口只读取文件和 `last_modified`，不读取组合、批次号或标签。
- `apps/datafiles/views/file_views.py:471-489`：`set_tags` 是手动标签全量覆盖接口。
- `apps/datafiles/serializers.py:11-47`：手动标签每条最长 50 字符、最多 20 条，大小写不敏感去重。
- `apps/batch_report/services.py:100-115`：批次报表严格按 `owner + file_type='batch' + batch_name` 查询。
- `apps/gage/views.py:37-119`、`apps/buyoff/views.py:63-144`：Gage/Buyoff 是临时多文件报表动作，分别还需要 Site 分配和角色映射。
- `frontend/src/pages/data/DataManagement.vue:199-207`：当前 Tab 名为“批次数据”。
- `frontend/src/pages/data/components/BatchDataTab.vue:45-146`：当前页面按物理目录分组，不区分组合、LotID 和手动标签。
- `frontend/src/components/common/fileSelectModel.ts:23-39`：文件下拉只匹配文件名、程序名和 `batch_name`，不匹配标签。

## 3. 已确认的产品口径

| 决策点 | 结论 |
|---|---|
| 组合语义 | 实验室调试数据集，不等同于批次 |
| 组合名 | 用户自定义，可随时修改 |
| 文件归属 | 一个文件最多属于一个组合 |
| 批次号 | 可选；允许组合内存在无批次文件 |
| 手动标签 | 保留现有行为，与系统标签共存 |
| 系统标签 | 加入组合后自动生成，只读，不可手动删除 |
| 组合改名 | 系统标签自动同步，不修改手动标签 |
| 物理批次 | 保留 `batch_name/sub_batch` 与现有目录行为 |
| 报表 | 组合不自动生成或跳转 Gage/Buyoff/批次报表 |
| 存量数据 | 默认未分组，不自动猜测归属 |

## 4. 方案选择

### 4.1 不采用：把自动标签写入现有 `tags`

问题：

- `set_tags` 会整列表覆盖，系统标签会被误删；
- 系统标签占用手动标签 20 条额度；
- 组合改名需要批量重写文件标签；
- 手动标签与系统标签同名时无法区分来源；
- 组合名、目录批次和 LotID 仍然混用。

### 4.2 不采用：持久化独立 `managed_tags` 字段

问题：

- 组合改名仍需批量重写所有成员文件；
- 结构化字段与标签字符串形成双份事实来源；
- 需要额外处理批量更新失败、部分成功和一致性修复。

### 4.3 采用：组合表 + 可选批次号 + 动态系统标签

事实来源只有：

- `DataFile.combination`
- `DataFile.batch_no`

系统标签在序列化和筛选时动态计算：

```text
combination_name
combination_name / batch_no    # batch_no 非空时追加
```

优点：

- 组合改名后标签立即同步，无需批量更新文件；
- 手动标签仍只存于 `tags`，不受系统标签影响；
- 不需要解析标签字符串反推归属；
- 系统标签不占手动标签额度；
- 同一批次号位于不同组合时，系统标签仍可区分。

## 5. 数据模型

### 5.1 新增 `DataCombination`

```text
id
owner                  FK(User), CASCADE
name                   CharField(max_length=40)
name_key               CharField(max_length=80)
description            TextField(blank=True, default='')
created_at             auto_now_add
updated_at             auto_now
```

约束与规则：

- `name` trim 后必填，禁止纯空白、控制字符以及 `/`、`\`；
- `name_key = name.casefold()`，同一 owner 下唯一；
- 保留用户输入的大小写用于展示；
- 组合名允许空格、中文、连字符和下划线；
- `UniqueConstraint(fields=['owner', 'name_key'])` 保证大小写不敏感唯一；
- 模型 `save()` 统一维护 `name/name_key`，避免不同入口产生不一致数据。

### 5.2 `DataFile` 新增字段

```text
combination            FK(DataCombination, null=True, blank=True, SET_NULL)
batch_no               CharField(max_length=40, blank=True, default='')
```

规则：

- `combination=None` 表示未分组；
- `batch_no` trim 后保存，允许为空，禁止控制字符以及 `/`、`\`；
- 显式传入非字符串批次号返回 400；parser metadata 中的非字符串 LotID 视为空值；
- `batch_no` 保留大小写，筛选和分组按大小写不敏感；同一组合内的大小写变体视为同一批次，展示首次出现的写法；
- `batch_no` 不参与文件路径、`file_type` 或批次报表成员判定；
- 删除组合只将 `combination` 置空，不删除文件，也不清空 `batch_no`；
- 移动组合默认保留 `batch_no`；
- `batch_name` 继续表示来源 ZIP/目录批次。

### 5.3 索引

- `DataCombination(owner, name_key)` 唯一约束；
- `DataFile.combination` 使用 FK 自带索引；
- `DataFile.batch_no` 增加 `db_index=True`，服务组合内批次筛选与分组。

### 5.4 动态标签规则

```text
managed_tags(datafile):
    if datafile.combination is None:
        return []

    tags = [datafile.combination.name]
    if datafile.batch_no:
        tags.append(f"{datafile.combination.name} / {datafile.batch_no}")
    return tags
```

组合名最长 40 字符、批次号最长 40 字符，因此系统批次标签最长 83 字符；该标签不受手动标签 50 字符限制，UI 可省略显示并保留完整 tooltip。

展示规则：

- `tags`：手动标签，可编辑、可删除；
- `managed_tags`：系统标签，只读；
- 前端合并展示时大小写不敏感去重；若手动标签与系统标签同名，显示系统标签标识，但删除手动标签不影响系统标签。

## 6. 序列化与查询契约

### 6.1 文件序列化

`DataFileSerializer` 和 `DataFileListSerializer` 增加：

```text
combination_id
combination_name
batch_no
managed_tags
```

其中：

- `combination_id/combination_name/batch_no` 来自结构化字段；
- `managed_tags` 是 read-only `SerializerMethodField`；
- 现有 `tags` 含义不变，仍只表示手动标签；
- `set_tags` 响应保持 `{id, tags}`，不改变现有契约。

查询文件列表时必须 `select_related('combination')`，避免逐行访问组合名产生 N+1。

### 6.2 文件列表筛选

`GET /api/v1/files/` 增加：

```text
?combination_id=<positive int>
?batch_no=<string>
```

规则：

- `combination_id` 非法值返回 400 `validation_error`；
- `batch_no` trim 后大小写不敏感精确匹配；
- 参数可与其他现有筛选组合；
- 隐藏文件规则保持不变。

### 6.3 标签搜索与精确筛选

`?tag=` 和 `search=` 必须同时匹配：

- 手动 `tags`；
- 动态组合名标签；
- 动态“组合名 / 批次号”标签。

实现要求：

- 抽公共纯函数，根据 `tags/combination_name/batch_no` 计算命中；
- 不得通过解析标签字符串反推组合或批次；
- 标签搜索只能作用于当前 queryset。

必须同批修复现有缺陷：`apps/datafiles/views/file_views.py:118-143` 的标签搜索通过 OR 重新查询 owner 下全部文件，会绕过此前的文件类型、组合、隐藏等筛选。修复为从当前 queryset 取候选 id，再 `filter(id__in=...)`。

### 6.4 标签联想

`POST /api/v1/files/list_tags/` 返回：

```json
{
  "tags": ["gage", "gage / BE01-2608130015", "manual-tag"],
  "managed_tags": ["gage", "gage / BE01-2608130015"]
}
```

规则：

- `tags` 保持原有字符串列表形态，返回手动标签与系统标签的并集；
- 新增 `managed_tags` 子集，供前端显示锁标识；
- 仍排除隐藏文件贡献的标签；
- 前缀匹配大小写不敏感；
- 前端禁止把 `managed_tags` 中的值再次添加为手动标签。

### 6.5 文件下拉 DTO

`GET /api/v1/files/options/` 增加标量字段：

```text
combination_id
combination_name
batch_no
```

不返回完整 `tags/managed_tags`，避免把最多 20000 项下拉响应放大。

前端 `FileSelect`：

- 匹配文件名、程序名、`batch_name`、组合名、批次号；
- 富信息行展示“组合名 · 批次号”；
- 现有虚拟滚动和 5000/20000 上限不变。

### 6.6 批次目录 DTO

`GET /api/v1/batch-dirs/` 的每个文件增加：

```text
combination_id
combination_name
batch_no
managed_tags
```

批次头展示规则：

- 所有文件属于同一组合时显示该组合名；
- 属于多个组合时显示“多个组合”；
- 未分组时显示“未分组”；
- 物理 `batch_name` 仍作为来源批次展示。

## 7. 组合 API

### 7.1 列表与创建

```text
GET  /api/v1/combinations/
POST /api/v1/combinations/
```

列表返回当前 owner 的全部组合，按名称排序；文件计数包含隐藏文件，因为这是管理面：

```json
[
  {
    "id": 1,
    "name": "gage",
    "description": "实验室调试",
    "file_count": 12,
    "batched_file_count": 8,
    "unbatched_file_count": 4,
    "created_at": "...",
    "updated_at": "..."
  }
]
```

创建请求：

```json
{"name": "gage", "description": "实验室调试"}
```

错误：

- 名称为空：400 `combination_name_required`；
- 同名组合已存在：400 `duplicate_combination`；
- 超过长度或含控制字符：400 `validation_error`。

### 7.2 重命名与删除

```text
PATCH  /api/v1/combinations/{id}/
DELETE /api/v1/combinations/{id}/
```

重命名：

- 只更新组合行；
- 文件上的 `managed_tags` 由序列化器实时重算；
- 不修改文件的 `tags`、`batch_no` 或 `updated_at`；
- 前端刷新组合列表和当前文件列表。

删除：

- 返回 204；
- 数据库将成员文件的 `combination` 置空；
- 不删除文件、不移动物理目录、不清空手动标签和 `batch_no`；
- 当前组合页面回到“未分组”或组合列表。

### 7.3 批量归组

```text
POST /api/v1/files/assign_combination/
```

请求：

```json
{
  "file_ids": [1, 2, 3],
  "combination_id": 1,
  "batch_no": "BE01-2608130015"
}
```

规则：

- `file_ids` 必须是非空整数列表；
- 所有文件必须存在且属于当前 owner，否则整体 404，不部分成功；
- `combination_id=null` 表示取消组合归属；
- `batch_no` 缺省表示保留原值；
- `batch_no=null` 或空字符串表示清空；
- 字符串表示设置新值；
- 一个数据库事务内完成；
- 返回更新后的文件列表。

## 8. 上传与导入

### 8.1 单文件与 ZIP 上传

`POST /api/v1/upload/` 增加可选表单字段：

```text
combination_id
batch_no
tags              # JSON 字符串数组
```

兼容规则：

- 不传这些字段时保持现有行为；
- `tags` 使用现有 `normalize_tags`，仍是手动标签；
- 非法 JSON、非法组合 id、非法标签均在任何文件写入前返回 400；
- 响应仍为 201 + `DataFile[]`，不改变现有客户端契约；
- 解析失败的文件仍以 `status='error'` 行返回。

### 8.2 批次号解析优先级

新导入文件按以下优先级确定 `batch_no`：

1. 用户显式填写；
2. parser metadata 中的 `lot_id`；
3. 空字符串。

禁止自动把 ZIP 名或目录名当作批次号。ZIP 名可以在界面中作为“建议值”，但必须由用户确认。

### 8.3 注册服务

扩展 `_register_file`：

```text
combination=None
batch_no_override=''
tags=None
```

处理：

- 手动标签归一化后写入 `tags`；
- 组合归属写入 `combination`；
- `batch_no_override` 非空时优先，否则使用 `metadata.lot_id`；
- 只持久化批次号，不额外持久化完整 metadata；
- ZIP、目录、SFTP 下载目录和单文件上传共用同一注册服务。

### 8.4 重传与幂等

当前导入按规范化路径跳过已注册文件。增强后：

- 已注册路径不重复插入；
- 请求携带 `combination_id` 时更新该文件的组合归属；
- 显式 `batch_no` 覆盖原值；
- 未显式传批次号时，仅当原 `batch_no` 为空才用新解析出的 LotID 回填；
- 上传携带手动标签时做大小写不敏感并集合并，不删除原手动标签；
- 系统标签始终由结构化字段动态计算。

### 8.5 SFTP 未导入目录

“SFTP 下载目录（未导入）”卡片保留。点击导入时：

1. 选择或新建组合；
2. 可填写批次号覆盖值；
3. 调用现有目录导入链路；
4. 导入成功后刷新组合页。

### 8.6 现有“组合为批次”

现有 `files/combine/` 继续负责物理移动和 `file_type/batch_name` 变更。

增强：

- 对话框增加可选“加入组合”；
- 选择组合时可同时填写可选批次号；
- 不选择组合时保持现有行为；
- `uncombine` 只撤销物理批次归属，不清除逻辑组合和 `batch_no`。

## 9. 前端设计

### 9.1 Tab 与信息架构

数据管理 Tab 展示名由“批次数据”改为“组合数据”。

本版本保留内部 key `batch` 和现有批次目录 testid，减少无关注册与状态扰动；新增组合相关 testid 使用 `combination-*`。

页面结构：

```text
组合工具栏：选择 / 新建 / 重命名 / 删除
组合汇总：文件数 / 有批次数 / 无批次数
有批次文件：按 batch_no 分组
无批次文件：单独列表
来源批次目录：保留现有 SFTP 未导入目录和批次目录管理
```

### 9.2 组件拆分

为满足 600 行约束，不在现有大组件上持续堆叠：

- 新增 `CombinationDataTab.vue` 作为组合页壳；
- 新增 `CombinationToolbar.vue`；
- 新增 `CombinationFileGroups.vue`；
- 将现有目录管理抽为 `BatchDirectorySection.vue`；
- 新增 `FileTagsCell.vue`，统一渲染手动标签和系统标签；
- 扩展现有 `BatchFilesTable.vue` 展示组合、批次号和标签。

### 9.3 标签展示

手动标签：

- 现有样式；
- 可关闭、可新增；
- 继续受 20 条限制。

系统标签：

- 带锁标识；
- 不可关闭；
- tooltip 显示“由组合名/批次号自动维护”；
- 组合改名或批次号修改后自动刷新；
- 不占手动标签额度。

### 9.4 文件列表

文件列表增加：

- 组合列或组合徽标；
- 批次号列；
- 标签列同时展示手动与系统标签；
- 工具栏增加组合筛选；
- 搜索命中组合名或批次号。

### 9.5 上传交互

文件列表上传区增加可选“导入设置”：

- 组合；
- 批次号；
- 手动标签。

组合数据页的上传区自动携带当前组合 id。未选择组合时仍允许普通上传，生成未分组文件。

### 9.6 Gage 与 Buyoff

组合页可提供显式按钮：

- “用当前组合打开 Gage 配置”；
- “用当前组合打开 Buyoff 配置”。

只回填成员文件，不自动生成报表，也不自动分配 Site 或角色。

### 9.7 双主题

新增组件只使用现有语义 token：

- `frontend/src/styles/design-tokens.css`
- `frontend/src/styles/element-plus-theme.css`

系统标签的锁标识、边框、悬停和禁用态必须在 light/night 两套主题下分别验证。

## 10. 权限与数据隔离

- 组合 CRUD 只允许当前 owner；
- 批量归组只允许当前 owner 的文件；
- 上传中的 `combination_id` 必须是当前 owner 的组合；
- 管理员跨用户文件列表仍沿用现有 `owner_id + data_view_all` 规则；
- 管理员只读文件页可展示组合名，但不获得组合写权限；
- 隐藏文件仍按现有规则从选择面排除；
- 组合列表是管理面，显示当前 owner 的全部组合，包括没有可见文件的组合。

## 11. 迁移策略

新增迁移 `0008_datafile_combination_batch_no`：

1. 创建 `DataCombination`；
2. 增加 `DataFile.combination`；
3. 增加 `DataFile.batch_no` 与索引；
4. 增加组合唯一约束。

不做自动数据回填：

- 存量文件 `combination=None`；
- 存量 `batch_no=''`；
- 存量手动标签不变；
- 存量批次报表不变。

后续提供“存量归组”向导：

- 选择文件或来源批次；
- 选择目标组合；
- 预览手动标签、系统标签和批次号；
- 确认后调用批量归组 API。

## 12. 错误处理

| 场景 | 响应 |
|---|---|
| 组合名为空 | 400 `combination_name_required` |
| 组合名重复 | 400 `duplicate_combination` |
| 组合不属于当前用户 | 404 |
| 批量归组包含非本人文件 | 404，整体不修改 |
| `combination_id` 非法 | 400 `validation_error` |
| 批次号超过 40 字符或含控制字符、`/`、`\` | 400 `validation_error` |
| 上传标签 JSON 非法 | 400 `validation_error` |
| 上传标签超过现有 20 条/50 字符限制 | 400，沿用现有错误信息 |

所有错误继续使用项目统一异常信封，不引入第二套错误格式。

## 13. 性能与一致性

- 文件列表和详情查询使用 `select_related('combination')`；
- `files/options` 只增加三个标量字段，不返回标签数组；
- 动态标签筛选沿用当前 JSON 标签筛选的 Python 候选集模式，不引入跨数据库 JSON 查询语法；
- 标签搜索修复为当前 queryset 内筛选，避免 OR 绕过；
- 组合改名不写文件表，避免大组合批量更新和 SQLite 长事务；
- 导入仍在事务外解析、事务内逐文件 INSERT，保持现有 SQLite 写锁边界；
- 重传只更新已有行的组合/批次元数据，不重复插入。

## 14. 验收标准

### 14.1 组合与标签

1. 创建组合 `gage` 成功，同名大小写变体返回 400。
2. 无批次文件加入 `gage` 后，`managed_tags=['gage']`。
3. 批次号为 `BE01-2608130015` 的文件加入 `gage` 后，`managed_tags=['gage', 'gage / BE01-2608130015']`。
4. 组合 `gage` 改名为 `gage-lab` 后，上述系统标签立即变化，文件 `tags/batch_no/updated_at` 不变。
5. 手动标签 `gage` 与系统标签 `gage` 共存；删除手动标签后系统标签仍存在。
6. 20 条手动标签加 2 条系统标签可以正常保存和展示。
7. 移动到其他组合后，旧组合系统标签消失，新组合系统标签出现，手动标签不变。
8. 删除组合后文件仍存在，`combination=None`，系统标签为空，手动标签和批次号保留。

### 14.2 导入

1. 单文件上传可不传组合、批次号和标签，行为与现状一致。
2. 单文件上传可同时携带组合、批次号和手动标签。
3. ZIP 中 parser 识别到 LotID 时自动写入 `batch_no`。
4. ZIP 未识别到 LotID 时 `batch_no` 为空，不把 ZIP 名伪造成批次号。
5. 同一 ZIP 含不同 LotID 时按文件分别保存。
6. 重传同一路径不重复插入，组合和批次元数据按规则幂等更新。
7. SFTP 未导入目录导入时可选择组合。
8. 现有“组合为批次”和批次报表行为不回归。

### 14.3 查询与权限

1. `combination_id` 与文件名、标签、隐藏状态等筛选可正确组合。
2. 标签搜索不能绕过组合筛选。
3. `tag=gage` 命中该组合全部成员。
4. `tag=gage / BE01-2608130015` 只命中对应组合和批次。
5. 非 owner 不能创建、修改、删除组合或归组他人文件。
6. 管理员跨用户只读文件列表能展示组合名，但不能修改。
7. 隐藏文件仍不出现在 `files/options` 和标签联想中。

### 14.4 前端

1. “组合数据”页可新建、选择、重命名和删除组合。
2. 有批次与无批次文件分区展示。
3. 手动标签可编辑，系统标签不可删除。
4. 组合改名后刷新当前文件列表即可看到系统标签同步；后端文件行无需更新。
5. 分析文件下拉可按组合名和批次号搜索。
6. light/night 双主题下标签、锁标识、空态和弹窗均可用。

## 15. 测试分层

### T1 后端契约

新增 `test/backend/test_combinations_api.py`：

- 组合 CRUD、唯一性、owner 隔离；
- 批量归组、清空批次号、取消归属；
- 动态系统标签与手动标签共存；
- 改名不写文件表；
- 删除组合不删除文件。

新增 `test/backend/test_combination_import.py`：

- 单文件上传携带组合/批次号/标签；
- ZIP LotID 自动识别；
- 无 LotID 不伪造批次号；
- 多 LotID ZIP；
- 重传幂等；
- 目录导入；
- 非法组合和标签在写文件前失败。

扩展现有文件查询测试：

- 组合筛选；
- 动态标签精确筛选；
- 搜索不绕过筛选；
- `list_tags` 返回系统标签；
- `files/options` 新增标量字段。

### T2 前端纯函数

新增 `frontend/test/unit/combinationTags.spec.ts`：

- 系统标签生成；
- 手动/系统标签合并去重；
- 组合改名和批次号变化；
- 无组合时返回空系统标签。

更新 `frontend/test/unit/fileSelectModel.spec.ts`：

- 组合名和批次号参与搜索；
- 不改变现有虚拟化匹配规模。

### T3 浏览器

新增 `frontend/e2e/data/combination-data.spec.ts`：

- 新建组合；
- 上传无批次单文件；
- 上传 ZIP 并识别批次号；
- 手动/系统标签共存；
- 组合重命名同步；
- 移动组合；
- 分析下拉按组合搜索；
- light/night 双主题。

T3 只保留关键接线证明，组合矩阵由 T1 完整覆盖。

## 16. 文件落点与 600 行约束

后端：

- `apps/datafiles/models.py`：新增组合模型和文件字段；
- `apps/datafiles/combination_service.py`：名称归一化、批次号解析、动态标签；
- `apps/datafiles/views/combination_views.py`：组合 CRUD 与批量归组；
- `apps/datafiles/serializers.py`：组合序列化器与文件只读字段；
- `apps/datafiles/views/_helpers.py`：注册链路接入；
- `apps/datafiles/views/file_views.py`：只做筛选和上传参数接线，新增逻辑继续外移。

当前 `file_views.py` 已 595 行，不能继续堆叠功能。

前端：

- `frontend/src/types/index.ts`：组合与文件类型；
- `frontend/src/api/datafiles.ts`：组合 API 和上传参数；
- `frontend/src/api/combinations.ts`：组合 CRUD；
- `frontend/src/pages/data/components/combination/`：组合页子组件；
- `frontend/src/pages/data/components/FileTagsCell.vue`：标签单元；
- `frontend/src/components/common/fileSelectModel.ts`：组合/批次号匹配。

当前 `BatchDataTab.vue` 554 行、`FileListTab.vue` 548 行，必须拆壳后承载新功能。

## 17. 文档与门禁

- 更新 `docs/intro/guide/04-data.md`；
- 更新 `docs/intro/.vitepress/theme/data.ts` 的批次数据介绍；
- 按需更新快速开始和 FAQ 中“ZIP 自动解析为批次”的说明；
- Tab 文案变更触发介绍书维护；
- 新增迁移命中全量 E2E 门禁；
- 前端类型和公共 utils 变更同样会触发全量档；
- 提交前执行 vitest、lint:e2e、build；收口执行后端全套和 `node scripts/e2e_pool.mjs --slots=4`。

## 18. 非目标

本版本不做：

- 一个文件属于多个组合；
- 独立 Batch 实体或批次状态机；
- 组合改变文件物理存储路径；
- 自动猜测存量文件属于 gage 还是 buyoff；
- 根据组合名自动生成 Gage/Buyoff/批次报表；
- 手动编辑或删除单条系统标签；
- 标签层级解析或通用标签树；
- 存量数据自动回填批次号。

## 19. 实施顺序

1. 模型、迁移、组合服务与 T1；
2. 序列化、筛选、标签联想与文件下拉 DTO；
3. 单文件、ZIP、目录、SFTP 导入接线；
4. 组合页与文件列表 UI；
5. 存量归组向导；
6. 介绍书、E2E 和全量收口。
