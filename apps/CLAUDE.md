# LQ-DataPrase Django 后端架构文档

## 技术栈

- **框架**: Django 4.2 + DRF 3.14
- **数据库**: PostgreSQL (base.py) / SQLite (development.py 覆盖)
- **认证**: JWT (djangorestframework-simplejwt, access 30min, refresh 7d)
- **异步任务**: Celery 5.3 + Redis 5.0
- **数据处理**: Pandas 2.0 + NumPy 1.24 + Matplotlib 3.7
- **文件处理**: openpyxl + python-pptx + Pillow
- **SFTP**: Paramiko 2.10
- **API 文档**: drf-spectacular (Swagger)

## 项目结构

```
LQ-DataPrase/
├── config/                    # Django 核心配置
│   ├── settings/base.py       #   基础配置（INSTALLED_APPS, DATABASES, JWT等）
│   └── settings/development.py#   开发覆盖（DEBUG=True, SQLite）
│   ├── celery.py              #   Celery 配置
│   ├── urls.py                #   根路由（10个app + Swagger）
│   ├── wsgi.py / asgi.py      #   部署入口
├── apps/                      # 9 个 Django 应用
│   ├── accounts/              #   用户认证/权限/设置（User/UserSetting）
│   ├── datafiles/             #   文件管理/解析（DataFile/ParseHistory + 4个parser）
│   ├── analysis/              #   数据分析（9个@action端点 + services子包）
│   ├── dashboard/             #   仪表板（KPI/图表数据）
│   ├── batch_report/          #   批次报表
│   ├── buyoff/                #   买断管理
│   ├── gage/                  #   量具 R&R（services/rr_analysis.py）
│   ├── export/                #   数据导出（Excel/PPT，含excel_builders/export_ppt）
│   ├── sftp/                  #   SFTP 文件浏览
│   └── data_correlation/      #   数据关联分析
├── requirements/              # base.txt + production.txt
├── manage.py                  # 默认使用 config.settings.development
├── pytest.ini                 # pytest 配置
└── db.sqlite3                 # 开发数据库
```

## 核心应用

### 1. accounts - 用户认证和权限

**模型**: `User`（AbstractUser, role: administrator\|user\|viewer, login_attempts, lockout_until）+ `UserSetting`（OneToOne, page_size/chart_height/cpk_threshold 等）

**API 端点** (`/api/v1/auth/`): `POST login` | `POST logout` | `GET/PUT profile` | `GET/PUT settings` | `GET/POST users`（管理员）| `POST users/{id}/reset_password` | `POST users/{id}/unlock`

**权限**: `FeaturePermission` — 管理员完全访问，用户可读+POST，浏览者只读。登录失败 5 次锁定 15 分钟。

**管理命令**: `seed_users`（初始化测试用户）| `seed_test_data`（生成测试数据）

---

### 2. datafiles - 数据文件管理和解析

**模型**: `DataFile`（owner/filename/format_type/row_count/col_count/program_name/metadata/status: pending\|parsing\|ready\|error）+ `ParseHistory`

**API 端点**: `GET files` | `POST upload` | `PUT activate/{id}` | `DELETE files/{id}` | `GET browse` | `GET history`

**解析器** (`parsers/`): `BaseATEParser` 抽象基类（`can_parse` / `parse` / `get_metadata`）→ 4 个实现（`cta8290d` / `cta8280f` / `ets88` / `sts8200`）

**格式识别**: 读取文件头 → 依次调用 `can_parse()` → 使用第一个返回 True 的解析器

**异步任务** (`tasks.py`): 文件解析任务（Celery 后台处理）

---

### 3. analysis - 数据分析（核心，views.py ~1154 行）

**API 端点** (`/api/v1/analysis/`): `POST histogram` | `wafer_map` | `correlation` | `multi_lot` | `correlation_matrix` | `bin_trend` | `boxplot` | `param_trend` | `serial_distribution`

**Services 子包**:
- `statistics.py` — CPK（Cp/Cpk/Pp/Ppk）、Sigma 水平、Pearson/Spearman 相关系数、异常值检测、分布拟合
- `data_services.py` — 数据加载/处理
- `limits.py` — 限值计算
- `efficiency.py` — 效率计算

**视图**: `AnalysisViewSet`（@action 装饰器）+ `StatisticsViewSet`

---

### 4. dashboard - 仪表板

**API**: `GET /api/v1/dashboard/summary/`（文件数/用户数/最近活动）| `GET /api/v1/dashboard/batch_report/`

---

### 5. 其他应用

| 应用 | 说明 | 关键文件 |
|------|------|---------|
| `batch_report` | 批次报表 | views.py, tests.py |
| `buyoff` | 买断管理 | views.py, services.py, tests.py |
| `gage` | 量具 R&R | views.py, services/rr_analysis.py, tests.py |
| `export` | 数据导出（Excel/PPT） | views.py, excel_builders.py, export_ppt.py, export_complete.py, excelize_helpers.py |
| `sftp` | SFTP 文件浏览 | views.py, tests.py |
| `data_correlation` | 数据关联分析 | views.py, tests.py |

