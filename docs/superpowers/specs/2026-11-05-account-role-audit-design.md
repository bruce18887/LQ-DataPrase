# 账号角色收敛与操作审计设计

- 日期：2026-11-05
- 状态：用户已确认，待编写实施计划
- 关联批次：上一批已完成自助改密、管理员重置清锁定、改密后 token 吊销。

## 1. 目标

1. 移除在当前架构下没有实际用途的 `viewer` 角色，把权限模型收敛为管理员与普通用户两级。
2. 把账号安全事件写入专用产品审计表，并提供管理员独立查询页。
3. 修复应用登录不更新 `last_login` 的问题。
4. 给用户管理页补“编辑账号资料与角色”的 UI，消除 API 有、页面没有的缺口。
5. 让代码、种子数据、e2e fixture、用户指南和部署文档描述同一个角色模型。

## 2. 背景判断

- `DataFile`、`Job`、`UserSetting`、`SftpConfig` 均按 owner 隔离；管理员也没有跨用户数据视图。
- 若 `viewer` 真为只读且不能上传，新建 viewer 账号在现有产品里没有稳定可看数据；若允许上传，又不再是“只读”。
- 现有测试已经把 viewer 当成“可检查数据一致性但不能删除”的普通非管理员使用，说明该角色没有独立、可长期维护的产品语义。
- 用户决定：不再保留 viewer，历史 viewer 全部归并为 user。

## 3. 角色与权限

### 3.1 角色

`User.ROLE_CHOICES` 最终只有：

- `administrator`：管理员
- `user`：普通用户

模型默认值仍为 `user`。UI、类型、种子账号和文档不再出现 viewer。

### 3.2 权限表

`apps/accounts/permissions.py` 只保留当前真实需要的功能：

```python
FEATURE_PERMISSIONS = {
    'user_management': ['administrator'],
    'system_config': ['administrator'],
    'audit_log_view': ['administrator'],
    'data_delete': ['administrator'],
    'data_repair_mutate': ['administrator', 'user'],
}
```

新增纯函数：

```python
role_can(role, feature) -> bool
```

供 `FeaturePermission` 和数据一致性视图共用，避免视图里再硬编码角色字符串。

### 3.3 行为边界

- 普通用户可继续查看、上传、分析、导出、删除自己的数据，使用 SFTP，提交作业。
- 数据一致性检查 GET 对已登录用户开放。
- 孤立数据导入、产品名补缺继续允许 administrator/user。
- 孤立数据删除、重复数据删除继续只允许 administrator。
- 用户管理、系统路径、指标、操作审计继续只允许 administrator。
- 管理员不能禁用/删除自己；系统必须保留至少一个启用管理员，这两条现有守卫不变。
- 本批不改变 `username` 是否可由管理员 PUT 的既有 API 现状，只在 UI 编辑弹窗中禁止修改用户名。

## 4. viewer 数据迁移

新增 `apps/accounts/migrations/0012_normalize_user_roles.py`。

操作顺序：

1. 历史模型中的 `viewer` 且 `is_superuser=False`：批量改为 `user`。
2. 历史模型中的 `viewer` 且 `is_superuser=True`：批量改为 `administrator`。
3. 所有 `is_superuser=True` 但 role 非 administrator 的历史遗留行：改为 administrator，和启动期 `_promote_legacy_superusers` 口径一致。
4. AlterField 将 `role.choices` 收敛为 administrator/user。

迁移逻辑抽成可独立调用/测试的纯函数，避免只能靠人工跑 migration 验证。反向 `run_python` 显式 no-op：历史 viewer 的独立身份按既定决策不再恢复，只允许 choices migration 自身回退。

`seed_users` 同步：

- 不再创建 viewer。
- 若发现历史 viewer 行，仍将其修正为 user；这是迁移之外的幂等兜底。
- 开发弱口令守卫文案只列 admin/user 两个已知口令。

## 5. 审计模型与事件

### 5.1 模型

`apps/accounts/models.py` 新增 `AuditEvent`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `created_at` | DateTimeField auto_now_add | 倒序主时间线 |
| `event` | CharField(32) | 稳定机器码 |
| `actor` | FK User, null, SET_NULL | 操作者；登录失败可空 |
| `actor_username` | CharField(150) | 事件发生时的账号快照 |
| `target` | FK User, null, SET_NULL | 被操作账号；未知登录用户可空 |
| `target_username` | CharField(150) | 被操作/被尝试账号快照 |
| `ip_address` | GenericIPAddressField null | 当前直连请求的 REMOTE_ADDR |
| `detail` | JSONField default dict | 事件结构化摘要 |

