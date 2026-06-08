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
from .cache import get_session, set_session, delete_session, SftpSessionCacheError
from .config_views import SftpConfigMixin
from .models import SftpConfig

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
        try:
            data = get_session(request.user.id)
        except SftpSessionCacheError:
            return None, None
        if not data:
            return None, None
        try:
            transport = paramiko.Transport((data['host'], data['port']))
            transport.connect(username=data['username'], password=data['password'])
            sftp = paramiko.SFTPClient.from_transport(transport)
            return transport, sftp
        except:
            return None, None

    # ------------------------------------------------------------------
    # Connect / Disconnect
    # ------------------------------------------------------------------

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
            host = cfg.host
            port = cfg.port
            username = cfg.username
            password = cfg.get_password()
        else:
            host = request.data.get('host')
            port = int(request.data.get('port', 22))
            username = request.data.get('username')
            password = request.data.get('password')

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
        return Response({'status': 'connected', 'host': host})

    @action(detail=False, methods=['post'])
    def disconnect(self, request):
        delete_session(request.user.id)
        return Response({'status': 'disconnected'})

    # ------------------------------------------------------------------
    # List files (with sorting)
    # ------------------------------------------------------------------

    @action(detail=False, methods=['get'])
    def list_files(self, request):
        path = request.query_params.get('path', '/')
        sort_by = request.query_params.get('sort_by', 'name')
        sort_order = request.query_params.get('sort_order', 'asc')

        transport, sftp = self._get_connection(request)
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

            # Sort: directories first, then by the requested key
            key_fn = SORT_KEYS.get(sort_by, SORT_KEYS['name'])
            reverse = sort_order == 'desc'
            items.sort(key=lambda x: (not x['is_dir'], key_fn(x)), reverse=reverse)

            sftp.close()
            transport.close()
            return Response({'path': path, 'items': items})
        except Exception as e:
            try:
                sftp.close()
                transport.close()
            except:
                pass
            return Response({'error': str(e)}, status=400)

    # ------------------------------------------------------------------
    # Download single file → save to media
    # ------------------------------------------------------------------

    @action(detail=False, methods=['post'])
    def download(self, request):
        remote_path = request.data.get('path')
        if not _is_csv(remote_path):
            return Response({'error': '仅支持 CSV 文件'}, status=400)

        transport, sftp = self._get_connection(request)
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
            sftp.close()
            transport.close()
            return Response({
                'status': 'ok',
                'filename': os.path.basename(file_path),
                'size': file_size,
                'path': file_path,
            })
        except Exception as e:
            try:
                sftp.close()
                transport.close()
            except:
                pass
            return Response({'error': str(e)}, status=400)

    # ------------------------------------------------------------------
    # Download directory → save individual files to media (SSE progress)
    # ------------------------------------------------------------------

    @action(detail=False, methods=['post'])
    def download_dir(self, request):
        remote_path = request.data.get('path')

        transport, sftp = self._get_connection(request)
        if not sftp:
            return Response({'error': 'not_connected'}, status=400)

        # Collect CSV files only
        file_list = []
        self._collect_files(sftp, remote_path, file_list, '', True)

        if not file_list:
            sftp.close()
            transport.close()
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
            finally:
                try:
                    sftp.close()
                    transport.close()
                except Exception:
                    pass

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

        transport, sftp = self._get_connection(request)
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
                    saved.append({
                        'filename': os.path.basename(file_path),
                        'size': os.path.getsize(file_path),
                    })
                except Exception as e:
                    logger.warning(f"SFTP batch download failed for {remote_path}: {e}")

            sftp.close()
            transport.close()
            return Response({
                'status': 'ok',
                'files': saved,
                'count': len(saved),
            })
        except Exception as e:
            try:
                sftp.close()
                transport.close()
            except:
                pass
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
        transport, sftp = self._get_connection(request)
        if not sftp:
            return Response({'error': 'not_connected'}, status=400)

        try:
            filename = os.path.basename(remote_path)
            upload_dir = _user_upload_dir(request.user, 'batch')

            # Handle collision
            file_path = os.path.join(upload_dir, filename)
            if os.path.exists(file_path):
                ts = int(time.time())
                name, ext = os.path.splitext(filename)
                file_path = os.path.join(upload_dir, f"{name}_{ts}{ext}")

            sftp.get(remote_path, file_path)
            sftp.close()
            transport.close()

            datafile = _register_file(request.user, file_path, 'single')
            return Response({
                'status': 'ok',
                'files': [{'id': datafile.id, 'filename': datafile.filename}],
            })
        except Exception as e:
            try:
                sftp.close()
                transport.close()
            except:
                pass
            return Response({'error': str(e)}, status=400)

    def _batch_download_parse(self, request, paths):
        transport, sftp = self._get_connection(request)
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

            sftp.close()
            transport.close()
            return Response({
                'status': 'ok',
                'batch_name': batch_name,
                'files': created,
            })
        except Exception as e:
            try:
                sftp.close()
                transport.close()
            except:
                pass
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
