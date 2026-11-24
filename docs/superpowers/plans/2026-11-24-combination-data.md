# 组合数据 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在数据管理中新增“组合数据”能力，用结构化组合归属和可选批次号驱动自动标签，同时保留现有手动标签与物理批次行为。

**Architecture:** 新增 owner 级 `DataCombination`，在 `DataFile` 上增加可空 `combination` 和 `batch_no`；系统标签不落库，由序列化器实时计算。上传、ZIP、目录和 SFTP 导入共用注册服务，前端组合页只消费同一套 API 与标签规则。

**Tech Stack:** Django、Django REST Framework、SQLite/PostgreSQL JSONField、Vue 3、TypeScript、Element Plus、Vitest、Playwright。

**Spec:** `docs/superpowers/specs/2026-11-24-combination-data-design.md`

## Global Constraints

- 一个文件最多属于一个组合；批次号可选；组合不等于物理批次。
- 手动标签继续使用 `DataFile.tags`，系统标签使用只读 `managed_tags`，不得写回 `tags`。
- 组合名最长 40 字符，批次号最长 40 字符；两者禁止 `/`、`\` 和控制字符。
- 组合名在同一 owner 下大小写不敏感唯一；批次号筛选和分组大小写不敏感。
- 组合改名不得修改成员文件的 `tags`、`batch_no` 或 `updated_at`。
- 删除组合只解除归属，不删除文件、不清空手动标签和批次号。
- `batch_name/sub_batch/file_type` 的物理批次语义保持不变，批次报表不得改写。
- Gage/Buyoff 只按组合收敛候选文件，不自动分配 Site 或角色。
- 单个 `.py`、`.ts`、`.vue` 文件不得超过 600 行；测试文件放在 `test/` 或既有 `apps/*/tests_*.py`。
- 前端新样式必须同时维护 light/night，只使用现有语义 token。
- 每个任务先写失败测试，再实现，再跑通过；后端组合矩阵用 T1，纯函数用 T2，浏览器只留关键接线。
- 新增迁移会触发全量 E2E；收口必须执行后端全套、vitest、lint:e2e、build 和 4-slot 池。
- 本计划不授权 push、合并分支或修改共享环境。
- 计划中的 commit 步骤仅在用户明确授权提交时执行；未授权时保留工作树改动并在任务结束时报告。

---

## File Structure

### 后端

- Create: `apps/datafiles/combination_service.py`
  - 组合名/批次号归一化、动态系统标签、批次号解析。
- Modify: `apps/datafiles/models.py`
  - 新增 `DataCombination`，扩展 `DataFile`。
- Create: `apps/datafiles/migrations/0008_datafile_combination_batch_no.py`
  - 新增组合表、文件 FK、批次号字段和索引。
- Modify: `apps/datafiles/serializers.py`
  - 组合序列化器、文件组合/批次号/系统标签字段。
- Create: `apps/datafiles/views/combination_views.py`
  - 组合 CRUD、批量归组。
- Modify: `apps/datafiles/views/file_views.py`
  - 筛选、搜索、标签联想、options 和上传参数接线；不承担组合业务主体。
- Modify: `apps/datafiles/views/batch_views.py`
  - 目录 DTO 与导入参数。
- Modify: `apps/datafiles/views/_helpers.py`
  - 注册服务持久化组合、批次号、手动标签；重传幂等更新。
- Modify: `apps/datafiles/views/__init__.py`
  - 导出新视图。
- Modify: `apps/datafiles/urls.py`
  - 注册组合路由和批量归组路由。
- Create: `test/backend/test_combinations_api.py`
- Create: `test/backend/test_combination_import.py`
- Create: `test/backend/test_combination_file_queries.py`

### 前端

- Modify: `frontend/src/types/index.ts`
- Create: `frontend/src/api/combinations.ts`
- Modify: `frontend/src/api/datafiles.ts`
- Create: `frontend/src/utils/combinationTags.ts`
- Create: `frontend/src/utils/reportFileScope.ts`
- Create: `frontend/test/unit/combinationTags.spec.ts`
- Create: `frontend/test/unit/reportFileScope.spec.ts`
- Modify: `frontend/test/unit/fileSelectModel.spec.ts`
- Create: `frontend/src/pages/data/components/combination/CombinationDataTab.vue`
- Create: `frontend/src/pages/data/components/combination/CombinationToolbar.vue`
- Create: `frontend/src/pages/data/components/combination/CombinationEditDialog.vue`
- Create: `frontend/src/pages/data/components/combination/CombinationFileGroups.vue`
- Create: `frontend/src/pages/data/components/combination/BatchDirectorySection.vue`
- Create: `frontend/src/pages/data/components/FileTagsCell.vue`
- Create: `frontend/src/pages/data/components/ImportOptionsDialog.vue`
- Modify: `frontend/src/pages/data/DataManagement.vue`
- Modify: `frontend/src/pages/data/components/FileUploadArea.vue`
- Modify: `frontend/src/pages/data/components/FileListTab.vue`
- Modify: `frontend/src/pages/data/components/FileListToolbar.vue`
- Modify: `frontend/src/pages/data/components/FileListTable.vue`
- Modify: `frontend/src/pages/data/components/BatchFilesTable.vue`
- Modify: `frontend/src/pages/data/components/CombineBatchDialog.vue`
- Modify: `frontend/src/pages/data/composables/useTagEditing.ts`
- Modify: `frontend/src/components/common/fileSelectModel.ts`
- Modify: `frontend/src/pages/data/GageSummary.vue`
- Modify: `frontend/src/pages/data/BuyoffForm.vue`
- Create: `frontend/e2e/data/combination-data.spec.ts`
- Modify: `frontend/e2e/data/zip-upload.spec.ts`
- Modify: `docs/intro/guide/04-data.md`
- Modify: `docs/intro/.vitepress/theme/data.ts`

---

### Task 1: 组合模型、归一化服务与迁移

**Files:**

- Create: `apps/datafiles/combination_service.py`
- Modify: `apps/datafiles/models.py`
- Create: `apps/datafiles/migrations/0008_datafile_combination_batch_no.py`
- Test: `test/backend/test_combination_service.py`

**Interfaces:**

- Produces:
  - `normalize_combination_name(raw) -> str`
  - `normalize_batch_no(raw) -> str`
  - `managed_tags_for(combination_name: str | None, batch_no: str) -> list[str]`
  - `resolve_batch_no(explicit: str, metadata: dict) -> str`
  - `DataCombination`
  - `DataFile.combination`
  - `DataFile.batch_no`

- [ ] **Step 1: 写失败测试**

创建 `test/backend/test_combination_service.py`：

```python
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.datafiles.combination_service import (
    managed_tags_for,
    normalize_batch_no,
    normalize_combination_name,
    resolve_batch_no,
)
from apps.datafiles.models import DataCombination, DataFile
from django.contrib.auth import get_user_model


class CombinationServiceTests(TestCase):
    def test_managed_tags_are_derived_from_combination_and_batch(self):
        self.assertEqual(managed_tags_for('gage', ''), ['gage'])
        self.assertEqual(
            managed_tags_for('gage', 'BE01-2608130015'),
            ['gage', 'gage / BE01-2608130015'],
        )
        self.assertEqual(managed_tags_for(None, 'BE01-2608130015'), [])

    def test_normalization_trims_and_rejects_separators(self):
        self.assertEqual(normalize_combination_name('  Gage Lab  '), 'Gage Lab')
        self.assertEqual(normalize_batch_no('  BE01-2608130015 '), 'BE01-2608130015')
        for raw in ('a/b', 'a\\b', 'a\nb'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                normalize_combination_name(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                normalize_batch_no(raw)

    def test_batch_number_prefers_explicit_then_metadata(self):
        self.assertEqual(resolve_batch_no('MANUAL', {'lot_id': 'LOT'}), 'MANUAL')
        self.assertEqual(resolve_batch_no('', {'lot_id': 'LOT'}), 'LOT')
        self.assertEqual(resolve_batch_no('', {'lot_id': None}), '')
        self.assertEqual(resolve_batch_no('', {'lot_id': 123}), '')
        self.assertEqual(resolve_batch_no('', {'lot_id': 'BAD/LOT'}), '')

    def test_combination_name_is_case_insensitive_unique_per_owner(self):
        User = get_user_model()
        owner = User.objects.create_user('combo_owner', password='x')
        other = User.objects.create_user('combo_other', password='x')
        DataCombination.objects.create(owner=owner, name='Gage')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DataCombination.objects.create(owner=owner, name='gage')
        DataCombination.objects.create(owner=other, name='gage')

    def test_delete_combination_only_clears_file_relation(self):
        User = get_user_model()
        owner = User.objects.create_user('combo_delete', password='x')
        combo = DataCombination.objects.create(owner=owner, name='gage')
        row = DataFile.objects.create(
            owner=owner, filename='a.csv', file_path='data/combo_delete/single/a.csv',
            file_size=1, format_type='CTA8290D', combination=combo,
            batch_no='BE01-2608130015', tags=['manual'],
        )
        combo.delete()
        row.refresh_from_db()
        self.assertIsNone(row.combination)
        self.assertEqual(row.batch_no, 'BE01-2608130015')
        self.assertEqual(row.tags, ['manual'])
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_combination_service -v 2`

Expected: FAIL，报 `ModuleNotFoundError: apps.datafiles.combination_service`。

- [ ] **Step 3: 实现服务与模型**

创建 `apps/datafiles/combination_service.py`：

```python
import re

_CONTROL_OR_SEPARATOR = re.compile(r'[\/\\\x00-\x1f\x7f]')


def normalize_combination_name(raw) -> str:
    if not isinstance(raw, str):
        raise ValueError('组合名必须是字符串')
    value = raw.strip()
    if not value:
        raise ValueError('组合名不能为空')
    if len(value) > 40:
        raise ValueError('组合名最长 40 字符')
    if _CONTROL_OR_SEPARATOR.search(value):
        raise ValueError('组合名不能包含 /、\\ 或控制字符')
    return value


def normalize_batch_no(raw) -> str:
    if raw is None:
        return ''
    if not isinstance(raw, str):
        raise ValueError('批次号必须是字符串')
    value = raw.strip()
    if len(value) > 40:
        raise ValueError('批次号最长 40 字符')
    if _CONTROL_OR_SEPARATOR.search(value):
        raise ValueError('批次号不能包含 /、\\ 或控制字符')
    return value


def managed_tags_for(combination_name: str | None, batch_no: str) -> list[str]:
    if not combination_name:
        return []
    tags = [combination_name]
    if batch_no:
        tags.append(f'{combination_name} / {batch_no}')
    return tags


def resolve_batch_no(explicit: str, metadata: dict) -> str:
    if explicit:
        return normalize_batch_no(explicit)
    raw = (metadata or {}).get('lot_id')
    if not isinstance(raw, str):
        return ''
    try:
        return normalize_batch_no(raw)
    except ValueError:
        return ''
```

在 `apps/datafiles/models.py` 增加：

```python
class DataCombination(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='data_combinations',
    )
    name = models.CharField(max_length=40)
    name_key = models.CharField(max_length=80)
    description = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'name_key'],
                name='uniq_combination_owner_name_key',
            ),
        ]

    def save(self, *args, **kwargs):
        from apps.datafiles.combination_service import normalize_combination_name
        self.name = normalize_combination_name(self.name)
        self.name_key = self.name.casefold()
        super().save(*args, **kwargs)
```

在 `DataFile` 字段区增加：

```python
    combination = models.ForeignKey(
        'datafiles.DataCombination',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='files',
    )
    batch_no = models.CharField(max_length=40, blank=True, default='', db_index=True)
```

- [ ] **Step 4: 生成迁移**

Run: `.venv/Scripts/python.exe -X utf8 manage.py makemigrations datafiles --name datafile_combination_batch_no`

Expected: 生成 `apps/datafiles/migrations/0008_datafile_combination_batch_no.py`，包含 `CreateModel(DataCombination)`、`AddField(combination)`、`AddField(batch_no)`。

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_combination_service -v 2`

Expected: PASS，5 个用例通过。

- [ ] **Step 6: 条件提交**

仅在用户授权提交时执行：

```bash
git add apps/datafiles/combination_service.py apps/datafiles/models.py apps/datafiles/migrations/0008_datafile_combination_batch_no.py test/backend/test_combination_service.py
git commit -m "feat(data): add combination model and managed tag rules"
```

---

### Task 2: 组合 CRUD 与批量归组 API

**Files:**

- Create: `apps/datafiles/views/combination_views.py`
- Modify: `apps/datafiles/serializers.py`
- Modify: `apps/datafiles/views/__init__.py`
- Modify: `apps/datafiles/urls.py`
- Test: `test/backend/test_combinations_api.py`

**Interfaces:**

- Consumes: Task 1 的 `DataCombination`、`normalize_combination_name`、`normalize_batch_no`。
- Produces:
  - `GET/POST /api/v1/combinations/`
  - `PATCH/DELETE /api/v1/combinations/{id}/`
  - `POST /api/v1/files/assign_combination/`
  - `DataCombinationSerializer`

- [ ] **Step 1: 写失败 API 测试**

创建 `test/backend/test_combinations_api.py`：

```python
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.datafiles.models import DataCombination, DataFile


class CombinationApiTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user('combo_api_owner', password='x')
        self.other = User.objects.create_user('combo_api_other', password='x')
        self.client.force_authenticate(self.owner)

    def _file(self, owner, filename, **extra):
        return DataFile.objects.create(
            owner=owner, filename=filename,
            file_path=f'data/{owner.username}/single/{filename}',
            file_size=1, format_type='CTA8290D', status='ready', **extra,
        )

    def test_create_list_rename_and_case_insensitive_duplicate(self):
        resp = self.client.post('/api/v1/combinations/', {'name': 'Gage'}, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        combo_id = resp.data['id']
        dup = self.client.post('/api/v1/combinations/', {'name': 'gage'}, format='json')
        self.assertEqual(dup.status_code, 400)
        self.assertEqual(dup.data['code'], 'duplicate_combination')
        renamed = self.client.patch(
            f'/api/v1/combinations/{combo_id}/', {'name': 'Gage Lab'}, format='json')
        self.assertEqual(renamed.status_code, 200, renamed.data)
        listed = self.client.get('/api/v1/combinations/')
        self.assertEqual([row['name'] for row in listed.data], ['Gage Lab'])

    def test_rename_recomputes_tags_without_touching_file_row(self):
        combo = DataCombination.objects.create(owner=self.owner, name='gage')
        row = self._file(self.owner, 'a.csv', combination=combo, batch_no='BE01-1', tags=['manual'])
        before = row.updated_at
        resp = self.client.patch(
            f'/api/v1/combinations/{combo.id}/', {'name': 'buyoff'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        row.refresh_from_db()
        self.assertEqual(row.updated_at, before)
        detail = self.client.get(f'/api/v1/files/{row.id}/')
        self.assertEqual(detail.data['managed_tags'], ['buyoff', 'buyoff / BE01-1'])
        self.assertEqual(detail.data['tags'], ['manual'])

    def test_delete_combination_keeps_file_and_manual_tags(self):
        combo = DataCombination.objects.create(owner=self.owner, name='gage')
        row = self._file(self.owner, 'a.csv', combination=combo, batch_no='BE01-1', tags=['manual'])
        resp = self.client.delete(f'/api/v1/combinations/{combo.id}/')
        self.assertEqual(resp.status_code, 204)
        row.refresh_from_db()
        self.assertIsNone(row.combination)
        self.assertEqual(row.batch_no, 'BE01-1')
        self.assertEqual(row.tags, ['manual'])

    def test_bulk_assign_is_owner_scoped_and_atomic(self):
        combo = DataCombination.objects.create(owner=self.owner, name='gage')
        mine = self._file(self.owner, 'mine.csv')
        theirs = self._file(self.other, 'theirs.csv')
        resp = self.client.post('/api/v1/files/assign_combination/', {
            'file_ids': [mine.id, theirs.id],
            'combination_id': combo.id,
            'batch_no': 'BE01-1',
        }, format='json')
        self.assertEqual(resp.status_code, 404)
        mine.refresh_from_db()
        self.assertIsNone(mine.combination)

    def test_bulk_assign_preserves_clears_and_sets_batch_number(self):
        combo = DataCombination.objects.create(owner=self.owner, name='gage')
        row = self._file(self.owner, 'a.csv', batch_no='OLD')
        url = '/api/v1/files/assign_combination/'
        self.client.post(url, {'file_ids': [row.id], 'combination_id': combo.id}, format='json')
        row.refresh_from_db()
        self.assertEqual(row.batch_no, 'OLD')
        self.client.post(url, {
            'file_ids': [row.id], 'combination_id': combo.id, 'batch_no': '',
        }, format='json')
        row.refresh_from_db()
        self.assertEqual(row.batch_no, '')

    def test_other_users_combination_is_not_visible_or_assignable(self):
        theirs = DataCombination.objects.create(owner=self.other, name='gage')
        mine = self._file(self.owner, 'mine.csv')
        resp = self.client.get('/api/v1/combinations/')
        self.assertEqual(resp.data, [])
        resp = self.client.post('/api/v1/files/assign_combination/', {
            'file_ids': [mine.id], 'combination_id': theirs.id,
        }, format='json')
        self.assertEqual(resp.status_code, 404)
        mine.refresh_from_db()
        self.assertIsNone(mine.combination)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_combinations_api -v 2`

Expected: FAIL，组合路由返回 404。

- [ ] **Step 3: 实现序列化器与视图**

在 `apps/datafiles/serializers.py` 增加：

```python
from django.db.models import Count, Q
from apps.datafiles.models import DataCombination


class DataCombinationSerializer(serializers.ModelSerializer):
    file_count = serializers.IntegerField(read_only=True)
    batched_file_count = serializers.IntegerField(read_only=True)
    unbatched_file_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = DataCombination
        fields = [
            'id', 'name', 'description', 'file_count', 'batched_file_count',
            'unbatched_file_count', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_name(self, value):
        from apps.datafiles.combination_service import normalize_combination_name
        try:
            return normalize_combination_name(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))
```

创建 `apps/datafiles/views/combination_views.py`：

```python
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.errors import error_response
from apps.datafiles.combination_service import normalize_batch_no
from apps.datafiles.models import DataCombination, DataFile
from apps.datafiles.serializers import DataCombinationSerializer, DataFileSerializer


class DataCombinationViewSet(viewsets.ModelViewSet):
    serializer_class = DataCombinationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        return DataCombination.objects.filter(owner=self.request.user).annotate(
            file_count=Count('files'),
            batched_file_count=Count('files', filter=~Q(files__batch_no='')),
            unbatched_file_count=Count('files', filter=Q(files__batch_no='')),
        ).order_by('name')

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def create(self, request, *args, **kwargs):
        name = request.data.get('name', '')
        if isinstance(name, str) and DataCombination.objects.filter(
            owner=request.user, name_key=name.strip().casefold(),
        ).exists():
            return error_response('duplicate_combination', '组合名已存在')
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        name = request.data.get('name', instance.name)
        if isinstance(name, str) and DataCombination.objects.filter(
            owner=request.user, name_key=name.strip().casefold(),
        ).exclude(pk=instance.pk).exists():
            return error_response('duplicate_combination', '组合名已存在')
        return super().update(request, *args, **kwargs)


class AssignCombinationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw_ids = request.data.get('file_ids')
        if not isinstance(raw_ids, list) or not raw_ids or not all(
            isinstance(i, int) and not isinstance(i, bool) for i in raw_ids
        ):
            return error_response('file_ids_required', 'file_ids 必须是非空整数列表')

        if 'combination_id' not in request.data:
            return error_response('combination_id_required', 'combination_id 必填')
        combination_id = request.data.get('combination_id')
        combination = None
        if combination_id is not None:
            try:
                combination_id = int(combination_id)
            except (TypeError, ValueError):
                return error_response('validation_error', 'combination_id 必须是整数')
            combination = get_object_or_404(
                DataCombination, pk=combination_id, owner=request.user)

        rows = list(DataFile.objects.filter(owner=request.user, id__in=raw_ids))
        if len(rows) != len(set(raw_ids)):
            return error_response(
                'file_not_found_or_not_owned', '部分文件不存在或不属于当前用户', 404)

        update_fields = ['combination', 'updated_at']
        if 'batch_no' in request.data:
            raw_batch_no = request.data.get('batch_no')
            try:
                batch_no = normalize_batch_no(raw_batch_no)
            except ValueError as exc:
                return error_response('validation_error', str(exc))
        else:
            batch_no = None

        with transaction.atomic():
            for row in rows:
                row.combination = combination
                if batch_no is not None:
                    row.batch_no = batch_no
                    if 'batch_no' not in update_fields:
                        update_fields.append('batch_no')
                row.save(update_fields=update_fields)

        return Response(DataFileSerializer(rows, many=True).data)
```

在 `apps/datafiles/views/__init__.py` 导出：

```python
from .combination_views import DataCombinationViewSet, AssignCombinationView
```

在 `apps/datafiles/urls.py` 注册：

```python
router.register(r'combinations', DataCombinationViewSet, basename='combination')

urlpatterns = [
    path('files/assign_combination/', AssignCombinationView.as_view(), name='file-assign-combination'),
    # 现有路由保持不变；files/assign_combination/ 必须排在 router include 前。
]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_combinations_api -v 2`

Expected: PASS，6 个用例通过。

- [ ] **Step 5: 条件提交**

```bash
git add apps/datafiles/serializers.py apps/datafiles/views/combination_views.py apps/datafiles/views/__init__.py apps/datafiles/urls.py test/backend/test_combinations_api.py
git commit -m "feat(data): add combination CRUD and assignment API"
```

---

### Task 3: 文件序列化、组合筛选、动态标签查询与下拉 DTO

**Files:**

- Modify: `apps/datafiles/serializers.py`
- Modify: `apps/datafiles/views/file_views.py`
- Modify: `apps/datafiles/views/batch_views.py`
- Test: `test/backend/test_combination_file_queries.py`

**Interfaces:**

- Consumes: Task 1 的 `managed_tags_for`、Task 2 的 `DataCombination`。
- Produces:
  - 文件 API 字段 `combination_id/combination_name/batch_no/managed_tags`
  - `GET /files/?combination_id=&batch_no=&tag=&search=`
  - `POST /files/list_tags/` 返回 `managed_tags`
  - `GET /files/options/` 返回组合与批次号标量
  - `GET /batch-dirs/` 文件行返回组合与系统标签

- [ ] **Step 1: 写失败查询测试**

创建 `test/backend/test_combination_file_queries.py`：

```python
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.datafiles.models import DataCombination, DataFile


class CombinationFileQueryTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user('combo_query_owner', password='x')
        self.client.force_authenticate(self.owner)
        self.gage = DataCombination.objects.create(owner=self.owner, name='gage')
        self.buyoff = DataCombination.objects.create(owner=self.owner, name='buyoff')
        self.a = self._file('a.csv', self.gage, 'BE01-1', ['shared'])
        self.b = self._file('b.csv', self.buyoff, 'BE01-1', ['shared'])
        self.c = self._file('c.csv', self.gage, '', [])

    def _file(self, name, combination, batch_no, tags):
        return DataFile.objects.create(
            owner=self.owner, filename=name,
            file_path=f'data/{self.owner.username}/single/{name}',
            file_size=1, format_type='CTA8290D', status='ready',
            combination=combination, batch_no=batch_no, tags=tags,
        )

    def test_file_detail_contains_structured_fields_and_managed_tags(self):
        resp = self.client.get(f'/api/v1/files/{self.a.id}/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['combination_id'], self.gage.id)
        self.assertEqual(resp.data['combination_name'], 'gage')
        self.assertEqual(resp.data['batch_no'], 'BE01-1')
        self.assertEqual(resp.data['managed_tags'], ['gage', 'gage / BE01-1'])
        self.assertEqual(resp.data['tags'], ['shared'])

    def test_combination_and_batch_filters(self):
        resp = self.client.get('/api/v1/files/', {
            'combination_id': self.gage.id, 'batch_no': 'be01-1', 'include_hidden': 1,
        })
        self.assertEqual([row['id'] for row in resp.data['results']], [self.a.id])

    def test_managed_tag_exact_filter(self):
        resp = self.client.get('/api/v1/files/', {
            'tag': 'gage / be01-1', 'include_hidden': 1,
        })
        self.assertEqual([row['id'] for row in resp.data['results']], [self.a.id])

    def test_search_does_not_bypass_combination_filter(self):
        resp = self.client.get('/api/v1/files/', {
            'combination_id': self.gage.id, 'search': 'shared', 'include_hidden': 1,
        })
        self.assertEqual([row['id'] for row in resp.data['results']], [self.a.id])

    def test_search_matches_full_managed_tag(self):
        resp = self.client.get('/api/v1/files/', {
            'combination_id': self.gage.id,
            'search': 'gage / BE01-1',
            'include_hidden': 1,
        })
        self.assertEqual([row['id'] for row in resp.data['results']], [self.a.id])

    def test_list_tags_returns_manual_and_managed_sets(self):
        resp = self.client.post('/api/v1/files/list_tags/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIn('shared', resp.data['tags'])
        self.assertIn('gage', resp.data['tags'])
        self.assertIn('gage / BE01-1', resp.data['managed_tags'])
        self.assertNotIn('shared', resp.data['managed_tags'])

    def test_options_adds_scalar_combination_fields_without_tags(self):
        resp = self.client.get('/api/v1/files/options/', {'include_error': 1})
        self.assertEqual(resp.status_code, 200, resp.data)
        row = next(item for item in resp.data['results'] if item['id'] == self.a.id)
        self.assertEqual(row['combination_id'], self.gage.id)
        self.assertEqual(row['combination_name'], 'gage')
        self.assertEqual(row['batch_no'], 'BE01-1')
        self.assertNotIn('tags', row)
        self.assertNotIn('managed_tags', row)

    def test_twenty_manual_tags_do_not_consume_managed_tag_quota(self):
        tags = [f'tag-{index}' for index in range(20)]
        self.a.tags = tags
        self.a.save(update_fields=['tags'])
        resp = self.client.get(f'/api/v1/files/{self.a.id}/')
        self.assertEqual(resp.data['tags'], tags)
        self.assertEqual(resp.data['managed_tags'], ['gage', 'gage / BE01-1'])
        saved = self.client.post(
            f'/api/v1/files/{self.a.id}/set_tags/', {'tags': tags}, format='json')
        self.assertEqual(saved.status_code, 200, saved.data)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_combination_file_queries -v 2`

Expected: FAIL，文件响应缺少 `managed_tags`，组合筛选无效。

- [ ] **Step 3: 扩展序列化器**

在 `DataFileSerializer` 和 `DataFileListSerializer` 的 `fields` 中同时加入：

```python
            'combination_id', 'combination_name', 'batch_no', 'managed_tags',
```

在两个类中各加入：

```python
    combination_id = serializers.IntegerField(source='combination.id', read_only=True)
    combination_name = serializers.CharField(source='combination.name', read_only=True)
    managed_tags = serializers.SerializerMethodField()

    def get_managed_tags(self, obj) -> list[str]:
        from apps.datafiles.combination_service import managed_tags_for
        return managed_tags_for(
            obj.combination.name if obj.combination_id else None,
            obj.batch_no or '',
        )
```

- [ ] **Step 4: 修改文件查询**

在 `DataFileViewSet.get_queryset()` 开头改为，并在 `file_views.py` 顶部增加 `from django.db.models import Q`、`from rest_framework.exceptions import ValidationError`：

```python
        queryset = scoped_files(
            self.request, self.action,
            DataFile.objects.filter(owner=self.request.user).select_related('combination'),
        )
```

在搜索块前加入组合与批次号筛选：

```python
        combination_id = (self.request.query_params.get('combination_id') or '').strip()
        if combination_id:
            try:
                combination_id = int(combination_id)
            except (TypeError, ValueError):
                raise ValidationError({'combination_id': '必须是整数'})
            queryset = queryset.filter(combination_id=combination_id)

        batch_no = (self.request.query_params.get('batch_no') or '').strip()
        if batch_no:
            queryset = queryset.filter(batch_no__iexact=batch_no)
```

把现有搜索块替换为：

```python
        search = self.request.query_params.get('search', '').strip()
        if search:
            from apps.datafiles.combination_service import managed_tags_for
            search_lower = search.lower()
            tag_match_ids = []
            for row in queryset.values('id', 'tags', 'combination__name', 'batch_no'):
                values = list(row.get('tags') or []) + managed_tags_for(
                    row.get('combination__name'), row.get('batch_no') or '')
                if any(search_lower in str(value).lower() for value in values):
                    tag_match_ids.append(row['id'])
            queryset = queryset.filter(
                Q(filename__icontains=search)
                | Q(program_name__icontains=search)
                | Q(batch_name__icontains=search)
                | Q(combination__name__icontains=search)
                | Q(batch_no__icontains=search)
                | Q(id__in=tag_match_ids)
            )
```

把 `tag` 精确过滤替换为：

```python
        tag = self.request.query_params.get('tag', '').strip()
        if tag:
            tag_lower = tag.lower()
            matching_ids = []
            for row in queryset.values('id', 'tags', 'combination__name', 'batch_no'):
                from apps.datafiles.combination_service import managed_tags_for
                values = list(row.get('tags') or []) + managed_tags_for(
                    row.get('combination__name'), row.get('batch_no') or '')
                if any(str(value).lower() == tag_lower for value in values):
                    matching_ids.append(row['id'])
            queryset = queryset.filter(id__in=matching_ids)
```

- [ ] **Step 5: 扩展标签联想与 options**

把 `list_tags` 的遍历改为读取组合名和批次号，并在返回前加入系统标签：

```python
        managed_seen = {}
        for tags, combination_name, batch_no in (
            DataFile.objects.filter(owner=request.user, is_hidden=False)
            .values_list('tags', 'combination__name', 'batch_no')
        ):
            if isinstance(tags, list):
                for tag in tags:
                    if not isinstance(tag, str):
                        continue
                    cleaned = tag.strip()
                    if cleaned:
                        seen.setdefault(cleaned.lower(), cleaned)
            from apps.datafiles.combination_service import managed_tags_for
            for tag in managed_tags_for(combination_name, batch_no or ''):
                managed_seen.setdefault(tag.lower(), tag)
                seen.setdefault(tag.lower(), tag)
        if prefix:
            prefix_lower = prefix.lower()
            seen = {key: value for key, value in seen.items() if key.startswith(prefix_lower)}
            managed_seen = {
                key: value for key, value in managed_seen.items()
                if key.startswith(prefix_lower)
            }
        return Response({
            'tags': sorted(seen.values(), key=str.lower),
            'managed_tags': sorted(managed_seen.values(), key=str.lower),
        })
```

`list_tags` 的 prefix 过滤继续在最终集合上按 `startswith` 应用。

`options` 的 `.values()` 增加：

```python
                'combination_id', 'combination__name', 'batch_no',
```

并把返回行转换为显式键：

```python
        rows = [
            {
                **row,
                'combination_name': row.pop('combination__name'),
            }
            for row in rows
        ]
```

- [ ] **Step 6: 扩展批次目录 DTO**

在 `BatchDirListView` 的文件 `.values()` 增加：

```python
            'combination_id', 'combination__name', 'batch_no',
```

构造文件字典时加入：

```python
                'combination_id': df['combination_id'],
                'combination_name': df['combination__name'] or '',
                'batch_no': df['batch_no'] or '',
                'managed_tags': managed_tags_for(
                    df['combination__name'], df['batch_no'] or ''),
```

文件头部组合展示由前端 Task 6 根据这些字段完成。

- [ ] **Step 7: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_combination_file_queries test.backend.test_admin_files_api -v 2`

Expected: PASS；新查询测试与既有管理员作用域测试全部通过。

- [ ] **Step 8: 条件提交**

```bash
git add apps/datafiles/serializers.py apps/datafiles/views/file_views.py apps/datafiles/views/batch_views.py test/backend/test_combination_file_queries.py
git commit -m "feat(data): expose combination metadata and managed tag queries"
```

---

### Task 4: 上传、ZIP、目录与重传导入接线

**Files:**

- Modify: `apps/datafiles/views/_helpers.py`
- Modify: `apps/datafiles/views/file_views.py`
- Modify: `apps/datafiles/views/batch_views.py`
- Test: `test/backend/test_combination_import.py`
- Test: `apps/datafiles/tests_import_tx.py`

**Interfaces:**

- Consumes: Task 1 的 `normalize_batch_no/resolve_batch_no`，Task 2 的组合模型。
- Produces:
  - `_register_file(..., combination=None, batch_no_override='', tags=None)`
  - `_register_zip_batch(..., combination=None, batch_no_override='', tags=None)`
  - `/upload/` 表单字段 `combination_id/batch_no/tags`
  - `/batch-dirs/import/` 字段 `combination_id/batch_no/tags`
  - `combineFiles` 后端可选组合参数

- [ ] **Step 1: 写失败导入测试**

创建 `test/backend/test_combination_import.py`：

```python
import io
import json
import os
import shutil
import tempfile
import zipfile
from unittest.mock import patch

import pandas as pd
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from apps.datafiles.models import DataCombination, DataFile
from apps.datafiles.views import _helpers


MIN_CSV = (
    '[GENERAL],\nTester_Type,CTA8290DPlus,\n[Data]\n'
    'col1,col2\nu1,u2\nmin1,min2\nmax1,max2\n1,2\n3,4\n'
).encode()


def zip_bytes(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


class CombinationImportTests(APITestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix='combo-import-')
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        User = get_user_model()
        self.owner = User.objects.create_user('combo_import_owner', password='x')
        self.client.force_authenticate(self.owner)
        self.combo = DataCombination.objects.create(owner=self.owner, name='gage')

    def _upload(self, filename, content, **fields):
        uploaded = SimpleUploadedFile(filename, content)
        return self.client.post('/api/v1/upload/', {
            'files': uploaded, **fields,
        }, format='multipart')

    def test_single_upload_accepts_combination_batch_and_manual_tags(self):
        resp = self._upload(
            'a.csv', MIN_CSV,
            combination_id=str(self.combo.id),
            batch_no='BE01-2608130015',
            tags=json.dumps(['manual']),
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        row = DataFile.objects.get(filename='a.csv')
        self.assertEqual(row.combination_id, self.combo.id)
        self.assertEqual(row.batch_no, 'BE01-2608130015')
        self.assertEqual(row.tags, ['manual'])
        self.assertEqual(resp.data[0]['managed_tags'], [
            'gage', 'gage / BE01-2608130015',
        ])

    def test_invalid_combination_or_tags_fails_before_file_write(self):
        resp = self._upload(
            'bad.csv', MIN_CSV, combination_id='999', tags='["manual"]')
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(DataFile.objects.filter(filename='bad.csv').exists())
        resp = self._upload('bad2.csv', MIN_CSV, tags='not-json')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(DataFile.objects.filter(filename='bad2.csv').exists())

    def test_zip_uses_parser_lot_id_and_does_not_use_zip_name(self):
        parsed = (
            'CTA8290D', pd.DataFrame({'col1': [1], 'col2': [2]}),
            {'lot_id': 'BE01-2608130015'}, 1, 2, 'PTS',
        )
        with patch.object(_helpers, 'parse_file_meta', return_value=parsed):
            resp = self._upload(
                'LOT-NAME.zip', zip_bytes({'a.csv': MIN_CSV}),
                combination_id=str(self.combo.id),
            )
        self.assertEqual(resp.status_code, 201, resp.data)
        row = DataFile.objects.get(filename='a.csv')
        self.assertEqual(row.batch_name, 'LOT-NAME')
        self.assertEqual(row.batch_no, 'BE01-2608130015')

    def test_zip_without_lot_id_leaves_batch_number_empty(self):
        parsed = (
            'CTA8290D', pd.DataFrame({'col1': [1], 'col2': [2]}),
            {}, 1, 2, 'PTS',
        )
        with patch.object(_helpers, 'parse_file_meta', return_value=parsed):
            resp = self._upload(
                'LOT-NAME.zip', zip_bytes({'a.csv': MIN_CSV}),
                combination_id=str(self.combo.id),
            )
        self.assertEqual(resp.status_code, 201, resp.data)
        row = DataFile.objects.get(filename='a.csv')
        self.assertEqual(row.batch_no, '')
        self.assertEqual(resp.data[0]['managed_tags'], ['gage'])

    def test_reupload_updates_combination_and_merges_manual_tags(self):
        first = self._upload('LOT-R.zip', zip_bytes({'a.csv': MIN_CSV}), tags='["old"]')
        self.assertEqual(first.status_code, 201, first.data)
        second = self._upload(
            'LOT-R.zip', zip_bytes({'a.csv': MIN_CSV}),
            combination_id=str(self.combo.id), tags='["new"]',
        )
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(DataFile.objects.filter(filename='a.csv').count(), 1)
        row = DataFile.objects.get(filename='a.csv')
        self.assertEqual(row.combination_id, self.combo.id)
        self.assertEqual({tag.lower() for tag in row.tags}, {'old', 'new'})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_combination_import -v 2`

Expected: FAIL，上传字段被忽略，ZIP 批次号为空。

- [ ] **Step 3: 扩展注册服务**

修改 `_register_file` 签名与创建字段：

```python
def _register_file(user, file_path, file_type='single', batch_name='', sub_batch='',
                   source_mtime=None, parsed=None, combination=None,
                   batch_no_override='', tags=None):
```

在 `DataFile.objects.create()` 中加入：

```python
        combination=combination,
        batch_no=resolve_batch_no(batch_no_override, metadata),
        tags=normalize_tags(tags or []),
```

在 `_register_zip_batch` 签名中加入相同三个参数，并把调用改为：

```python
                    _register_file(
                        user, fp, 'batch', batch_name, sub_batch,
                        parsed=parsed, combination=combination,
                        batch_no_override=batch_no_override, tags=tags,
                    )
```

- [ ] **Step 4: 实现重传元数据更新**

在 `_helpers.py` 增加：

```python
def _merge_tags(existing, incoming):
    from apps.datafiles.serializers import normalize_tags
    merged = list(existing or [])
    seen = {str(tag).lower() for tag in merged}
    for tag in normalize_tags(incoming or []):
        if tag.lower() not in seen:
            merged.append(tag)
            seen.add(tag.lower())
    return normalize_tags(merged)


def _refresh_existing_import_row(row, combination, batch_no_override, tags, parsed):
    from rest_framework.exceptions import ValidationError
    from apps.datafiles.combination_service import resolve_batch_no
    update_fields = []
    if combination is not None and row.combination_id != combination.id:
        row.combination = combination
        update_fields.append('combination')
    resolved = resolve_batch_no(batch_no_override, parsed[2])
    if batch_no_override or (resolved and not row.batch_no):
        if row.batch_no != resolved:
            row.batch_no = resolved
            update_fields.append('batch_no')
    if tags:
        try:
            merged = _merge_tags(row.tags, tags)
        except ValidationError as exc:
            logger.warning(
                '_refresh_existing_import_row: tag merge rejected id=%s: %s',
                row.id, exc,
            )
            merged = row.tags
        if merged != row.tags:
            row.tags = merged
            update_fields.append('tags')
    if update_fields:
        row.save(update_fields=[*update_fields, 'updated_at'])
```

在 ZIP 导入中，把现有路径集合改为路径到行的映射：

```python
    existing_rows = {
        os.path.normpath(resolve_file_path(row.file_path)): row
        for row in DataFile.objects.filter(
            owner=user, file_type='batch', batch_name=batch_name,
        )
    }
    existing_paths = set(existing_rows)
    batch_base = _user_upload_dir(user, 'batch')
    created = []
    for fp in csv_paths:
        normalized = os.path.normpath(fp)
        if normalized in existing_paths:
            parsed = parse_file_meta(fp)
            _refresh_existing_import_row(
                existing_rows[normalized], combination,
                batch_no_override, tags, parsed)
            continue
        _, sub_batch = _batch_ctx(fp, batch_base)
        parsed = parse_file_meta(fp)
        try:
            with transaction.atomic():
                created.append(
                    _register_file(
                        user, fp, 'batch', batch_name, sub_batch,
                        parsed=parsed, combination=combination,
                        batch_no_override=batch_no_override, tags=tags,
                    )
                )
        except Exception:
            logger.warning(
                '_register_zip_batch: failed to register %s', fp,
                exc_info=True,
            )
            continue
    return created, None
```

目录导入使用同样的 `path -> row` 映射，不新增逐文件查询。

- [ ] **Step 5: 上传入口解析组合与标签**

在 `FileUploadView.post` 文件校验后、写盘前加入，并在 `file_views.py` 顶部补充 `import json`、`from rest_framework import serializers`、`from apps.datafiles.models import DataCombination`：

```python
        combination = None
        combination_id = (request.data.get('combination_id') or '').strip()
        if combination_id:
            try:
                combination = DataCombination.objects.get(
                    pk=int(combination_id), owner=request.user)
            except (TypeError, ValueError, DataCombination.DoesNotExist):
                return error_response('combination_not_found', '组合不存在', 404)

        raw_tags = request.data.get('tags')
        if raw_tags:
            try:
                manual_tags = normalize_tags(json.loads(raw_tags))
            except (TypeError, ValueError, serializers.ValidationError):
                return error_response('validation_error', 'tags 必须是 JSON 数组')
        else:
            manual_tags = []

        try:
            batch_no_override = normalize_batch_no(request.data.get('batch_no') or '')
        except ValueError as exc:
            return error_response('validation_error', str(exc))
```

把 ZIP 和单文件注册调用传入 `combination/batch_no_override/manual_tags`。

- [ ] **Step 6: 目录导入与物理组合接线**

`BatchDirImportView.post` 使用同一组参数解析代码；把参数传给 `_register_file`。现有路径命中时调用 `_refresh_existing_import_row`。

`DataFileViewSet.combine` 增加可选 `combination_id/batch_no`：

- 校验组合属于当前 owner；
- 在现有 DB 事务中同时写入 `combination/batch_no`；
- 不传组合时保持原行为；
- `uncombine` 不清空这两个字段。

- [ ] **Step 7: 补事务边界测试**

在 `apps/datafiles/tests_import_tx.py` 增加：

```python
    def test_combination_metadata_does_not_move_parse_into_transaction(self):
        parser = self._patch_parser()
        created, error = _helpers._register_zip_batch(
            self.user, _build_zip(['a.csv']), 'combo-tx.zip',
            combination=None, batch_no_override='BE01-1', tags=['manual'])
        self.assertIsNone(error)
        self.assertEqual(len(created), 1)
        self.assertEqual(parser.in_atomic_block, [False])
        self.assertEqual(created[0].batch_no, 'BE01-1')
        self.assertEqual(created[0].tags, ['manual'])
```

- [ ] **Step 8: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_combination_import apps.datafiles.tests_import_tx apps.datafiles.tests.ZipUploadTests -v 2`

Expected: PASS；新导入测试、事务边界和既有 ZIP 用例全部通过。

- [ ] **Step 9: 条件提交**

```bash
git add apps/datafiles/views/_helpers.py apps/datafiles/views/file_views.py apps/datafiles/views/batch_views.py test/backend/test_combination_import.py apps/datafiles/tests_import_tx.py
git commit -m "feat(data): attach combinations during all import paths"
```

---

### Task 5: 前端类型、API 与动态标签纯函数

**Files:**

- Modify: `frontend/src/types/index.ts`
- Create: `frontend/src/api/combinations.ts`
- Modify: `frontend/src/api/datafiles.ts`
- Create: `frontend/src/utils/combinationTags.ts`
- Test: `frontend/test/unit/combinationTags.spec.ts`

**Interfaces:**

- Produces:
  - `DataCombination`
  - `DataFile.combination_id/combination_name/batch_no/managed_tags`
  - `combinationsApi.list/create/update/remove`
  - `datafilesApi.assignCombination`
  - `datafilesApi.combineFiles(ids, batchName, options)`
  - `datafilesApi.upload/uploadMultiple(..., options)`
  - `managedTagsFor`
  - `mergeDisplayTags`

- [ ] **Step 1: 写失败纯函数测试**

创建 `frontend/test/unit/combinationTags.spec.ts`：

```typescript
import { describe, expect, it } from 'vitest'
import { managedTagsFor, mergeDisplayTags } from '../../src/utils/combinationTags'

describe('combinationTags', () => {
  it('无批次只生成组合标签', () => {
    expect(managedTagsFor('gage', '')).toEqual(['gage'])
  })

  it('有批次生成组合与组合批次标签', () => {
    expect(managedTagsFor('gage', 'BE01-2608130015')).toEqual([
      'gage',
      'gage / BE01-2608130015',
    ])
  })

  it('未分组不生成系统标签', () => {
    expect(managedTagsFor(null, 'BE01-2608130015')).toEqual([])
  })

  it('展示合并且大小写不敏感去重', () => {
    expect(mergeDisplayTags(['Gage', 'manual'], ['gage', 'gage / BE01'])).toEqual([
      'Gage',
      'manual',
      'gage / BE01',
    ])
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npx vitest run test/unit/combinationTags.spec.ts`

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现类型、API 与纯函数**

在 `frontend/src/types/index.ts` 增加：

```typescript
export interface DataCombination {
  id: number
  name: string
  description: string
  file_count: number
  batched_file_count: number
  unbatched_file_count: number
  created_at: string
  updated_at: string
}
```

`DataFile` 增加：

```typescript
  combination_id?: number | null
  combination_name?: string | null
  batch_no?: string
  managed_tags?: string[]
```

`FileOption` 增加：

```typescript
  combination_id: number | null
  combination_name: string | null
  batch_no: string
```

创建 `frontend/src/utils/combinationTags.ts`：

```typescript
export function managedTagsFor(
  combinationName: string | null | undefined,
  batchNo: string | undefined,
): string[] {
  if (!combinationName) return []
  const tags = [combinationName]
  if (batchNo) tags.push(`${combinationName} / ${batchNo}`)
  return tags
}

export function mergeDisplayTags(manual: string[], managed: string[]): string[] {
  const result: string[] = []
  const seen = new Set<string>()
  for (const tag of [...manual, ...managed]) {
    const key = tag.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    result.push(tag)
  }
  return result
}
```

创建 `frontend/src/api/combinations.ts`：

```typescript
import api from './index'
import type { DataCombination } from '../types'

export interface CombinationInput {
  name: string
  description?: string
}

export const combinationsApi = {
  list: () => api.get<DataCombination[]>('/combinations/'),
  create: (input: CombinationInput) => api.post<DataCombination>('/combinations/', input),
  update: (id: number, input: Partial<CombinationInput>) =>
    api.patch<DataCombination>(`/combinations/${id}/`, input),
  remove: (id: number) => api.delete(`/combinations/${id}/`),
}
```

在 `frontend/src/api/datafiles.ts` 增加：

```typescript
export interface UploadOptions {
  combinationId?: number | null
  batchNo?: string
  tags?: string[]
}

export interface AssignCombinationInput {
  fileIds: number[]
  combinationId: number | null
  batchNo?: string | null
}

export interface CombineFilesOptions {
  combinationId?: number | null
  batchNo?: string
}
```

上传方法保留原回调参数，新增第三参数：

```typescript
  upload(file: File, onProgress?: (pct: number) => void, options: UploadOptions = {}) {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('last_modified', String(file.lastModified))
    appendUploadOptions(formData, options)
    return api.post('/upload/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (e.total && onProgress) onProgress(Math.round((e.loaded * 100) / e.total))
      },
    })
  },
```

在 `datafiles.ts` 增加共用表单辅助函数，`upload` 与 `uploadMultiple` 都调用：

```typescript
function appendUploadOptions(formData: FormData, options: UploadOptions) {
  if (options.combinationId != null) formData.append('combination_id', String(options.combinationId))
  if (options.batchNo) formData.append('batch_no', options.batchNo)
  if (options.tags?.length) formData.append('tags', JSON.stringify(options.tags))
}
```

`uploadMultiple(files, onProgress?, options = {})` 在追加 files 和 `last_modified` 后调用 `appendUploadOptions(formData, options)`，其余上传逻辑不变。

```typescript
  assignCombination(input: AssignCombinationInput) {
    return api.post<DataFile[]>('/files/assign_combination/', {
      file_ids: input.fileIds,
      combination_id: input.combinationId,
      ...(input.batchNo !== undefined ? { batch_no: input.batchNo } : {}),
    })
  },
  combineFiles(ids: number[], batchName: string, options: CombineFilesOptions = {}) {
    return api.post<{ combined: number; batch_name: string; files: DataFile[] }>(
      '/files/combine/', {
        ids,
        batch_name: batchName,
        ...(options.combinationId !== undefined
          ? { combination_id: options.combinationId }
          : {}),
        ...(options.batchNo ? { batch_no: options.batchNo } : {}),
      },
    )
  },
```

`ListFilesParams` 增加 `combination_id?: number`、`batch_no?: string`。`listTags` 返回类型改为：

```typescript
api.post<{ tags: string[]; managed_tags: string[] }>('/files/list_tags/', { prefix })
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd frontend && npx vitest run test/unit/combinationTags.spec.ts test/unit/fileSelectModel.spec.ts`

Expected: PASS。

- [ ] **Step 5: 条件提交**

```bash
git add frontend/src/types/index.ts frontend/src/api/combinations.ts frontend/src/api/datafiles.ts frontend/src/utils/combinationTags.ts frontend/test/unit/combinationTags.spec.ts
git commit -m "feat(data): add combination frontend contracts"
```

---

### Task 6: 组合数据页与来源批次目录

**Files:**

- Create: `frontend/src/pages/data/components/combination/CombinationDataTab.vue`
- Create: `frontend/src/pages/data/components/combination/CombinationToolbar.vue`
- Create: `frontend/src/pages/data/components/combination/CombinationEditDialog.vue`
- Create: `frontend/src/pages/data/components/combination/CombinationFileGroups.vue`
- Create: `frontend/src/pages/data/components/combination/BatchDirectorySection.vue`
- Modify: `frontend/src/pages/data/DataManagement.vue`
- Test: `frontend/e2e/data/combination-data.spec.ts`

**Interfaces:**

- Consumes: Task 5 的 `combinationsApi`、`datafilesApi.listFiles`、`DataCombination`。
- Produces:
  - `CombinationDataTab` props `{ activeFileId?: number }`
  - emits `file-selected`、`total-change`、`open-report`
  - `open-report` payload `{ kind: 'gage' | 'buyoff'; combinationId: number | null; combinationName: string | null; fileIds: number[] }`

- [ ] **Step 1: 写失败浏览器接线测试**

创建 `frontend/e2e/data/combination-data.spec.ts`：

```typescript
import { test, expect } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import { gotoApp } from '../helpers/nav'
import { makeZip } from '../helpers/zip'
import { cleanupQuiet, deleteBatchQuiet, deleteFilesByNameQuiet } from '../helpers/cleanup'

test.describe('组合数据', { tag: ['@p2', '@data'] }, () => {
  test('创建、重命名与删除组合', async ({ page }) => {
    await gotoApp(page, '/data')
    await page.locator('.tabs-nav .tab-btn').filter({ hasText: '组合数据' }).click()

    const name = `e2e_combo_${Date.now()}`
    try {
      await page.getByTestId('combination-create').click()
      await page.getByTestId('combination-name-input').fill(name)
      await page.getByTestId('combination-save').click()
      await expect(page.getByTestId('combination-current-name')).toHaveText(name)

      await page.getByTestId('combination-rename').click()
      await page.getByTestId('combination-name-input').fill(`${name}_lab`)
      await page.getByTestId('combination-save').click()
      await expect(page.getByTestId('combination-current-name')).toHaveText(`${name}_lab`)

      await page.getByTestId('combination-delete').click()
      await page.getByRole('button', { name: '确认删除组合' }).click()
      await expect(page.getByTestId('combination-current-name')).toHaveCount(0)
    } finally {
      await page.evaluate(async (comboName) => {
        const token = localStorage.getItem('access_token')
        const headers = token ? { Authorization: `Bearer ${token}` } : {}
        const resp = await fetch('/api/v1/combinations/', { headers })
        const rows = await resp.json()
        const row = rows.find((item: any) => item.name === comboName || item.name === `${comboName}_lab`)
        if (row) await fetch(`/api/v1/combinations/${row.id}/`, { method: 'DELETE', headers })
      }, name)
    }
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npx playwright test e2e/data/combination-data.spec.ts --project=P2 --workers=1 --retries=0`

Expected: FAIL，页面不存在“组合数据”Tab 或 `combination-create`。

- [ ] **Step 3: 实现组合编辑对话框与工具栏**

`CombinationEditDialog.vue`：

```vue
<template>
  <el-dialog
    :model-value="visible"
    :title="mode === 'create' ? '新建组合' : '重命名组合'"
    width="420px"
    @update:model-value="emit('update:visible', $event)"
  >
    <el-input
      v-model="name"
      data-testid="combination-name-input"
      maxlength="40"
      placeholder="例如 gage、buyoff、实验室调试"
    />
    <template #footer>
      <el-button @click="emit('update:visible', false)">取消</el-button>
      <el-button
        type="primary"
        :disabled="!name.trim()"
        data-testid="combination-save"
        @click="submit"
      >保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  visible: boolean
  mode: 'create' | 'rename'
  initialName?: string
}>()
const emit = defineEmits<{
  'update:visible': [value: boolean]
  submit: [name: string]
}>()
const name = ref('')
watch(() => [props.visible, props.initialName], () => {
  if (props.visible) name.value = props.initialName ?? ''
})
function submit() {
  emit('submit', name.value.trim())
}
</script>
```

`CombinationToolbar.vue` 使用 `el-select-v2` 展示组合，按钮固定 `data-testid`：

```vue
<el-select-v2
  :model-value="activeId"
  :options="options"
  filterable
  placeholder="选择组合"
  popper-class="dp-combination-select-popper"
  data-testid="combination-select"
  @update:model-value="emit('select', $event)"
/>
<el-button data-testid="combination-create" @click="emit('create')">新建组合</el-button>
<el-button :disabled="activeId == null" data-testid="combination-rename" @click="emit('rename')">重命名</el-button>
<el-button :disabled="activeId == null" data-testid="combination-delete" @click="emit('delete')">删除组合</el-button>
```

样式只使用 `var(--bg-2)`、`var(--border-2)`、`var(--text)`、`var(--text-2)`，不写死颜色。

- [ ] **Step 4: 实现组合页壳与文件分组**

`CombinationDataTab.vue` 的核心状态与动作，Vue import 使用 `computed, onActivated, onMounted, ref, watch`：

```typescript
const combinations = ref<DataCombination[]>([])
const files = ref<DataFile[]>([])
const activeId = ref<number | null>(null)
const dialogMode = ref<'create' | 'rename'>('create')
const dialogVisible = ref(false)

async function loadAll() {
  const [comboResp, fileResp] = await Promise.all([
    combinationsApi.list(),
    datafilesApi.listFiles({ page_size: 10000, include_hidden: 1 }),
  ])
  combinations.value = Array.isArray(comboResp.data) ? comboResp.data : []
  files.value = fileResp.data.results ?? fileResp.data
  if (activeId.value != null && !combinations.value.some(c => c.id === activeId.value)) {
    activeId.value = null
  }
}

const activeCombination = computed(() =>
  combinations.value.find(c => c.id === activeId.value) ?? null)
const visibleFiles = computed(() => files.value.filter(
  file => (file.combination_id ?? null) === activeId.value,
))
const total = computed(() => visibleFiles.value.length)
watch(total, value => emit('total-change', value), { immediate: true })
onMounted(loadAll)
onActivated(loadAll)
```

新建调用 `combinationsApi.create`，成功后把 `activeId` 设为返回 id；重命名调用 `combinationsApi.update`；两者随后 `await loadAll()`。删除用 `ElMessageBox.confirm`，确认按钮文案为“确认删除组合”，成功后把 `activeId` 置空并刷新。

`CombinationFileGroups.vue` 分组规则：

```typescript
const groups = computed(() => {
  const batched = new Map<string, DataFile[]>()
  const unbatched: DataFile[] = []
  for (const file of props.files) {
    const key = (file.batch_no || '').trim().toLowerCase()
    if (!key) {
      unbatched.push(file)
      continue
    }
    const list = batched.get(key) ?? []
    list.push(file)
    batched.set(key, list)
  }
  return {
    batched: [...batched.entries()].map(([key, rows]) => ({
      key,
      label: rows[0].batch_no || key,
      files: rows,
    })),
    unbatched,
  }
})
```

模板先渲染“有批次文件”分组，再渲染“无批次文件”；每组使用现有 `BatchFilesTable`，并显示组合名与批次号。

`BatchDirectorySection.vue` 只包一层 `el-collapse`，内部复用现有 `BatchDataTab`，标题为“来源批次目录（ZIP / SFTP）”；不向上转发它的 `total-change`，避免覆盖组合页角标。组合页同时渲染 `FileUploadArea`，监听 `@upload-success="loadAll"` 并调用 `filesStore.notifyFilesChanged()`；根节点 testid 为 `combination-upload`，Task 7 会把当前组合与内联导入设置传入。

- [ ] **Step 5: 接入数据管理 Tab**

`DataManagement.vue`：

```typescript
import CombinationDataTab from './components/combination/CombinationDataTab.vue'

const tabs = [
  { key: 'files', label: '文件列表', icon: '📋' },
  { key: 'batch', label: '组合数据', icon: '🧪' },
  { key: 'view', label: '查看数据', icon: '🔍' },
  { key: 'export', label: '导出工具', icon: '📥' },
  { key: 'compare', label: '文件对比', icon: '📁' },
  { key: 'gage', label: 'Gage Summary', icon: '📊' },
  { key: 'buyoff', label: 'Buyoff Form', icon: '📝' },
]
```

模板把 `<BatchDataTab>` 替换为：

```vue
<CombinationDataTab
  :active-file-id="activeFileId ?? undefined"
  @file-selected="onFileManagerSelect"
  @total-change="batchTotal = $event"
  @open-report="onOpenCombinationReport"
/>
```

`onOpenCombinationReport` 在本任务先落地最小上下文，Task 8 再扩展 Gage/Buyoff 候选过滤：

```typescript
interface ReportContext {
  kind: 'gage' | 'buyoff'
  combinationId: number | null
  combinationName: string | null
  fileIds: number[]
}
const reportContext = ref<ReportContext | null>(null)

function onOpenCombinationReport(payload: ReportContext) {
  reportContext.value = payload
  activeTab.value = payload.kind
}
```

- [ ] **Step 6: 运行浏览器测试确认通过**

Run: `cd frontend && npx playwright test e2e/data/combination-data.spec.ts --project=P2 --workers=1 --retries=0`

Expected: PASS，1 条用例通过；light/night 各走查一次新建、重命名、删除弹窗。

- [ ] **Step 7: 条件提交**

```bash
git add frontend/src/pages/data/components/combination frontend/src/pages/data/DataManagement.vue frontend/e2e/data/combination-data.spec.ts
git commit -m "feat(data): add combination data tab"
```

---

### Task 7: 文件列表标签、组合筛选与上传设置

**Files:**

- Create: `frontend/src/pages/data/components/FileTagsCell.vue`
- Create: `frontend/src/pages/data/components/ImportOptionsDialog.vue`
- Modify: `frontend/src/pages/data/components/FileUploadArea.vue`
- Modify: `frontend/src/pages/data/components/FileListTab.vue`
- Modify: `frontend/src/pages/data/components/FileListToolbar.vue`
- Modify: `frontend/src/pages/data/components/FileListTable.vue`
- Modify: `frontend/src/pages/data/components/BatchFilesTable.vue`
- Modify: `frontend/src/pages/data/components/CombineBatchDialog.vue`
- Modify: `frontend/src/pages/data/composables/useTagEditing.ts`
- Test: `frontend/e2e/data/combination-data.spec.ts`

**Interfaces:**

- Consumes: Task 5 的 `UploadOptions/AssignCombinationInput/combinationsApi`。
- Produces:
  - 文件列表手动/系统标签分区展示
  - 工具栏组合筛选
  - 上传区组合、批次号、手动标签配置
  - 批量“加入组合”动作

- [ ] **Step 1: 写失败浏览器测试**

在 `combination-data.spec.ts` 增加：

```typescript
  test('单文件保留手动标签并显示只读组合标签', async ({ page }) => {
    await gotoApp(page, '/data')
    const name = `e2e_combo_tags_${Date.now()}`
    const comboId = await page.evaluate(async (comboName) => {
      const token = localStorage.getItem('access_token')
      const resp = await fetch('/api/v1/combinations/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ name: comboName }),
      })
      return (await resp.json()).id as number
    }, name)

    try {
      await page.locator('.tabs-nav .tab-btn').filter({ hasText: '组合数据' }).click()
      await page.getByTestId('combination-select').click()
      await page.locator('.dp-combination-select-popper .el-select-dropdown__item')
        .filter({ hasText: name }).click()
      await expect(page.getByTestId('combination-upload')).toBeVisible()
      await page.getByTestId('import-manual-tags').fill('manual')
      await page.getByTestId('import-manual-tags').press('Enter')
      await page.getByTestId('combination-upload').locator('input[type=file]')
        .setInputFiles({
          name: 'combo_single.csv',
          mimeType: 'text/csv',
          buffer: Buffer.from(
            '[GENERAL],\nTester_Type,CTA8290DPlus,\n[Data]\ncol1,col2\nu1,u2\nmin1,min2\nmax1,max2\n1,2\n',
          ),
        })

      await expect(page.getByTestId('combination-files')).toContainText('combo_single.csv')
      await expect(page.getByTestId('combination-files')).toContainText('manual')
      await expect(page.locator('[data-testid="managed-tag"]')).toHaveText(name)
      await expect(page.locator('[data-testid="managed-tag"] .el-tag__close')).toHaveCount(0)

      await page.getByTestId('combination-rename').click()
      await page.getByTestId('combination-name-input').fill(`${name}_lab`)
      await page.getByTestId('combination-save').click()
      await expect(page.locator('[data-testid="managed-tag"]')).toHaveText(`${name}_lab`)
    } finally {
      await deleteFilesByNameQuiet(page, 'combo_single.csv')
      await page.evaluate(async (id) => {
        const token = localStorage.getItem('access_token')
        await fetch(`/api/v1/combinations/${id}/`, {
          method: 'DELETE',
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        })
      }, comboId)
    }
  })
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npx playwright test e2e/data/combination-data.spec.ts --project=P2 --workers=1 --retries=0`

Expected: FAIL，组合页没有上传设置或系统标签。

- [ ] **Step 3: 实现标签单元**

`FileTagsCell.vue`：

```vue
<template>
  <div class="file-tags-cell">
    <el-tag
      v-for="tag in row.tags || []"
      :key="`manual-${tag}`"
      size="small"
      type="info"
      effect="light"
      class="file-tag"
      data-testid="manual-tag"
      @close="emit('remove-manual', row, tag)"
    >{{ tag }}</el-tag>
    <el-tag
      v-for="tag in row.managed_tags || []"
      :key="`managed-${tag}`"
      size="small"
      type="warning"
      effect="plain"
      class="file-tag"
      data-testid="managed-tag"
      title="由组合名/批次号自动维护"
    >
      <el-icon><Lock /></el-icon>{{ tag }}
    </el-tag>
  </div>
</template>

<script setup lang="ts">
import { Lock } from '@element-plus/icons-vue'
defineProps<{ row: any }>()
const emit = defineEmits<{
  'remove-manual': [row: any, tag: string]
}>()
</script>
```

`FileListTable.vue` 的标签列保留现有新增输入，把渲染部分替换为 `<FileTagsCell>`；展开详情同步展示 `managed_tags`。

`BatchFilesTable.vue` 在文件名列下增加紧凑标签行，手动标签普通样式，系统标签使用 `data-testid="managed-tag"`。

- [ ] **Step 4: 阻止手动标签覆盖系统标签**

`useTagEditing.ts` 的 `commitNewTag` 增加：

```typescript
    const managed = Array.isArray(row.managed_tags) ? row.managed_tags : []
    if (managed.some((x: string) => x.toLowerCase() === t.toLowerCase())) {
      ElMessage.warning('该标签由组合自动维护，不能作为手动标签重复添加')
      editingId.value = null
      newTagValue.value = ''
      return
    }
```

`removeTag` 只接收手动标签；`FileTagsCell` 不为系统标签渲染关闭按钮。

- [ ] **Step 5: 实现导入设置**

`ImportOptionsDialog.vue` 只用于“批量加入组合 / 存量归组”，表单包含：

- 组合 `el-select-v2`，选项来自 `combinationsApi.list()`；
- 批次号 `el-input`，`maxlength=40`；
- “清空批次号”复选框。

批量动作字段 testid：

```text
import-combination
import-batch-no
import-clear-batch-no
import-submit
```

批次号留空且未勾选“清空批次号”时，提交对象省略 `batchNo`，保留原值；勾选后提交空字符串。

`FileUploadArea.vue` 增加 props，并把 Vue import 扩展为 `computed, ref, watch`：

```typescript
const props = defineProps<{
  visible: boolean
  combinations?: DataCombination[]
  combinationId?: number | null
  lockCombination?: boolean
}>()
const selectedCombinationId = ref<number | null>(props.combinationId ?? null)
const batchNo = ref('')
const manualTags = ref<string[]>([])
const combinationOptions = computed(() => (props.combinations ?? []).map(
  combo => ({ value: combo.id, label: combo.name }),
))
watch(() => props.combinationId, value => {
  selectedCombinationId.value = value ?? null
})
```

上传区在拖拽区上方直接渲染内联设置，避免多文件逐条弹窗：

```vue
<el-select-v2
  v-model="selectedCombinationId"
  :options="combinationOptions"
  :disabled="lockCombination"
  data-testid="import-combination"
/>
<el-input
  v-model="batchNo"
  maxlength="40"
  data-testid="import-batch-no"
/>
<el-select-v2
  v-model="manualTags"
  multiple
  filterable
  allow-create
  default-first-option
  data-testid="import-manual-tags"
/>
```

`handleUpload` 直接读取当前内联设置并调用：

```typescript
datafilesApi.upload(options.file, (pct) => {
  uploadProgress.value = pct
}, {
  combinationId: selectedCombinationId.value,
  batchNo: batchNo.value,
  tags: manualTags.value,
})
```

组合页传入当前 `combinationId` 并 `lockCombination`，根节点加 `data-testid="combination-upload"`；文件列表上传不锁组合。多文件上传共用同一组内联设置，不引入逐文件对话框。

- [ ] **Step 6: 文件列表组合筛选与批量归组**

`FileListToolbar.vue` 增加 props `combinations: DataCombination[]`、`combinationId: number | null`，用 computed 生成 `{ value, label }` 选项，并新增 emit `combination-change: [value: number | null]`。模板增加组合下拉：

```vue
<el-select-v2
  :model-value="combinationId"
  :options="combinationOptions"
  clearable
  filterable
  placeholder="全部组合"
  data-testid="file-combination-filter"
  @update:model-value="emit('combination-change', $event)"
/>
```

`FileListTab.vue` 增加 `combinationsApi` 与 `DataCombination` import，并增加：

```typescript
const combinationFilter = ref<number | null>(null)
const combinations = ref<DataCombination[]>([])

function onCombinationFilterChange(value: number | null) {
  combinationFilter.value = value
  currentPage.value = 1
  tableRef.value?.clearSelection()
  loadFiles()
}

async function loadCombinations() {
  const { data } = await combinationsApi.list()
  combinations.value = Array.isArray(data) ? data : []
}
onActivated(loadCombinations)
```

`FileListTab.vue` 给 `FileListToolbar` 传入 `:combinations="combinations" :combination-id="combinationFilter"` 并监听 `@combination-change`；给 `FileUploadArea` 传入 `:combinations="combinations"`。`loadFiles` 参数增加：

```typescript
      combination_id: combinationFilter.value ?? undefined,
```

工具栏增加“加入组合”按钮，弹出 `ImportOptionsDialog`，提交调用：

```typescript
datafilesApi.assignCombination({
  fileIds: selectedIds.value,
  combinationId,
  batchNo,
})
```

成功后清空选择并刷新。

`CombineBatchDialog.vue` 增加可选组合与批次号，submit 事件改为 `[payload: { batchName: string; combinationId?: number | null; batchNo?: string }]`；`FileListTab.onCombineSubmit` 接收该 payload 并调用 `combineFiles([...selectedIds.value], payload.batchName, { combinationId: payload.combinationId, batchNo: payload.batchNo })`。

- [ ] **Step 7: 运行测试确认通过**

Run: `cd frontend && npx playwright test e2e/data/combination-data.spec.ts --project=P2 --workers=1 --retries=0`

Expected: PASS，2 条用例通过；检查系统标签无关闭按钮，手动标签仍可关闭。

- [ ] **Step 8: 条件提交**

```bash
git add frontend/src/pages/data/components/FileTagsCell.vue frontend/src/pages/data/components/ImportOptionsDialog.vue frontend/src/pages/data/components/FileUploadArea.vue frontend/src/pages/data/components/FileListTab.vue frontend/src/pages/data/components/FileListToolbar.vue frontend/src/pages/data/components/FileListTable.vue frontend/src/pages/data/components/BatchFilesTable.vue frontend/src/pages/data/components/CombineBatchDialog.vue frontend/src/pages/data/composables/useTagEditing.ts frontend/e2e/data/combination-data.spec.ts
git commit -m "feat(data): render managed tags and import options"
```

---

### Task 8: 文件下拉搜索与 Gage/Buyoff 组合上下文

**Files:**

- Modify: `frontend/src/components/common/fileSelectModel.ts`
- Modify: `frontend/test/unit/fileSelectModel.spec.ts`
- Create: `frontend/src/utils/reportFileScope.ts`
- Test: `frontend/test/unit/reportFileScope.spec.ts`
- Modify: `frontend/src/pages/data/DataManagement.vue`
- Modify: `frontend/src/pages/data/GageSummary.vue`
- Modify: `frontend/src/pages/data/BuyoffForm.vue`
- Test: `frontend/e2e/data/combination-data.spec.ts`

**Interfaces:**

- Produces:
  - `matchFile` 匹配 `combination_name/batch_no`
  - `metaText` 展示组合与批次号
  - `filterReportFiles(files, combinationId)`
  - Gage/Buyoff props `{ combinationId?: number | null; combinationName?: string | null }`

- [ ] **Step 1: 写失败纯函数测试**

更新 `fileSelectModel.spec.ts`：

```typescript
  it('matchFile 命中组合名和批次号', () => {
    const f = file(1, 'Alpha.csv', {
      combination_name: 'Gage Lab',
      batch_no: 'BE01-2608130015',
    })
    expect(matchFile(f, 'gage')).toBe(true)
    expect(matchFile(f, 'be01')).toBe(true)
  })
```

创建 `frontend/test/unit/reportFileScope.spec.ts`：

```typescript
import { describe, expect, it } from 'vitest'
import { filterReportFiles } from '../../src/utils/reportFileScope'

describe('filterReportFiles', () => {
  const files = [
    { id: 1, combination_id: 3 },
    { id: 2, combination_id: 4 },
    { id: 3, combination_id: null },
  ] as any

  it('按组合收敛候选', () => {
    expect(filterReportFiles(files, 3).map(f => f.id)).toEqual([1])
  })

  it('未指定组合时返回全部', () => {
    expect(filterReportFiles(files, null).map(f => f.id)).toEqual([1, 2, 3])
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npx vitest run test/unit/fileSelectModel.spec.ts test/unit/reportFileScope.spec.ts`

Expected: FAIL，组合字段未参与匹配，纯函数模块不存在。

- [ ] **Step 3: 实现下拉匹配与报表候选过滤**

`fileSelectModel.ts`：

```typescript
export function matchFile(
  f: Pick<DataFile, 'filename' | 'program_name' | 'batch_name' | 'combination_name' | 'batch_no'>,
  query: string,
): boolean {
  if (!query) return true
  return [
    f.filename,
    f.program_name,
    f.batch_name,
    f.combination_name,
    f.batch_no,
  ].some((value) => (value ?? '').toLowerCase().includes(query))
}
```

`metaText` 在现有数组中加入：

```typescript
    f.combination_name,
    f.batch_no,
```

创建 `frontend/src/utils/reportFileScope.ts`：

```typescript
import type { DataFile } from '../types'

export function filterReportFiles(
  files: DataFile[],
  combinationId: number | null | undefined,
): DataFile[] {
  if (combinationId == null) return files
  return files.filter(file => (file.combination_id ?? null) === combinationId)
}
```

- [ ] **Step 4: 接入组合页报表动作**

`CombinationDataTab.vue` 仅在 `activeCombination && visibleFiles.length` 时显示：

```vue
<el-button @click="emit('open-report', { kind: 'gage', combinationId: activeId, combinationName: activeCombination?.name ?? null, fileIds: visibleFiles.map(f => f.id) })">
  用当前组合打开 Gage 配置
</el-button>
<el-button @click="emit('open-report', { kind: 'buyoff', combinationId: activeId, combinationName: activeCombination?.name ?? null, fileIds: visibleFiles.map(f => f.id) })">
  用当前组合打开 Buyoff 配置
</el-button>
```

`DataManagement.vue` 沿用 Task 6 的 `ReportContext/reportContext`，补充 `combinationName` 和手动 Tab 清理逻辑：

把 Task 6 的 `ReportContext` 补全为：

```typescript
interface ReportContext {
  kind: 'gage' | 'buyoff'
  combinationId: number | null
  combinationName: string | null
  fileIds: number[]
}
```

组合页事件带 `combinationName`，其余处理函数：

```typescript
function onOpenCombinationReport(payload: ReportContext) {
  reportContext.value = payload
  activeTab.value = payload.kind
}

function selectTab(key: string) {
  reportContext.value = null
  activeTab.value = key
}
```

Tab 点击改为 `selectTab(tab.key)`；组合页主动跳转不经过 `selectTab`，因此保留上下文。Gage/Buyoff 绑定改为：

```vue
<GageSummary
  :files="selectableFiles"
  :combination-id="reportContext?.kind === 'gage' ? reportContext.combinationId : null"
  :combination-name="reportContext?.kind === 'gage' ? reportContext.combinationName : null"
/>
<BuyoffForm
  :files="selectableFiles"
  :combination-id="reportContext?.kind === 'buyoff' ? reportContext.combinationId : null"
  :combination-name="reportContext?.kind === 'buyoff' ? reportContext.combinationName : null"
/>
```

Gage/Buyoff 模板增加：

```vue
<el-alert
  v-if="combinationName"
  :title="`当前组合：${combinationName}；候选文件已收敛，Site 仍需手动分配`"
  type="info"
  :closable="false"
/>
```

两个组件 props 增加 `combinationId/combinationName`。Gage 提示“候选文件已收敛，Site 仍需手动分配”，Buyoff 提示“候选文件已收敛，角色仍需手动分配”。`availableFiles` 改为：

```typescript
function availableFiles() {
  return filterReportFiles(props.files, props.combinationId)
}
```

Buyoff 的 `availableFiles(currentRole)` 在 `filterReportFiles` 结果上继续应用原有角色互斥规则。不得自动写 `siteSlots` 或 `roleAssignments`。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd frontend && npx vitest run test/unit/fileSelectModel.spec.ts test/unit/reportFileScope.spec.ts`

Expected: PASS。

- [ ] **Step 6: 条件提交**

```bash
git add frontend/src/components/common/fileSelectModel.ts frontend/test/unit/fileSelectModel.spec.ts frontend/src/utils/reportFileScope.ts frontend/test/unit/reportFileScope.spec.ts frontend/src/pages/data/DataManagement.vue frontend/src/pages/data/GageSummary.vue frontend/src/pages/data/BuyoffForm.vue
git commit -m "feat(data): scope file pickers by combination"
```

---

### Task 9: 文档、存量归组入口与全量收口

**Files:**

- Modify: `frontend/e2e/data/zip-upload.spec.ts`
- Modify: `frontend/e2e/data/combination-data.spec.ts`
- Modify: `docs/intro/guide/04-data.md`
- Modify: `docs/intro/.vitepress/theme/data.ts`
- Modify: `docs/intro/guide/02-quickstart.md`
- Modify: `docs/intro/guide/10-faq.md`
- Modify: `frontend/src/pages/data/components/combination/CombinationDataTab.vue`

**Interfaces:**

- Consumes: Task 2 批量归组 API、Task 6 组合页、Task 7 标签展示。
- Produces: 存量归组向导、完整浏览器接线、更新后的介绍书与全量验证结论。

- [ ] **Step 1: 增加存量归组向导**

在 `CombinationDataTab.vue` 增加“存量归组”按钮，打开 `ImportOptionsDialog` 时加载未分组文件：

```typescript
const ungroupedFiles = computed(() => files.value.filter(
  file => file.combination_id == null,
))
```

提交时调用：

```typescript
await datafilesApi.assignCombination({
  fileIds: ungroupedFiles.value.map(file => file.id),
  combinationId,
  batchNo,
})
await loadAll()
filesStore.notifyFilesChanged()
```

界面显示将归组的文件数，并要求二次确认；不自动猜测批次号。

- [ ] **Step 2: 更新既有 ZIP E2E 的 Tab 文案**

把 `frontend/e2e/data/zip-upload.spec.ts` 中：

```typescript
const batchTab = page.locator('.tabs-nav .tab-btn').filter({ hasText: '批次数据' })
await expect(page.locator('.tab-btn.active')).toContainText('批次数据')
```

改为：

```typescript
const batchTab = page.locator('.tabs-nav .tab-btn').filter({ hasText: '组合数据' })
await expect(page.locator('.tab-btn.active')).toContainText('组合数据')
```

其余 `batch-header-*`、`batch-files-*` testid 保持不变，因为它们仍属于“来源批次目录”。

- [ ] **Step 3: 补组合导入浏览器接线**

在 `combination-data.spec.ts` 增加一条 ZIP 导入：

```typescript
  test('ZIP 导入到组合后显示组合与批次标签', async ({ page }) => {
    await gotoApp(page, '/data')
    const name = `e2e_combo_zip_${Date.now()}`
    const comboId = await page.evaluate(async (comboName) => {
      const token = localStorage.getItem('access_token')
      const resp = await fetch('/api/v1/combinations/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ name: comboName }),
      })
      return (await resp.json()).id as number
    }, name)

    await page.locator('.tabs-nav .tab-btn').filter({ hasText: '组合数据' }).click()
    await page.getByTestId('combination-select').click()
    await page.locator('.dp-combination-select-popper .el-select-dropdown__item')
      .filter({ hasText: name }).click()
    await expect(page.getByTestId('combination-upload')).toBeVisible()
    await page.getByTestId('import-batch-no').fill('BE01-2608130015')

    const zipPath = path.join(os.tmpdir(), `e2e_combo_${Date.now()}.zip`)
    makeZip(zipPath, [{
      name: 'root.csv',
      content: '[GENERAL],\nTester_Type,CTA8290DPlus,\n[Data]\ncol1,col2\nu1,u2\nmin1,min2\nmax1,max2\n1,2\n',
    }])
    try {
      await page.getByTestId('combination-upload').locator('input[type=file]').setInputFiles(zipPath)
      await expect(page.getByTestId('combination-files')).toContainText('root.csv')
      await expect(page.locator('[data-testid="managed-tag"]')).toContainText([
        name,
        `${name} / BE01-2608130015`,
      ])
    } finally {
      await deleteBatchQuiet(page, path.basename(zipPath, '.zip'))
      cleanupQuiet(zipPath)
      await page.evaluate(async (id) => {
        const token = localStorage.getItem('access_token')
        await fetch(`/api/v1/combinations/${id}/`, {
          method: 'DELETE',
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        })
      }, comboId)
    }
  })
```

- [ ] **Step 4: 更新介绍书**

`docs/intro/guide/04-data.md` 将“批次数据”章节改为“组合数据”，说明：

- 组合是实验室调试数据集；
- 批次号可选；
- 手动标签与系统标签共存；
- 组合改名系统标签同步；
- 来源批次目录仍管理 ZIP/SFTP 物理批次。

`docs/intro/.vitepress/theme/data.ts` 的 `batchData` 文案同步替换为组合数据语义。快速开始和 FAQ 补充：“ZIP 仍会解析为来源批次；是否带业务批次号取决于文件 LotID 或用户填写。”

- [ ] **Step 5: 运行后端全套**

Run: `.venv/Scripts/python.exe -X utf8 manage.py test test.backend apps.accounts apps.analysis apps.batch_report apps.buyoff apps.dashboard apps.datafiles apps.export apps.gage apps.jobs apps.sftp apps.weight -v 1`

Expected: PASS；任何失败先单文件复跑并对照基线，不得把存量红直接算作本批回归。

- [ ] **Step 6: 运行前端静态门禁**

Run:

```bash
cd frontend
npx vitest run
npm run lint:e2e
npm run build
```

Expected: vitest 全绿、lint:e2e 无错误、build 成功。

- [ ] **Step 7: 运行组合与存量批次定向回归**

分别执行，每条命令只跑一个 Playwright 档：

```bash
cd frontend
npx playwright test e2e/data/combination-data.spec.ts --project=P2 --workers=1 --retries=0
npx playwright test e2e/data/zip-upload.spec.ts --project=P2 --workers=1 --retries=0
npx playwright test e2e/data/file-list-sort-filter.spec.ts --project=P2 --workers=1 --retries=0
npx playwright test e2e/analysis/file-select.spec.ts --project=P1 --workers=1 --retries=0
```

Expected: 全部 PASS；上传用例必须同时清理 DataFile/批次/组合，不能只删临时 ZIP。

- [ ] **Step 8: 运行全量收口池**

Run: `node scripts/e2e_pool.mjs --slots=4`

Expected: 末行 `RESULT: PASS`，`verdict=MEASURED`；若为 `VOID (infra)` 必须重跑，不作为通过证据。

- [ ] **Step 9: 介绍书构建与走读**

Run:

```bash
cd frontend
npm run intro:build
node ../scripts/intro/check.mjs
```

Expected: `PASS`；浏览器走读数据管理章节，desktop 与 420px 各检查一次，console 零错误。

- [ ] **Step 10: 条件提交**

```bash
git add frontend/e2e/data/zip-upload.spec.ts frontend/e2e/data/combination-data.spec.ts docs/intro/guide/04-data.md docs/intro/.vitepress/theme/data.ts docs/intro/guide/02-quickstart.md docs/intro/guide/10-faq.md frontend/src/pages/data/components/combination/CombinationDataTab.vue
git commit -m "docs(data): document combination data and close regression gates"
```

---

## Final Acceptance Checklist

- [ ] `DataCombination` 迁移已应用，存量文件保持未分组。
- [ ] 组合 CRUD 与批量归组 API 通过 T1。
- [ ] 文件 API 返回 `combination_id/combination_name/batch_no/managed_tags`。
- [ ] 手动标签与系统标签共存，系统标签不可关闭。
- [ ] 组合改名后系统标签同步，文件行不被修改。
- [ ] 单文件、ZIP、目录、SFTP 导入均走统一归组逻辑。
- [ ] LotID 自动写入 `batch_no`，无 LotID 不伪造批次号。
- [ ] 重传不重复插入，组合与手动标签按规则幂等更新。
- [ ] 标签搜索不再绕过组合、文件类型和隐藏筛选。
- [ ] 分析下拉可按组合名和批次号搜索。
- [ ] Gage/Buyoff 只收敛候选，不自动分配 Site 或角色。
- [ ] 批次报表、物理批次目录和既有 ZIP 用例不回归。
- [ ] light/night 双主题走查通过。
- [ ] 后端全套、vitest、lint:e2e、build、4-slot 池和介绍书检查均通过。
- [ ] 未执行未授权的 push、合并或共享环境修改。