---

## 核心配置

### 数据库 (`config/settings/base.py`)

```python
# base.py — PostgreSQL（生产）
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'ate_analysis', 'USER': 'ate_user', 'PASSWORD': 'ate_password',
        'HOST': 'localhost', 'PORT': '5432',
    }
}
# development.py — SQLite 覆盖（开发）
DATABASES = { 'default': { 'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3' } }
```

### JWT

```python
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=30),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True, 'BLACKLIST_AFTER_ROTATION': True,
}
```

### 已安装应用（12 个自定义应用）

```python
INSTALLED_APPS = [
    # Django 内置...
    'rest_framework', 'rest_framework_simplejwt', 'corsheaders',
    'django_filters', 'drf_spectacular', 'celery',
    # 自定义应用（9 个）
    'apps.accounts', 'apps.datafiles', 'apps.analysis', 'apps.dashboard',
    'apps.batch_report', 'apps.buyoff', 'apps.gage', 'apps.export',
    'apps.sftp', 'apps.data_correlation',
]
```

### 路由 (`config/urls.py`)

根路径重定向到 Swagger（`/api/schema/swagger/`）。10 个 app 路由统一挂载到 `/api/v1/` 下。

### 语言时区

```python
LANGUAGE_CODE = 'zh-hans'  TIME_ZONE = 'Asia/Shanghai'  USE_TZ = True
```

---

## 设计模式和约定

### ViewSet 模式

**标准 CRUD**:
```python
class DataFileViewSet(viewsets.ModelViewSet):
    serializer_class = DataFileSerializer
    permission_classes = [IsAuthenticated]
    def get_queryset(self):
        return self.queryset.filter(owner=self.request.user)
```

**自定义 @action**:
```python
class AnalysisViewSet(viewsets.ViewSet):
    @action(detail=False, methods=['post'])
    def histogram(self, request):
        file_id = request.data.get('file_id')
        # 分析逻辑 → 返回 { data, statistics }
        return Response(result)
```

### Serializer 模式

**列表 vs 详情**:
```python
class DataFileListSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataFile
        fields = ['id', 'filename', 'format_type', 'status', 'created_at']
```

### 数据流

```
POST /api/v1/analysis/histogram/ { file_id, param_x, bins, spec_lower, spec_upper }
  → AnalysisViewSet.histogram()
  → 加载 DataFile → Parser 解析 → 提取参数数据
  → statistics.py 计算 CPK/均值/标准差
  → 返回 { data: [...], statistics: { mean, std, cpk, ... } }
```

### 错误处理

```python
from rest_framework.exceptions import ValidationError, NotFound

if not param_x: raise ValidationError("param_x is required")
try: datafile = DataFile.objects.get(id=file_id, owner=request.user)
except DataFile.DoesNotExist: raise NotFound("DataFile not found")
```

### 权限

```python
class FeaturePermission(BasePermission):
    def has_permission(self, request, view):
        if request.user.role == 'administrator': return True
        elif request.user.role == 'user': return request.method in SAFE_METHODS or request.method == 'POST'
        elif request.user.role == 'viewer': return request.method in SAFE_METHODS
        return False
```

### 命名约定

- 文件名 / 函数 / 变量：snake_case
- 类名：PascalCase
- 常量：UPPER_SNAKE_CASE
- API 端点：snake_case（`/api/v1/data_files/`, `/param_trend/`）

---

## 开发指南

### 启动

```bash
pip install -r requirements/base.txt
python manage.py migrate
python manage.py seed_users        # 初始化测试用户
python manage.py seed_test_data    # 生成测试数据
python manage.py runserver         # → http://localhost:8000
celery -A config worker -l info    # 另一个终端
redis-server                       # 如需 Celery
```

### 添加解析器

1. `apps/datafiles/parsers/` 创建文件
2. 继承 `BaseATEParser` 实现 `can_parse` / `parse` / `get_metadata`
3. 在 `apps/datafiles/services.py` 注册

### 添加分析功能

1. `apps/analysis/views.py` 的 `AnalysisViewSet` 添加 `@action`
2. 复杂统计逻辑放 `apps/analysis/services/`

### 运行测试

```bash
python manage.py test              # 全部
python manage.py test apps.accounts
```

### API 文档

Swagger UI: `http://localhost:8000/api/schema/swagger/`

---

## 最佳实践

1. **类型提示**: 所有函数参数和返回值加类型
2. **异常处理**: 使用 DRF 标准异常，避免裸 `except`
3. **查询优化**: `select_related` / `prefetch_related`
4. **权限检查**: 所有 ViewSet 设 `permission_classes`
5. **数据验证**: Serializer 中验证，不在 View 中
6. **事务管理**: 多模型操作 `@transaction.atomic`
7. **代码复用**: 通用逻辑提取到 `services.py`
8. **Celery 异步**: 耗时操作（文件解析/大计算）走后台任务

任何后端改动都要测试api接口