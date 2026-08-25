import os, time, logging, json
import paramiko
from stat import S_ISDIR
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.http import StreamingHttpResponse
from apps.datafiles.views import _register_file, _is_summary_csv
logger = logging.getLogger(__name__)

from apps.datafiles.views import _user_upload_dir
from apps.accounts.models import UserSetting
from .cache import set_session, delete_session, SftpSessionCacheError
from .config_views import SftpConfigMixin
from .models import SftpConfig
from . import pool

CSV_EXTENSIONS = {'.csv'}


def _is_csv(filename):
    return os.path.splitext(filename)[1].lower() in CSV_EXTENSIONS

SORT_KEYS = {
    'name': lambda x: x['name'].lower(),
    'mtime': lambda x: x.get('mtime', 0) or 0,
    'size': lambda x: x.get('size', 0) or 0,
    'type': lambda x: os.path.splitext(x['name'])[1].lower(),
}


class SftpViewSet(SftpConfigMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    def _get_connection(self, request):
        """Return a pooled, live SFTPClient for the user, or None.

        Connection lifecycle is owned by ``apps.sftp.pool`` — callers must NOT
        close the returned client. On operation failure, call
        ``pool.invalidate(request.user.id)`` so the bad connection is rebuilt.
        """
        try:
            return pool.get_connection(request.user.id)
        except pool.SftpPoolError:
            return None

    # ------------------------------------------------------------------
    # Connect / Disconnect
    # ------------------------------------------------------------------

    def _record_last_visit(self, user, *, path=None, config_name=None, host=None, port=None, username=None):
        """Persist last SFTP visit metadata for 断线续连 (per-user).

        只更新传入的字段（update_fields），避免无谓写库。调用方必须 try/except
        静默包裹——记录失败（如路径超长）绝不能影响浏览/连接主流程。
        """
        setting, _ = UserSetting.objects.get_or_create(user=user)
        updates = []
        if path is not None:
            setting.sftp_last_path = path
            updates.append('sftp_last_path')
        if config_name is not None:
            setting.sftp_last_config = config_name
            updates.append('sftp_last_config')
        if host is not None:
            setting.sftp_last_host = host
            updates.append('sftp_last_host')
        if port is not None:
            setting.sftp_last_port = port
            updates.append('sftp_last_port')
        if username is not None:
            setting.sftp_last_username = username
            updates.append('sftp_last_username')
        if updates:
            setting.save(update_fields=updates)

    def _connect_impl(self, request, *, host, port, username, password, config_name=''):
        """Shared connect logic: handshake → persist session → record last visit."""
        try:
            transport = paramiko.Transport((host, port))
            transport.connect(username=username, password=password)
            transport.close()
        except Exception as e:
            return Response({'status': 'error', 'message': str(e)}, status=400)

        # Persist the session (password encrypted at rest) in Redis or
        # Django's default cache as fallback.  If *both* fail, report an
        # error so the user knows subsequent requests won't work.
        try:
            set_session(request.user.id, host, port, username, password)
        except SftpSessionCacheError as e:
            logger.error('Connect succeeded but session cache write failed: %s', e)
            return Response(
                {'status': 'error', 'message': '连接成功但会话缓存写入失败，请检查服务配置'},
                status=500,
            )

        # Record last-connect metadata for 断线续连 (failure must not block).
        try:
            self._record_last_visit(
                request.user,
                config_name=config_name,
                host=host,
                port=port,
                username=username,
            )
        except Exception as e:
            logger.warning('Failed to record last SFTP visit: %s', e)
        return Response({'status': 'connected', 'host': host})

    @action(detail=False, methods=['post'])
    def connect(self, request):
        # When a saved config is referenced, load host/port/username and the
        # decrypted password SERVER-SIDE so the stored password never travels
        # to the browser. Direct host/username/password connect still works.
        config_id = request.data.get('config_id')
        config_name = request.data.get('config_name')

        if config_id is not None or config_name:
            cfg_qs = SftpConfig.objects.filter(owner=request.user)
            if config_id is not None:
                cfg_qs = cfg_qs.filter(id=config_id)
            else:
                cfg_qs = cfg_qs.filter(name=config_name)
            cfg = cfg_qs.first()
            if not cfg:
                return Response({'status': 'error', 'message': '未找到配置'}, status=400)
            return self._connect_impl(
                request,
                host=cfg.host, port=cfg.port,
                username=cfg.username, password=cfg.get_password(),
                config_name=cfg.name,
            )

        return self._connect_impl(
            request,
            host=request.data.get('host'),
            port=int(request.data.get('port', 22)),
            username=request.data.get('username'),
            password=request.data.get('password'),
            # 手动连接：清空上次的 config_name，下次走「预填表单」分支
            config_name='',
        )

    @action(detail=False, methods=['post'])
    def auto_connect(self, request):
        """POST /sftp/auto_connect/ — 用上次保存的配置自动重连（密码服务端解密，不回传）。

        Body 可选 ``{config_name}`` 覆盖存储的记录；缺省用上次记录。
        无记录 / 配置被删 / 缺少密码 → 400，前端降级为手动预填。
        """
        setting, _ = UserSetting.objects.get_or_create(user=request.user)
        config_name = request.data.get('config_name') or setting.sftp_last_config
        if not config_name:
            return Response({'status': 'error', 'message': '上次连接未保存配置，无法自动重连'}, status=400)
        cfg = SftpConfig.objects.filter(owner=request.user, name=config_name).first()
        if not cfg or not cfg.password_encrypted:
            return Response({'status': 'error', 'message': '上次使用的配置已不存在或缺少密码，请手动连接'}, status=400)
        return self._connect_impl(
            request,
            host=cfg.host, port=cfg.port,
            username=cfg.username, password=cfg.get_password(),
            config_name=cfg.name,
        )

    @action(detail=False, methods=['get'])
    def last_visit(self, request):
        """GET /sftp/last_visit/ — 断线续连信息（无记录也 200，返回默认值）。

        ``can_auto_connect`` 需要同时满足：上次用保存配置连接 + 配置仍存在 + 有加密密码。
        host/port/username 始终返回（供手动预填）；密码永不回传。
        """
        setting, _ = UserSetting.objects.get_or_create(user=request.user)
        cfg = None
        if setting.sftp_last_config:
            cfg = SftpConfig.objects.filter(owner=request.user, name=setting.sftp_last_config).first()
        return Response({
            'can_auto_connect': bool(cfg and cfg.password_encrypted),
            'config_name': setting.sftp_last_config,
            'host': setting.sftp_last_host,
            'port': setting.sftp_last_port,
            'username': setting.sftp_last_username,
            'last_path': setting.sftp_last_path,
        })

    @action(detail=False, methods=['post'])
    def disconnect(self, request):
        delete_session(request.user.id)
        pool.close(request.user.id)
        return Response({'status': 'disconnected'})

    @action(detail=False, methods=['post'])
    def disconnect(self, request):
        delete_session(request.user.id)
        pool.close(request.user.id)
        return Response({'status': 'disconnected'})

    # ------------------------------------------------------------------
    # List files (with sorting)
    # ------------------------------------------------------------------

    @action(detail=False, methods=['get'])
    def list_files(self, request):
        path = request.query_params.get('path', '/')
        sort_by = request.query_params.get('sort_by', 'name')
        sort_order = request.query_params.get('sort_order', 'asc')

        sftp = self._get_connection(request)
        if not sftp:
            return Response({'error': 'not_connected'}, status=400)

        try:
            items = []
            for entry in sftp.listdir_attr(path):
                is_dir = S_ISDIR(entry.st_mode)
                items.append({
                    'name': entry.filename,
                    'is_dir': is_dir,
                    'size': entry.st_size if not is_dir else 0,
                    'mtime': entry.st_mtime,
                })

            # Sort: directories first (except when sorting by time, which is pure chronological)
            key_fn = SORT_KEYS.get(sort_by, SORT_KEYS['name'])
            reverse = sort_order == 'desc'
            if sort_by == 'mtime':
                items.sort(key=key_fn, reverse=reverse)
            else:
                items.sort(key=lambda x: (not x['is_dir'], key_fn(x)), reverse=reverse)

            # 断线续连：每次成功浏览都更新上次路径（即使不点断开、直接刷新也记录）。
            # 记录失败绝不影响浏览。
            try:
                self._record_last_visit(request.user, path=path)
            except Exception:
                pass

            return Response({'path': path, 'items': items})
        except Exception as e:
            pool.invalidate(request.user.id)
            return Response({'error': str(e)}, status=400)

    # ------------------------------------------------------------------
    # Download single file → save to media
    # ------------------------------------------------------------------

    @action(detail=False, methods=['post'])
    def download(self, request):
        remote_path = request.data.get('path')
        if not _is_csv(remote_path):
            return Response({'error': '仅支持 CSV 文件'}, status=400)

        sftp = self._get_connection(request)
        if not sftp:
            return Response({'error': 'not_connected'}, status=400)

        try:
            filename = os.path.basename(remote_path)
            upload_dir = _user_upload_dir(request.user, 'single')
            file_path = os.path.join(upload_dir, filename)
            if os.path.exists(file_path):
                ts = int(time.time())
                name, ext = os.path.splitext(filename)
                file_path = os.path.join(upload_dir, f"{name}_{ts}{ext}")

            sftp.get(remote_path, file_path)
            file_size = os.path.getsize(file_path)
            # 下载到应用数据区即注册：数据管理列表可见，避免修复中心误报孤儿
            datafile = _register_file(request.user, file_path, 'single')
            return Response({
                'status': 'ok',
                'filename': os.path.basename(file_path),
                'size': file_size,
                'path': file_path,
                'datafile_id': datafile.id,
            })
        except Exception as e:
            pool.invalidate(request.user.id)
            return Response({'error': str(e)}, status=400)

    # ------------------------------------------------------------------
    # Download directory → save individual files to media (SSE progress)
    # ------------------------------------------------------------------

    @action(detail=False, methods=['post'])
    def download_dir(self, request):
        remote_path = request.data.get('path')

        sftp = self._get_connection(request)
        if not sftp:
            return Response({'error': 'not_connected'}, status=400)

        # Collect CSV files only
        file_list = []
        self._collect_files(sftp, remote_path, file_list, '', True)

        if not file_list:
            return Response({'error': '目录为空'}, status=400)

        dir_name = os.path.basename(remote_path.rstrip('/')) or 'download'
        upload_dir = _user_upload_dir(request.user, 'batch')
        local_dir = os.path.join(upload_dir, dir_name)
        os.makedirs(local_dir, exist_ok=True)

        total_bytes = sum(size for _, _, size, _ in file_list)
        total_files = len(file_list)

        def sse_generator():
            bytes_done = 0
            success_count = 0
            start_time = time.time()
            try:
                for i, (remote_fp, rel_path, size, _mtime) in enumerate(file_list):
                    # rel_path uses '/' separators (built in _collect_files);
                    # normalize to the OS separator so the stored DataFile
                    # path matches os.walk output later (registered detection
                    # in BatchDirListView relies on consistent separators).
                    rel_path_os = rel_path.replace('/', os.sep)
                    local_file_path = os.path.join(local_dir, rel_path_os)
                    os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
                    try:
                        sftp.get(remote_fp, local_file_path)
                        bytes_done += size
                        success_count += 1
                        # Auto-register into database
                        try:
                            _register_file(request.user, local_file_path, 'batch', dir_name)
                        except Exception as re:
                            logger.warning(f"Auto-register failed for {local_file_path}: {re}")
                        elapsed = time.time() - start_time
                        speed = bytes_done / elapsed if elapsed > 0 else 0
                        eta = (total_bytes - bytes_done) / speed if speed > 0 else 0
                        yield f"data: {json.dumps({'event': 'progress', 'current': i + 1, 'total': total_files, 'filename': os.path.basename(rel_path), 'rel_path': rel_path, 'percent': round(bytes_done * 100 / total_bytes) if total_bytes else 100, 'speed': round(speed / 1048576, 2), 'eta': round(eta)})}\n\n"
                    except Exception as e:
                        logger.warning(f"SFTP download failed for {remote_fp}: {e}")
                        yield f"data: {json.dumps({'event': 'error', 'filename': os.path.basename(rel_path), 'message': str(e)})}\n\n"
            except GeneratorExit:
                # Client disconnected mid-stream: connection state is unreliable.
                pool.invalidate(request.user.id)
                raise
            except Exception:
                pool.invalidate(request.user.id)
                raise

            yield f"data: {json.dumps({'event': 'done', 'dir_name': dir_name, 'file_count': success_count, 'total': total_files, 'saved_dir': local_dir})}\n\n"

        response = StreamingHttpResponse(sse_generator(), content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response

    # ------------------------------------------------------------------
    # Batch download (multiple files) → save to media
    # ------------------------------------------------------------------

    @action(detail=False, methods=['post'])
    def download_batch(self, request):
        paths = request.data.get('paths', [])
        if not paths:
            return Response({'error': '未选择文件'}, status=400)

        # Filter to CSV only
        paths = [p for p in paths if _is_csv(p)]
        if not paths:
            return Response({'error': '未选择文件'}, status=400)

        sftp = self._get_connection(request)
        if not sftp:
            return Response({'error': 'not_connected'}, status=400)

        try:
            upload_dir = _user_upload_dir(request.user, 'single')
            saved = []
            for remote_path in paths:
                try:
                    filename = os.path.basename(remote_path)
                    file_path = os.path.join(upload_dir, filename)
                    if os.path.exists(file_path):
                        ts = int(time.time())
                        name, ext = os.path.splitext(filename)
                        file_path = os.path.join(upload_dir, f"{name}_{ts}{ext}")
                    sftp.get(remote_path, file_path)
                    # 与单文件下载同语义：下载即注册（single）
                    _register_file(request.user, file_path, 'single')
                    saved.append({
                        'filename': os.path.basename(file_path),
                        'size': os.path.getsize(file_path),
                    })
                except Exception as e:
                    logger.warning(f"SFTP batch download failed for {remote_path}: {e}")

            return Response({
                'status': 'ok',
                'files': saved,
                'count': len(saved),
            })
        except Exception as e:
            pool.invalidate(request.user.id)
            return Response({'error': str(e)}, status=400)

    # ------------------------------------------------------------------
    # Download and parse (server-side, saves to user's batch dir)
    # ------------------------------------------------------------------

    @action(detail=False, methods=['post'])
    def download_and_parse(self, request):
        """Download file(s) from SFTP, save to user's batch dir, create DataFile records."""
        remote_path = request.data.get('path')
        paths = request.data.get('paths', [])

        if paths:
            paths = [p for p in paths if _is_csv(p)]
            if not paths:
                return Response({'error': '无 CSV 文件'}, status=400)
            return self._batch_download_parse(request, paths)
        elif remote_path:
            if not _is_csv(remote_path):
                return Response({'error': '仅支持 CSV 文件'}, status=400)
            return self._single_download_parse(request, remote_path)
        else:
            return Response({'error': '需要 path 或 paths 参数'}, status=400)

    def _single_download_parse(self, request, remote_path):
        sftp = self._get_connection(request)
        if not sftp:
            return Response({'error': 'not_connected'}, status=400)

        try:
            filename = os.path.basename(remote_path)
            # 单文件解析 → single 目录（旧实现下载到 batch 目录却注册 single，
            # 造成目录错位 + 修复中心误报孤儿）
            upload_dir = _user_upload_dir(request.user, 'single')

            # Handle collision
            file_path = os.path.join(upload_dir, filename)
            if os.path.exists(file_path):
                ts = int(time.time())
                name, ext = os.path.splitext(filename)
                file_path = os.path.join(upload_dir, f"{name}_{ts}{ext}")

            sftp.get(remote_path, file_path)

            datafile = _register_file(request.user, file_path, 'single')
            return Response({
                'status': 'ok',
                'files': [{'id': datafile.id, 'filename': datafile.filename}],
            })
        except Exception as e:
            pool.invalidate(request.user.id)
            return Response({'error': str(e)}, status=400)

    def _batch_download_parse(self, request, paths):
        sftp = self._get_connection(request)
        if not sftp:
            return Response({'error': 'not_connected'}, status=400)

        try:
            # Determine batch name from first path's parent dir
            first_parent = os.path.basename(os.path.dirname(paths[0]))
            batch_name = first_parent or f"batch_{int(time.time())}"

            upload_dir = _user_upload_dir(request.user, 'batch')
            batch_dir = os.path.join(upload_dir, batch_name)
            os.makedirs(batch_dir, exist_ok=True)

            created = []
            for remote_path in paths:
                try:
                    filename = os.path.basename(remote_path)
                    if _is_summary_csv(filename):
                        continue  # summary dump, not test data
                    file_path = os.path.join(batch_dir, filename)

                    sftp.get(remote_path, file_path)

                    datafile = _register_file(request.user, file_path, 'batch', batch_name)
                    created.append({'id': datafile.id, 'filename': datafile.filename})
                except:
                    continue

            return Response({
                'status': 'ok',
                'batch_name': batch_name,
                'files': created,
            })
        except Exception as e:
            pool.invalidate(request.user.id)
            return Response({'error': str(e)}, status=400)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _collect_files(self, sftp, remote_dir, result, rel_prefix, only_data):
        """Recursively collect files from a remote directory."""
        remote_dir = remote_dir.rstrip('/')
        try:
            attrs = sftp.listdir_attr(remote_dir)
        except Exception as e:
            logger.warning(f"SFTP listdir failed for {remote_dir}: {e}")
            return

        for attr in attrs:
            name = attr.filename
            if name.startswith('.'):
                continue
            remote_path = f"{remote_dir}/{name}"
            rel_path = f"{rel_prefix}{name}" if rel_prefix else name

            if S_ISDIR(attr.st_mode):
                self._collect_files(sftp, remote_path, result, f"{rel_path}/", only_data)
            else:
                ext = os.path.splitext(name)[1].lower()
                if only_data and (ext != '.csv' or _is_summary_csv(name)):
                    # Skip non-CSV and summary dumps (Sum_*.csv): they are not
                    # per-unit ATE data and must not be downloaded/registered.
                    continue
                result.append((remote_path, rel_path, attr.st_size, attr.st_mtime))
