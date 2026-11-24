from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
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
        if not isinstance(name, str) or not name.strip():
            return error_response('combination_name_required', '组合名必填')
        if isinstance(name, str) and DataCombination.objects.filter(
            owner=request.user, name_key=name.strip().casefold(),
        ).exists():
            return error_response('duplicate_combination', '组合名已存在')
        try:
            with transaction.atomic():
                return super().create(request, *args, **kwargs)
        except IntegrityError:
            return error_response('duplicate_combination', '组合名已存在')

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        name = request.data.get('name', instance.name)
        if not isinstance(name, str) or not name.strip():
            return error_response('combination_name_required', '组合名必填')
        if isinstance(name, str) and DataCombination.objects.filter(
            owner=request.user, name_key=name.strip().casefold(),
        ).exclude(pk=instance.pk).exists():
            return error_response('duplicate_combination', '组合名已存在')
        try:
            with transaction.atomic():
                return super().update(request, *args, **kwargs)
        except IntegrityError:
            return error_response('duplicate_combination', '组合名已存在')


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
            if (not isinstance(combination_id, int) or isinstance(combination_id, bool)
                    or combination_id <= 0):
                return error_response('validation_error', 'combination_id 必须是正整数')
            combination = get_object_or_404(
                DataCombination, pk=combination_id, owner=request.user)

        update_values = {}
        if 'batch_no' in request.data:
            try:
                update_values['batch_no'] = normalize_batch_no(request.data.get('batch_no'))
            except ValueError as exc:
                return error_response('validation_error', str(exc))

        try:
            with transaction.atomic():
                if combination is not None:
                    combination = DataCombination.objects.select_for_update().filter(
                        pk=combination_id, owner=request.user,
                    ).first()
                    if combination is None:
                        return error_response('combination_not_found', '组合不存在', 404)
                rows = list(DataFile.objects.select_for_update().filter(
                    owner=request.user, id__in=raw_ids,
                ))
                if len(rows) != len(set(raw_ids)):
                    return error_response(
                        'file_not_found_or_not_owned', '部分文件不存在或不属于当前用户', 404)
                updates = {'combination_id': combination.pk if combination else None,
                           'updated_at': timezone.now(),
                           **update_values}
                changed = DataFile.objects.filter(
                    owner=request.user, id__in=raw_ids,
                ).update(**updates)
                if changed != len(raw_ids):
                    transaction.set_rollback(True)
                    return error_response(
                        'file_not_found_or_not_owned', '部分文件不存在或不属于当前用户', 404)
                rows = list(DataFile.objects.filter(
                    owner=request.user, id__in=raw_ids,
                ).order_by('id'))
        except IntegrityError:
            return error_response('combination_not_found', '组合不存在', 404)

        return Response(DataFileSerializer(rows, many=True).data)
