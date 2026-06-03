# DataPhrase Django 后端架构文档

## 技术栈

- **框架**: Django 4.2+, Django REST Framework 3.14+
- **数据库**: PostgreSQL (生产) / SQLite (开发)
- **认证**: JWT (djangorestframework-simplejwt)
- **异步任务**: Celery 5.3+, Redis 5.0+
- **数据处理**: Pandas 2.0+, NumPy 1.24+, Matplotlib 3.7+
- **文件处理**: openpyxl 3.1+, python-pptx 0.6.21+, Pillow 10.0+
- **SFTP**: Paramiko 2.10+
- **API 文档**: drf-spectacular (Swagger)

## 项目结构

```
DataPhrase_Django/
├── config/                 # Django 核心配置
│   ├── settings/
│   │   ├── base.py        # 基础配置
│   │   └── development.py # 开发环境覆盖
│   ├── celery.py          # Celery 配置
│   ├── urls.py            # 根 URL 路由
│   ├── wsgi.py            # WSGI 入口
│   └── asgi.py            # ASGI 入口
│
├── apps/                   # Django 应用集合
│   ├── accounts/          # 用户认证和权限
│   ├── datafiles/         # 数据文件管理和解析
│   ├── analysis/          # 数据分析
│   ├── dashboard/         # 仪表板
│   ├── batch_report/      # 批次报表
│   ├── buyoff/            # 买断管理
│   ├── gage/              # 量具管理
│   ├── export/            # 数据导出
│   ├── sftp/              # SFTP 文件浏览
│   └── data_correlation/  # 数据关联分析
│
├── requirements/          # Python 依赖
│   ├── base.txt          # 基础依赖
│   └── development.txt   # 开发依赖
│
├── manage.py             # Django 管理脚本
└── db.sqlite3            # SQLite 数据库（开发环境）
```

## 核心应用架构

### 1. accounts - 用户认证和权限

**核心模型** (`apps/accounts/models.py`):
```python
class User(AbstractUser):
    """自定义用户模型"""
    role: 'administrator' | 'user' | 'viewer'
    display_name: str
    login_attempts: int
    lockout_until: datetime

class UserSetting(Model):
    """用户个性化设置"""
    user: OneToOneField(User)
    page_size, chart_height, table_height, chart_dpi
    cpk_a/b/c_threshold
    chart_engine, aggrid_header_font_size
    recent_files, histogram_label_offset
```

**API 端点** (`/api/v1/auth/`):
- `POST /login/` - 登录（返回 JWT token）
- `POST /logout/` - 登出
- `GET /profile/` - 获取用户信息
- `PUT /profile/` - 更新用户信息
- `GET /settings/` - 获取用户设置
- `PUT /settings/` - 更新用户设置
- `GET /users/` - 用户列表（管理员）
- `POST /users/` - 创建用户（管理员）
- `POST /users/{id}/reset_password/` - 重置密码
- `POST /users/{id}/unlock/` - 解锁账户

**认证机制**:
- JWT 认证（访问令牌 30 分钟，刷新令牌 7 天）
- 登录失败 5 次后锁定账户 15 分钟
- 自定义权限类：`FeaturePermission`

**管理命令**:
```bash
python manage.py seed_users  # 初始化测试用户
```

---

### 2. datafiles - 数据文件管理和解析

**核心模型** (`apps/datafiles/models.py`):
```python
class DataFile(Model):
    """数据文件记录"""
    owner: ForeignKey(User)
    filename, file_path, file_size
    format_type: 'CTA8290D' | 'CTA8280F' | 'ETS88' | 'STS8200'
    row_count, col_count, program_name
    metadata: JSONField
    status: 'pending' | 'parsing' | 'ready' | 'error'
    created_at, updated_at

class ParseHistory(Model):
    """解析历史记录"""
    user, datafile, filename, filepath, format_type
    rows, cols, parsed_at
```

**API 端点** (`/api/v1/`):
- `GET /files/` - 文件列表
- `POST /upload/` - 上传文件
- `PUT /activate/{id}/` - 激活文件
- `DELETE /files/{id}/` - 删除文件
- `GET /browse/` - 数据浏览（分页、搜索、过滤）
- `GET /history/` - 解析历史

**数据解析器架构** (`apps/datafiles/parsers/`):

```python
# base.py - 抽象基类
class BaseATEParser(ABC):
    @abstractmethod
    def can_parse(self, file_path: str) -> bool:
        """检查是否能解析该文件"""
        pass
    
    @abstractmethod
    def parse(self, file_path: str) -> pd.DataFrame:
        """解析文件并返回 DataFrame"""
        pass
    
    @abstractmethod
    def get_metadata(self, file_path: str) -> dict:
        """提取文件元数据"""
        pass
```

