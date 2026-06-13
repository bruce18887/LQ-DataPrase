"""File CRUD and upload views."""

import os
import time

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.datafiles.models import DataFile
from apps.datafiles.serializers import (
    DataFileListSerializer,
    DataFileSerializer,
    normalize_tags,
)
from apps.datafiles.services import clear_parse_cache

from ._helpers import (
    _is_archive,
    _extract_archive,
    _register_file,
    _user_upload_dir,
    _disk_mtime,
    _parse_last_modified,
    _delete_datafile_on_disk,
)


class DataFileViewSet(viewsets.ModelViewSet):
    serializer_class = DataFileSerializer
    permission_classes = [IsAuthenticated]
    search_fields = ['filename', 'batch_name', 'program_name']
    filterset_fields = ['product_code', 'format_type', 'file_type']
    ordering_fields = ['created_at', 'source_mtime', 'filename', 'file_size']

    def get_queryset(self):
        queryset = DataFile.objects.filter(owner=self.request.user)

        # Custom search for tags (JSONField)
        search = self.request.query_params.get('search', '').strip()
        if search:
            # Search in filename, program_name, and tags
            from django.db.models import Q
            q = Q(filename__icontains=search) | Q(program_name__icontains=search)
            # For tags, we need to search within the JSON array
            # SQLite doesn't support JSON array search natively, so we'll filter in Python
            # For PostgreSQL, we could use __contains with a JSONB array
            # For now, we'll do a simple approach: filter by filename/program_name first,
            # then filter tags in Python if needed
            queryset = queryset.filter(q)

        # Filter by specific tag
        tag = self.request.query_params.get('tag', '').strip()
        if tag:
            # Filter files that have this specific tag (case-insensitive)
            # Since tags is a JSONField with a list, we need to check if the tag exists in the list
            # This is database-specific; for SQLite we'll filter in Python
            # For PostgreSQL, we could use __contains
            tag_lower = tag.lower()
            matching_ids = []
            for df in queryset.values('id', 'tags'):
                tags = df.get('tags') or []
                if any(t.lower() == tag_lower for t in tags if isinstance(t, str)):
                    matching_ids.append(df['id'])
            queryset = queryset.filter(id__in=matching_ids)

        return queryset

    def get_serializer_class(self):
        if self.action == 'list':
            return DataFileListSerializer
        return DataFileSerializer

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def destroy(self, request, *args, **kwargs):
        datafile = self.get_object()
        _delete_datafile_on_disk(datafile)
        datafile.delete()
        clear_parse_cache()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['post'])
    def bulk_delete(self, request):
        """Delete multiple owned files at once: { "ids": [1, 2, 3] }."""
        ids = request.data.get('ids') or []
        if not isinstance(ids, list) or not ids:
            return Response(
                {'error': 'ids must be a non-empty list'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Owner-scoped: only the requesting user's files are ever touched.
        qs = DataFile.objects.filter(owner=request.user, id__in=ids)
        for datafile in qs:
            _delete_datafile_on_disk(datafile)
        deleted_count = qs.count()
        qs.delete()
        clear_parse_cache()
        return Response({'deleted': deleted_count})

    @action(detail=False, methods=['get'])
    def product_codes(self, request):
        """Distinct non-empty product codes for the current user's files."""
        codes = (
            DataFile.objects.filter(owner=request.user)
            .exclude(product_code='')
            .values_list('product_code', flat=True)
            .distinct()
            .order_by('product_code')
        )
        return Response({'product_codes': list(codes)})

    @action(detail=True, methods=['post'])
    def set_tags(self, request, pk=None):
        """Overwrite the file's tag list. Body: ``{"tags": ["a", "b"]}``.

        Owner-scoped: a 404 is returned if the file is not owned by the
        requesting user. Validation (length / count / type) is delegated to
        ``normalize_tags``; on success the response echoes the saved tags.
        """
        datafile = self.get_object()
        try:
            tags = normalize_tags(request.data.get('tags') or [])
        except Exception as e:
            return Response(
                {'tags': [str(e)]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        datafile.tags = tags
        datafile.save(update_fields=['tags', 'updated_at'])
        return Response({'id': datafile.id, 'tags': datafile.tags})

    @action(detail=False, methods=['post'])
    def list_tags(self, request):
        """Return distinct, de-dup'd tags the current user has ever used.

        Body (optional): ``{"prefix": "PR"}`` — case-insensitive prefix filter
        used by the front-end autocomplete. Tags from every file the user
        owns are aggregated and returned in lexicographic order.
        """
        prefix = (request.data.get('prefix') or '').strip()
        seen = {}
        # Iterate over each file's tag list and collect distinct (case-insensitive)
        # entries, preferring the first-seen casing as the canonical form.
        for tag_list in (
            DataFile.objects.filter(owner=request.user)
            .exclude(tags=[])
            .values_list('tags', flat=True)
        ):
            if not isinstance(tag_list, list):
                continue
            for t in tag_list:
                if not isinstance(t, str):
                    continue
                t = t.strip()
                if not t:
                    continue
                key = t.lower()
                if key in seen:
                    continue
                if prefix and not key.startswith(prefix.lower()):
                    continue
                seen[key] = t
        return Response({'tags': sorted(seen.values(), key=str.lower)})


class FileUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        # Support both single 'file' and multiple 'files' keys
        files = request.FILES.getlist('files') or request.FILES.getlist('file')
        if not files:
            return Response({'error': '未选择文件'}, status=400)

        # Optional per-file last_modified (epoch ms), parallel to the files list.
        last_modified_list = request.data.getlist('last_modified')

        upload_dir = _user_upload_dir(request.user, 'single')
        created = []

        for idx, uploaded_file in enumerate(files):
            base_name = uploaded_file.name
            file_path = os.path.join(upload_dir, base_name)

            lm_value = last_modified_list[idx] if idx < len(last_modified_list) else None
            browser_mtime = _parse_last_modified(lm_value)

            # Handle filename collision
            if os.path.exists(file_path):
                ts = int(time.time())
                name, ext = os.path.splitext(base_name)
                file_path = os.path.join(upload_dir, f"{name}_{ts}{ext}")

            # Save uploaded file
            with open(file_path, 'wb+') as dest:
                for chunk in uploaded_file.chunks():
                    dest.write(chunk)

            # If archive, extract and register each extracted file
            if _is_archive(base_name):
                extract_dir = file_path + '_extracted'
                os.makedirs(extract_dir, exist_ok=True)
                try:
                    extracted = _extract_archive(file_path, extract_dir)
                    batch_name = os.path.splitext(base_name)[0]
                    for ext_path in extracted:
                        # Archives preserve the original file mtime on disk.
                        df = _register_file(
                            request.user, ext_path, 'batch', batch_name,
                            source_mtime=_disk_mtime(ext_path),
                        )
                        created.append(df)
                except Exception:
                    pass
                # Remove the archive itself (keep extracted files)
                os.remove(file_path)
            else:
                df = _register_file(
                    request.user, file_path, 'single',
                    source_mtime=browser_mtime,
                )
                created.append(df)

        return Response(
            DataFileSerializer(created, many=True).data,
            status=status.HTTP_201_CREATED,
        )
