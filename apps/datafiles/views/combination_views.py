from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from apps.common.errors import error_response
from apps.datafiles.combination_service import normalize_batch_no
from apps.datafiles.models import DataCombination, DataFile
from apps.datafiles.serializers import DataCombinationSerializer, DataFileSerializer


class DataCombinationViewSet(ModelViewSet):
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
            try:
                batch_no = normalize_batch_no(request.data.get('batch_no'))
            except ValueError as exc:
                return error_response('validation_error', str(exc))
            update_fields.append('batch_no')
        else:
            batch_no = None

        with transaction.atomic():
            for row in rows:
                row.combination = combination
                if batch_no is not None:
                    row.batch_no = batch_no
                row.save(update_fields=update_fields)

        return Response(DataFileSerializer(rows, many=True).data)