**支持的格式**:
- `CTA8290D` - CTA8290D 格式解析器 (`parsers/cta8290d.py`)
- `CTA8280F` - CTA8280F 格式解析器 (`parsers/cta8280f.py`)
- `ETS88` - ETS88 格式解析器 (`parsers/ets88.py`)
- `STS8200` - STS8200 格式解析器 (`parsers/sts8200.py`)

**格式识别流程**:
1. 读取文件头部内容
2. 依次调用各解析器的 `can_parse()` 方法
3. 使用第一个返回 True 的解析器

**Celery 异步任务** (`apps/datafiles/tasks.py`):
- 文件解析任务（后台处理大文件）

---

### 3. analysis - 数据分析

**API 端点** (`/api/v1/analysis/`):
- `POST /histogram/` - 直方图分析
- `POST /wafer_map/` - 晶圆图
- `POST /correlation/` - 相关性分析
- `POST /multi_lot/` - 多批次对比
- `POST /correlation_matrix/` - 相关矩阵
- `POST /bin_trend/` - Bin 趋势
- `POST /boxplot/` - 箱线图
- `POST /param_trend/` - 参数趋势
- `POST /serial_distribution/` - 序列号分布

**统计计算服务** (`apps/analysis/services/statistics.py`):
- CPK 计算（Cp, Cpk, Pp, Ppk）
- Sigma 水平计算
- 相关性分析（Pearson, Spearman）
- 异常值检测和清理
- 分布拟合

**核心视图** (`apps/analysis/views.py` - 1154 行):
- `AnalysisViewSet` - 使用 `@action` 装饰器定义各种分析端点
- `StatisticsViewSet` - 统计计算端点

---

### 4. dashboard - 仪表板

**API 端点** (`/api/v1/dashboard/`):
- `GET /summary/` - 仪表板摘要（文件数、用户数、最近活动）
- `GET /batch_report/` - 批次报表

---

## 核心配置

### Django 设置 (`config/settings/base.py`)

**数据库配置**:
```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'dataphrase'),
        'USER': os.getenv('DB_USER', 'postgres'),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
    }
}
```

**JWT 配置**:
```python
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=30),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
}
```

**CORS 配置**:
```python
CORS_ALLOW_ALL_ORIGINS = True  # 开发环境
CORS_ALLOW_CREDENTIALS = True
```

**Celery 配置**:
```python
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
```

**语言和时区**:
```python
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_TZ = True
```

---

## 设计模式和约定

### 1. ViewSet 模式

**标准 CRUD ViewSet**:
```python
class DataFileViewSet(viewsets.ModelViewSet):
    queryset = DataFile.objects.all()
    serializer_class = DataFileSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return self.queryset.filter(owner=self.request.user)
```

**自定义 Action ViewSet**:
```python
class AnalysisViewSet(viewsets.ViewSet):
    @action(detail=False, methods=['post'])
    def histogram(self, request):
        # 直方图分析逻辑
        pass
    
    @action(detail=False, methods=['post'])
    def correlation(self, request):
        # 相关性分析逻辑
        pass
```

### 2. Serializer 模式

**列表 vs 详情序列化器**:
```python
class DataFileListSerializer(serializers.ModelSerializer):
    """列表视图 - 简化字段"""
    class Meta:
        model = DataFile
        fields = ['id', 'filename', 'format_type', 'status', 'created_at']

class DataFileDetailSerializer(serializers.ModelSerializer):
    """详情视图 - 完整字段"""
    owner_name = serializers.CharField(source='owner.display_name', read_only=True)
    
    class Meta:
        model = DataFile
        fields = '__all__'
```

### 3. 数据流模式

**典型分析请求流程**:
```
1. 前端发送 POST 请求 → /api/v1/analysis/histogram/
   {
     "file_id": 123,
     "param_x": "VDD_CURRENT",
     "bins": 50,
     "spec_lower": 0.5,
     "spec_upper": 1.5
   }

2. AnalysisViewSet.histogram() 接收请求
   ↓
3. 加载 DataFile 对象
   ↓
4. 使用对应的 Parser 解析文件
   ↓
5. 提取参数数据（param_x 列）
   ↓
6. 调用 statistics.py 计算统计指标
   ↓
7. 生成直方图数据（bins, counts）
   ↓
8. 返回 JSON 响应
   {
     "data": [...],
     "statistics": {
       "mean": 1.0,
       "std": 0.2,
       "cpk": 1.5,
       ...
     }
   }
```

### 4. 错误处理模式

**DRF 标准异常**:
```python
from rest_framework.exceptions import ValidationError, NotFound

# 参数验证错误
if not param_x:
    raise ValidationError("param_x is required")

# 资源不存在
try:
    datafile = DataFile.objects.get(id=file_id, owner=request.user)
except DataFile.DoesNotExist:
    raise NotFound("DataFile not found")
```

### 5. 权限控制模式

**基于角色的权限**:
```python
class FeaturePermission(BasePermission):
    def has_permission(self, request, view):
        if request.user.role == 'administrator':
            return True
        elif request.user.role == 'user':
            return request.method in SAFE_METHODS or request.method == 'POST'
        elif request.user.role == 'viewer':
            return request.method in SAFE_METHODS
        return False
```