索引：

- `created_at`
- `(event, created_at)`
- `(actor_username, created_at)`
- `(target_username, created_at)`

### 5.2 事件码

| 事件码 | 中文标签 | 触发点 |
|---|---|---|
| `login_success` | 登录成功 | LoginView 成功签发 token |
| `login_failure` | 登录失败 | 用户名不存在、密码错误、禁用、锁定期间尝试 |
| `account_locked` | 账号锁定 | 第 5 次失败导致锁定的状态变化 |
| `account_unlocked` | 账号解锁 | 管理员 unlock |
| `password_changed` | 自助修改密码 | ChangePasswordView 成功 |
| `password_reset` | 管理员重置密码 | reset_password 成功 |
| `user_created` | 创建账号 | UserManagementViewSet create |
| `user_updated` | 更新账号 | UserManagementViewSet update |
| `user_deleted` | 删除账号 | UserManagementViewSet destroy |
| `system_paths_changed` | 存储路径变更 | SystemPathsView PUT 成功 |

账号启用/停用不单开事件码，作为 `user_updated` detail 中的 `is_active` 变更。

### 5.3 detail 约定

- `login_failure`：`reason` 为 `unknown_user` / `bad_password` / `account_disabled` / `account_locked`；密码错误时另有 `remaining_attempts`。
- `account_locked`：`retry_after_minutes`、ISO `locked_until`。
- `user_updated`：`changed_fields` 数组和这些字段变更后的安全值；只允许 `username/email/display_name/role/is_active`，绝不记录密码。
- `user_created`：`role`、`is_active`。
- `user_deleted`：删除前的 `role`，目标身份靠 `target_username` 快照保留，`target` FK 置空。
- `password_reset`：`target_username`、`lockout_cleared=true`。
- `system_paths_changed`：变更前后的 `data_dir/temp_dir` 配置值、`restart_required`。

### 5.4 写入器

新增 `apps/accounts/audit.py`：

```python
record(request, event, *, actor=None, target=None, target_username=None, detail=None)
```

规则：

1. actor 默认取 `request.user`，匿名用户写空快照。
2. username 输入超过 150 字符时截断，未知账号探测不能因异常输入让登录 500。
3. IP 取 `REMOTE_ADDR`；拿不到或非法时留空。
4. `AuditEvent.objects.create()` 包在独立 savepoint 中。
5. 任何审计异常只写 warning 日志，不回滚改密、重置、账号变更或登录业务动作。

## 6. 审计查询 API

端点：`GET /api/v1/auth/audit-events/`

权限：`IsAuthenticated + FeaturePermission('audit_log_view')`。

查询参数：

- `event`：单个事件码，空值表示全部；非法值 400。
- `username`：在 actor/target username 上大小写不敏感包含匹配；最长 150。
- `date_from` / `date_to`：`YYYY-MM-DD`，按项目时区取整日边界且包含两端；非法或倒置 400。
- `page`：页码。
- `page_size`：默认 50，最大 100。

响应沿用 DRF 分页信封，每条包含：

```json
{
  "id": 1,
  "created_at": "...",
  "event": "password_reset",
  "actor_username": "admin",
  "target_username": "e2e_user",
  "ip_address": "127.0.0.1",
  "detail": {}
}
```

排序固定 `created_at desc`。该端点只读，不提供创建、修改、删除接口。

## 7. 前端设计

### 7.1 操作审计页

- 路由：`/admin/audit`
- 标题：操作审计
- meta：`requiresAdmin: true`
- 侧栏：在“系统管理”分组、用户管理之后增加“操作审计”入口；非管理员不渲染 DOM。
- API：`frontend/src/api/audit.ts`
- 纯逻辑：`frontend/src/utils/audit.ts`
  - 事件标签映射
  - 筛选对象转 query 参数
  - detail 单行摘要
- 页面结构：
  - 筛选区：事件下拉、账号关键词、日期范围、查询、重置。
  - 表格列：时间、事件、操作者、目标、IP、详情摘要。
  - 行展开显示格式化 detail。
  - 分页控件显示总数，可切 20/50/100。
- 主题：沿用 `--bg/--card/--border/--text/--text-2` 与现有 admin 页样式，不新增单页硬编码色；dark/light 都走 token。
- 空态/错误：空结果明确显示“暂无符合条件的审计记录”；请求失败由统一 toast 处理，页面保留筛选条件便于重试。

