"""Shared validation for combination metadata on import/move endpoints."""

import json

from rest_framework import serializers

from apps.common.errors import error_response
from apps.datafiles.combination_service import normalize_batch_no
from apps.datafiles.models import DataCombination
from apps.datafiles.serializers import normalize_tags


def resolve_owned_combination(request, raw_id, required=False):
    """Resolve an optional owner-scoped combination, returning an HTTP error."""
    missing = raw_id is None or (isinstance(raw_id, str) and not raw_id.strip())
    if missing:
        if required:
            return None, error_response('combination_id_required', 'combination_id 必填')
        return None, None
    if isinstance(raw_id, bool) or not isinstance(raw_id, (str, int)):
        return None, error_response('validation_error', 'combination_id 必须是整数')
    try:
        combination_id = int(raw_id)
    except (TypeError, ValueError):
        return None, error_response('validation_error', 'combination_id 必须是整数')
    if combination_id <= 0:
        return None, error_response('validation_error', 'combination_id 必须是正整数')
    try:
        combination = DataCombination.objects.get(
            pk=combination_id, owner=request.user,
        )
    except DataCombination.DoesNotExist:
        return None, error_response('combination_not_found', '组合不存在', 404)
    return combination, None


def parse_import_options(request):
    """Return ``(combination, batch_no, manual_tags, error_response)``."""
    combination, error = resolve_owned_combination(
        request, request.data.get('combination_id'),
    )
    if error is not None:
        return None, None, None, error

    raw_tags = request.data.get('tags')
    if raw_tags is None or raw_tags == '':
        manual_tags = []
    else:
        if isinstance(raw_tags, str):
            try:
                raw_tags = json.loads(raw_tags)
            except (TypeError, ValueError):
                return None, None, None, error_response(
                    'validation_error', 'tags 必须是 JSON 数组')
        try:
            manual_tags = normalize_tags(raw_tags)
        except serializers.ValidationError:
            return None, None, None, error_response(
                'validation_error', 'tags 必须是 JSON 数组')

    try:
        batch_no = normalize_batch_no(request.data.get('batch_no'))
    except ValueError as exc:
        return None, None, None, error_response('validation_error', str(exc))
    return combination, batch_no, manual_tags, None


def parse_combine_options(request):
    """Return only explicitly supplied combination fields for physical combine."""
    combination, error = resolve_owned_combination(
        request, request.data.get('combination_id'),
    )
    if error is not None:
        return None, error
    updates = {}
    if combination is not None:
        updates['combination'] = combination
    if 'batch_no' in request.data:
        try:
            updates['batch_no'] = normalize_batch_no(request.data.get('batch_no'))
        except ValueError as exc:
            return None, error_response('validation_error', str(exc))
    return updates, None