---

## 命名约定

- **文件名**: snake_case (如 `data_files.py`, `user_settings.py`)
- **类名**: PascalCase (如 `DataFile`, `UserSetting`)
- **函数/方法名**: snake_case (如 `get_queryset`, `parse_file`)
- **变量名**: snake_case (如 `file_path`, `param_x`)
- **常量**: UPPER_SNAKE_CASE (如 `MAX_FILE_SIZE`, `DEFAULT_BINS`)
- **API 端点**: snake_case (如 `/api/v1/data_files/`, `/param_trend/`)

---

## 开发指南

### 启动开发服务器

```bash
# 安装依赖
pip install -r requirements/development.txt

# 数据库迁移
python manage.py migrate

# 创建超级用户
python manage.py createsuperuser

# 初始化测试用户
python manage.py seed_users

# 启动开发服务器
python manage.py runserver

# 启动 Celery worker（另一个终端）
celery -A config worker -l info

# 启动 Redis（如果未运行）
redis-server
```

### 添加新的数据格式解析器

1. 在 `apps/datafiles/parsers/` 创建新文件（如 `new_format.py`）
2. 继承 `BaseATEParser` 并实现三个方法：
   ```python
   class NewFormatParser(BaseATEParser):
       def can_parse(self, file_path: str) -> bool:
           # 检查文件头或特征
           pass
       
       def parse(self, file_path: str) -> pd.DataFrame:
           # 解析文件并返回 DataFrame
           pass
       
       def get_metadata(self, file_path: str) -> dict:
           # 提取元数据
           pass
   ```
3. 在 `apps/datafiles/services.py` 注册解析器

### 添加新的分析功能

1. 在 `apps/analysis/views.py` 的 `AnalysisViewSet` 添加新的 `@action`:
   ```python
   @action(detail=False, methods=['post'])
   def new_analysis(self, request):
       file_id = request.data.get('file_id')
       # 分析逻辑
       return Response(data)
   ```

2. 如需复杂统计计算，在 `apps/analysis/services/statistics.py` 添加函数

3. 在 `config/urls.py` 确保路由已包含（通常自动注册）

### 运行测试

```bash
# 运行所有测试
python manage.py test

# 运行特定应用测试
python manage.py test apps.accounts

# 运行特定测试类
python manage.py test apps.accounts.tests.UserModelTest
```

### API 文档

访问 Swagger UI:
```
http://localhost:8000/api/schema/swagger-ui/
```

---

## 关键文件路径

- **核心配置**: `config/settings/base.py`
- **URL 路由**: `config/urls.py`
- **用户模型**: `apps/accounts/models.py`
- **数据文件模型**: `apps/datafiles/models.py`
- **解析器基类**: `apps/datafiles/parsers/base.py`
- **分析视图**: `apps/analysis/views.py` (1154 行)
- **统计计算**: `apps/analysis/services/statistics.py`
- **Celery 配置**: `config/celery.py`

---

## 最佳实践

1. **类型提示**: 所有函数参数和返回值使用类型提示
2. **异常处理**: 使用 DRF 标准异常类，避免裸 `except`
3. **查询优化**: 使用 `select_related` 和 `prefetch_related` 减少数据库查询
4. **权限检查**: 所有 ViewSet 必须设置 `permission_classes`
5. **数据验证**: 在 Serializer 中进行数据验证，而非 View 中
6. **日志记录**: 使用 Django logging 记录关键操作和错误
7. **事务管理**: 涉及多个模型操作时使用 `@transaction.atomic`
8. **代码复用**: 将通用逻辑提取到 `services.py` 或 `utils.py`
9. **测试覆盖**: 每个 API 端点至少有一个测试用例
10. **文档字符串**: 所有公共类和方法必须有 docstring

---

## 常见问题

### Q: 如何切换数据库？
A: 修改 `config/settings/base.py` 中的 `DATABASES` 配置，或设置环境变量 `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`。

### Q: 如何处理大文件上传？
A: 使用 Celery 异步任务处理文件解析，避免阻塞请求。参考 `apps/datafiles/tasks.py`。

### Q: 如何添加新的用户角色？
A: 修改 `apps/accounts/models.py` 中 `User.role` 的 choices，并更新 `FeaturePermission` 逻辑。

### Q: 如何优化分析性能？
A: 
- 使用 Pandas 向量化操作代替循环
- 对大数据集进行采样或分块处理
- 使用 Celery 异步处理耗时分析
- 考虑使用缓存（Redis）存储中间结果

---

## 相关资源

- Django 文档: https://docs.djangoproject.com/
- DRF 文档: https://www.django-rest-framework.org/
- Celery 文档: https://docs.celeryproject.org/
- Pandas 文档: https://pandas.pydata.org/docs/