### 7.2 用户编辑弹窗

- 用户管理表格操作列新增“编辑”。
- 弹窗字段：
  - 用户名：只读。
  - 显示名：可改。
  - 邮箱：可改，空值合法。
  - 角色：只允许管理员/普通用户。
- 保存调用 `PUT /api/v1/auth/users/<id>/`，成功后刷新列表。
- 后端角色/启用守卫失败时保留原列表，错误文案由统一拦截器展示。
- 保留独立的禁用/启用、重置密码、解锁、删除按钮；编辑弹窗不塞密码重置，避免两类操作混在一个确认流里。

### 7.3 角色展示清理

- `frontend/src/types/index.ts` 的 Role 联合类型改为 administrator/user。
- Topbar、个人资料弹窗、用户管理的 role label/icon 移除查看者分支。
- 历史数据迁移后不会出现 viewer；若某台机器迁移失败仍读到未知角色，前端标签回退“用户”，不再显示 viewer。

## 8. last_login

LoginView 成功后统一写：

```python
user.last_login = timezone.now()
user.login_attempts = 0
user.lockout_until = None
user.save(update_fields=['last_login', 'login_attempts', 'lockout_until'])
```

- 不再把“干净账号零 UPDATE”当登录契约；更新最后登录是产品要求。
- `LoginPathTests` 重新测定成功路径语句数并钉住新的 SQL 形状。
- 登录失败、未知用户、禁用与锁定尝试不更新 last_login。

## 9. 必须同步修改的现有触点

### 9.1 后端

- `apps/accounts/models.py`：role choices、AuditEvent。
- `apps/accounts/permissions.py`：权限表、`role_can`。
- `apps/accounts/views.py`：登录 last_login/审计、用户 CRUD 审计、重置/解锁审计。
- `apps/accounts/urls.py`：audit-events 路由。
- `apps/accounts/serializers.py`：审计序列化器；更新 profile 提权注释中的 viewer 示例。
- `apps/common/views.py`：系统路径变更审计。
- `apps/datafiles/views/browse_views.py`：数据一致性角色判断改用权限表。
- `apps/accounts/management/commands/seed_users.py`：移除 viewer 并兜底归并。
- `apps/accounts/admin.py`：本批不向 Django admin 注册 AuditEvent，保持产品审计查询单一入口。

### 9.2 既有测试

- `apps/accounts/tests.py`：role viewer 改为 user。
- `apps/common/tests_metrics.py`、`tests_system_paths.py`：非管理员探针改 user。
- `apps/datafiles/tests.py`：一致性角色契约改为 user/admin 两级。
- `test/backend/test_batch_dir_traversal.py`：攻击者角色改 user，路径逃逸断言保持。
- `test/backend/test_profile_privilege.py`、`test_accounts_bootstrap.py`：移除 viewer 断言，补充 API 拒绝设置 viewer。
- 登录路径语句测试按 last_login 新形状更新。
- 登录审计测试显式抬高 login throttle，避免跨测试共享默认 20/min 预算造成无关 429。

### 9.3 前端与 e2e

- `frontend/e2e/fixtures/test-data.ts`：删除 viewer 种子账号与 Role 键。
- `frontend/e2e/admin/admin.spec.ts`：重置密码临时用户改 user，增加编辑弹窗与审计页用例。
- `frontend/e2e/README.md`：种子账号说明改两级。
- `frontend/e2e/auth/account.spec.ts` 注释里的 admin/user/viewer 改 admin/user。
- 审计页纯函数新增 T2 用例；事件产生、权限、筛选、编辑弹窗增加 T3 用例。

### 9.4 文档

- `README.md`：删除 viewer 开发账号表行，权限说明改成管理员/普通用户。
- `docs/user-guide/README.md`：删除 viewer 读者入口。
- `docs/user-guide/01-quickstart.md`：删除 viewer 默认账号。
- `docs/user-guide/08-admin.md`：重写两级角色矩阵，补编辑弹窗和操作审计章节。
- `docs/reference/server-deployment.md`：viewer 探针示例改为 user，并更新首启验收命令/结果说明。
- 用户指南 `dist` 按既有 `docs/user-guide/build.js` 重新生成；只接受本次源页对应差异。若生成器导致大量无关文件变化，实施时停在自审并提交差异报告，不混入无关 churn。
- 带日期的历史架构评审与性能基线不改写，其历史结论不代表当前状态。

## 10. 错误处理

