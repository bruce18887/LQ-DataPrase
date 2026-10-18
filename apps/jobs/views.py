"""`/api/v1/jobs/` —— 提交、轮询、下载、取消。

三条硬口径：

* **提交只拿号**：202 + `job_id`，请求线程不碰计算（这是本片存在的唯一理由）。
* **越权一律 404**，不是 403 —— 作业 id 是自增的，403 等于告诉别人「这个 id 真的存在」。
* **进程池建不起来时降级成今天的同步导出**（200 + 文件流 + `X-Job-Fallback: 1`），
  而不是 500、也不是排队等一个永远不会有 worker 来领的作业。
"""

import os

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.errors import error_response
from apps.common.export_naming import base_export_context, render_export_filename
from apps.datafiles.models import DataFile
from apps.datafiles.utils import resolve_file_path
from apps.jobs import executor
from apps.jobs.models import Job

LIST_LIMIT = 50

# kind → (export_naming 的类型键, 扩展名)。文件名的模板与占位符全走
# `apps/common/export_naming.py` 那一套（用户可在系统设置里改模板），这里只给键。
KIND_EXPORT_TYPE = {
    'export_excel': ('to_excel', 'xlsx'),
    'export_batch_charts': ('batch_charts', 'xlsx'),
    'export_html_report': ('html_report', 'html'),
}


def _job_payload(job: Job) -> dict:
    return {
        'id': job.id,
        'kind': job.kind,
        'status': job.status,
        'progress': job.progress,
        'error': job.error,
        'result_name': job.result_name,
        'created_at': job.created_at.isoformat() if job.created_at else None,
    }


def _flatten_prefs(user, params, datafile, kind) -> dict:
    """把只有主进程才读得到的东西压成纯标量：文件名、DPI、CPK 阈值、隐藏列、时间戳。

    worker 禁 Django ⇒ 拿不到 `request.user.settings`。这些值必须在**提交那一刻**定死：
    用户排队期间改了 DPI 或阈值，作业不该据此出一份他没要求的产物
    （这也是 `params` 存快照而不是引用的同一个理由）。
    """
    from apps.common.user_settings import get_cpk_thresholds
    from apps.export.user_prefs import get_export_dpi
    from django.utils import timezone

    export_type, ext = KIND_EXPORT_TYPE[kind]
    # pptx 是 batch_charts 的一种 format：产物扩展名跟着走
    if kind == 'export_batch_charts' and str(params.get('format', 'xlsx')) == 'pptx':
        ext = 'pptx'
    settings_obj = getattr(user, 'settings', None)

    prefs = {
        'result_name': render_export_filename(
            user, export_type, ext,
            {**base_export_context(user),
             'filename': datafile.filename.rsplit('.', 1)[0]}),
        'hidden_columns': list(settings_obj.default_hidden_columns or [])
        if settings_obj else [],
    }
    if kind in ('export_batch_charts', 'export_html_report'):
        prefs['dpi'] = get_export_dpi(user)
        prefs['cpk_thresholds'] = tuple(get_cpk_thresholds(user))
    if kind == 'export_html_report':
        # 报告上的时间戳钉在提交那一刻，不随队列长度漂移
        prefs['generated_at'] = timezone.localtime(timezone.now()).strftime(
            '%Y-%m-%d %H:%M:%S')
    return prefs


def _build_task(kind, *, params, abs_path, fmt, job_id, owner_id, datafile, prefs):
    """按类型拼 task。只吃 `params` + `prefs`，不碰 request。"""
    if kind == 'export_excel':
        return executor.build_export_excel_task(
            params={**params, 'result_name': prefs['result_name']},
            abs_path=abs_path, fmt=fmt, hidden_columns=prefs['hidden_columns'],
            job_id=job_id, owner_id=owner_id)
    if kind == 'export_batch_charts':
        return executor.build_batch_charts_task(
            params={**params, 'result_name': prefs['result_name']},
            abs_path=abs_path, fmt=fmt,
            job_id=job_id, owner_id=owner_id,
            dpi=prefs['dpi'], cpk_thresholds=prefs['cpk_thresholds'],
            chart_format='pptx' if str(params.get('format', 'xlsx')) == 'pptx' else 'xlsx')
    return executor.build_html_report_task(
        params={**params, 'result_name': prefs['result_name']},
        abs_path=abs_path, fmt=fmt, job_id=job_id, owner_id=owner_id,
        dpi=prefs['dpi'], cpk_thresholds=prefs['cpk_thresholds'],
        datafile=datafile, generated_at=prefs['generated_at'])


class JobSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, kind):
        if kind not in executor.KIND_RUNNERS:
            return error_response('unsupported_kind',
                                  f'{kind} 还不是可提交的作业类型', 400)

        datafile = get_object_or_404(DataFile, pk=request.data.get('file_id'),
                                     owner=request.user)
        abs_path = resolve_file_path(datafile.file_path)
        if not os.path.exists(abs_path):
            return error_response('file_not_found', '源文件已不在磁盘上', 404)

        # params 存**用户的请求参数**本身；文件名/DPI/阈值等主进程偏好走 prefs，
        # 不进快照 —— 否则 GET /jobs/ 会把内部钳位值当作用户意图回显出去。
        params = {k: v for k, v in request.data.items() if k != 'result_name'}
        prefs = _flatten_prefs(request.user, params, datafile, kind)
        job = Job.objects.create(owner=request.user, kind=kind,
                                 status='pending', params=params)
        task = _build_task(kind, params=params, abs_path=abs_path,
                           fmt=datafile.format_type, job_id=job.id,
                           owner_id=request.user.pk, datafile=datafile, prefs=prefs)

        if not executor.executor_available():
            return self._sync_fallback(job, task)

        executor.submit(job, task)
        job.refresh_from_db()
        return Response({'job_id': job.id, 'status': job.status},
                        status=http_status.HTTP_202_ACCEPTED)

    def _sync_fallback(self, job: Job, task: dict):
        entry, _timeout = executor.KIND_RUNNERS[job.kind]
        try:
            result = entry(task)
        except Exception as exc:
            job.status, job.error, job.finished_at = 'error', str(exc), timezone.now()
            job.save(update_fields=['status', 'error', 'finished_at'])
            return error_response('export_failed', f'导出失败：{exc}', 500)
        job.status, job.progress = 'done', 100
        job.result_path = executor._relativize(result['out_path'])
        job.result_name = os.path.basename(result['out_path'])
        job.started_at = job.finished_at = timezone.now()
        job.save(update_fields=['status', 'progress', 'result_path',
                                'result_name', 'started_at', 'finished_at'])
        response = FileResponse(open(result['out_path'], 'rb'),
                                filename=job.result_name, as_attachment=True)
        response['X-Job-Fallback'] = '1'
        return response


class JobDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        job = get_object_or_404(Job, pk=pk, owner=request.user)
        return Response(_job_payload(job))


class JobDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        job = get_object_or_404(Job, pk=pk, owner=request.user)
        if job.status != 'done' or not job.result_path:
            return error_response('job_not_ready', '作业还没产出结果', 404)
        abs_path = resolve_file_path(job.result_path)
        if not os.path.exists(abs_path):
            return error_response('result_missing', '结果文件已不在磁盘上', 404)
        return FileResponse(open(abs_path, 'rb'), filename=job.result_name,
                            as_attachment=True)


class JobCancelView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        job = get_object_or_404(Job, pk=pk, owner=request.user)
        if job.status != 'pending':
            # running 的作业已经在别的进程里算，杀掉它只会留下一半个文件
            return error_response('not_cancellable',
                                  f'{job.status} 的作业不能取消', 409)
        job.status, job.finished_at = 'cancelled', timezone.now()
        job.save(update_fields=['status', 'finished_at'])
        return Response(_job_payload(job))


class JobListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = Job.objects.filter(owner=request.user)[:LIST_LIMIT]
        return Response({'results': [_job_payload(job) for job in rows]})