- 审计写入采用 best-effort，业务动作优先成功；异常必须有日志证据。
- 查询参数错误使用项目统一 `{code,message,detail}` 错误信封，不返回裸英文字段。
- 迁移幂等：正常完成后再执行 `seed_users` 不应创建或遗留 viewer。
- API 拒绝把新账号设置为 viewer；迁移前历史行则由 migration 处理。
- 日期筛选按项目时区解释，避免 UTC 和本地日界混用。
- 删除账号后审计保留 username 快照，不依赖仍可查询到的目标 FK。

## 11. 测试分层

### 11.1 T1 后端

1. `normalize_roles`：viewer/user、superuser viewer、遗留 superuser role user 三种归并。
2. choices 与 API：创建/更新 role=viewer 返回校验错误。
3. 登录成功更新 last_login；失败不更新；语句数量与新实现一致。
4. 每类安全事件产生正确的 actor/target/detail/IP。
5. 审计插入抛错时业务接口仍返回原成功状态。
6. audit API：管理员可查；普通用户 403；匿名 401；筛选、分页、排序正确。
7. 数据一致性角色继续按 `role_can` 判定，viewer 不再作为测试角色。

### 11.2 T2 前端

1. `buildAuditQuery` 只产生非空参数，日期边界与页码稳定。
2. 事件标签完整覆盖模型事件码。
3. detail 摘要对空对象、未知事件、嵌套/超长值不抛错。

### 11.3 T3 浏览器

1. 管理员编辑账号资料与角色，列表即时收敛。
2. 管理员完成一次重置密码后，审计页最新记录出现且按目标账号筛选命中。
3. 普通用户直达 `/admin/audit` 被路由守卫送回 dashboard，侧栏无入口。
4. 现有 auth/admin 回归不被角色模型改变破坏。

### 11.4 门禁

- 每批 commit 前跑 `cd frontend && npm run test:e2e:affected`。
- 触及 migrations/config/stores/router/styles，预计升级为全量；最终收口跑 `node scripts/e2e_pool.mjs --slots=4` 加后端全量。
- 结论只取门禁末尾 `RESULT:`；slot 崩溃或 `verdict=VOID (infra)` 必须按基础设施轮复跑，不算产品绿。
- 前端还跑 `npm run test:unit`、`npm run lint:e2e`、`npm run build`。

## 12. 实施顺序

1. 角色模型/migration/权限表，以及直接受影响的现有后端测试。
2. last_login 与登录审计事件。
3. AuditEvent、审计写入器和用户管理/系统配置端点接线。
4. audit-events API。
5. 前端角色展示清理与用户编辑弹窗。
6. 审计纯函数、API client、独立管理页和路由/侧栏。
7. 文档与 e2e fixture/spec 同步。
8. T1/T2/T3 分层验证及全量门禁收口。

## 13. 验收标准

- 新建/编辑账号时 UI 和 API 都无法选择或设置 viewer。
- 升级现有 SQLite 后，历史 viewer 不再是管理员权限之外的半截角色；非超级用户 viewer 变为 user。
- 登录成功后用户管理页能看到“最后登录”变化。
- 每次登录、锁定、解锁、改密、重置、账号创建/更新/删除、存储路径变更都有一条正确审计记录；删除账号后的记录仍保留目标 username。
- 管理员可在独立页面查询和筛选，普通用户无法访问 API 或页面。
- 用户管理能修改显示名、邮箱、角色，后端安全守卫不变。
- 后端全量、vitest、build、lint:e2e 和一轮无 VOID 的 e2e 全量池均有可复制结论。

## 14. 明确不做

- 跨用户文件共享或“真正只读 viewer”。
- 邮件自助找回密码。
- 上传、删除单个数据文件、SFTP 下载等数据操作级审计。
- 删除用户时清理磁盘上传目录和作业产物。
- MFA/SSO、Django Groups 权限体系、TLS/CORS 整改。
- 审计日志自动过期或批量删除 UI。

## 15. 已接受风险

- 登录失败审计会记录未知用户名，暴力探测可产生较多行。当前以登录 IP 限流和局域网威胁模型兜住，并明确不做自动清理；若未来公网暴露，需要另做保留/归档策略。
- viewer 历史身份被永久归并，迁移不可逆地还原其独立角色；这是用户选定的结果。
- `last_login` 写入使成功登录比旧实现多一条 UPDATE，登录路径语句测试必须同步重测，不能保留旧 no-op 期望。
- 用户指南 dist 是生成物，若构建器版本变化产生无关 churn，实施批次要停在差异自审，不把无关 HTML 混入本次变更。

