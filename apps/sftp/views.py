import os, io, tempfile, zipfile, time
import paramiko
from stat import S_ISDIR
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.core.cache import cache
from django.http import FileResponse, StreamingHttpResponse

from apps.datafiles.models import DataFile, ParseHistory
from apps.datafiles.parsers import get_parser, BaseATEParser
from apps.datafiles.views import _user_upload_dir

SFTP_CACHE_PREFIX = 'sftp_conn_'

SORT_KEYS = {
    'name': lambda x: x['name'].lower(),
    'mtime': lambda x: x.get('mtime', 0) or 0,
    'size': lambda x: x.get('size', 0) or 0,
    'type': lambda x: os.path.splitext(x['name'])[1].lower(),
}


class SftpViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    def _get_conn_key(self, request):
        return f"{SFTP_CACHE_PREFIX}{request.user.id}"

    def _get_connection(self, request):
        data = cache.get(self._get_conn_key(request))
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
        host = request.data.get('host')
        port = int(request.data.get('port', 22))
        username = request.data.get('username')
        password = request.data.get('password')

        try:
            transport = paramiko.Transport((host, port))
            transport.connect(username=username, password=password)
            transport.close()
            cache.set(self._get_conn_key(request), {
                'host': host, 'port': port, 'username': username, 'password': password,
            }, timeout=3600)
            return Response({'status': 'connected', 'host': host})
        except Exception as e:
            return Response({'status': 'error', 'message': str(e)}, status=400)

    @action(detail=False, methods=['post'])
    def disconnect(self, request):
        cache.delete(self._get_conn_key(request))
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
    # Download single file
    # ------------------------------------------------------------------

    @action(detail=False, methods=['post'])
    def download(self, request):
        remote_path = request.data.get('path')
        transport, sftp = self._get_connection(request)
        if not sftp:
            return Response({'error': 'not_connected'}, status=400)

        try:
            buf = io.BytesIO()
            sftp.getfo(remote_path, buf)
            buf.seek(0)
            sftp.close()
            transport.close()

            filename = os.path.basename(remote_path)
            response = FileResponse(buf, as_attachment=True, filename=filename,
                                   content_type='application/octet-stream')
            return response
        except Exception as e:
            try:
                sftp.close()
                transport.close()
            except:
                pass
            return Response({'error': str(e)}, status=400)

    # ------------------------------------------------------------------
    # Download directory as ZIP (recursive)
    # ------------------------------------------------------------------

    @action(detail=False, methods=['post'])
    def download_dir(self, request):
        remote_path = request.data.get('path')
        only_data = request.data.get('only_data', False)

        transport, sftp = self._get_connection(request)
        if not sftp:
            return Response({'error': 'not_connected'}, status=400)

        try:
            # Collect all files recursively
            file_list = []
            self._collect_files(sftp, remote_path, file_list, '', only_data)

            if not file_list:
                sftp.close()
                transport.close()
                return Response({'error': '目录为空'}, status=400)

            # Build ZIP in memory
            buf = io.BytesIO()
            dir_name = os.path.basename(remote_path.rstrip('/')) or 'download'
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                for remote_fp, rel_path, _size, _mtime in file_list:
                    try:
                        file_buf = io.BytesIO()
                        sftp.getfo(remote_fp, file_buf)
                        file_buf.seek(0)
                        zf.writestr(f"{dir_name}/{rel_path}", file_buf.read())
                    except:
                        pass

            buf.seek(0)
            sftp.close()
            transport.close()

            response = FileResponse(buf, as_attachment=True,
                                   filename=f'{dir_name}.zip',
                                   content_type='application/zip')
            return response
        except Exception as e:
            try:
                sftp.close()
                transport.close()
            except:
                pass
            return Response({'error': str(e)}, status=400)

    # ------------------------------------------------------------------
    # Batch download (multiple files as ZIP)
    # ------------------------------------------------------------------

    @action(detail=False, methods=['post'])
    def download_batch(self, request):
        paths = request.data.get('paths', [])
        if not paths:
            return Response({'error': '未选择文件'}, status=400)

        transport, sftp = self._get_connection(request)
        if not sftp:
            return Response({'error': 'not_connected'}, status=400)

        try:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                for remote_path in paths:
                    try:
                        file_buf = io.BytesIO()
                        sftp.getfo(remote_path, file_buf)
                        file_buf.seek(0)
                        zf.writestr(os.path.basename(remote_path), file_buf.read())
                    except:
                        pass

            buf.seek(0)
            sftp.close()
            transport.close()

            response = FileResponse(buf, as_attachment=True,
                                   filename='batch_download.zip',
                                   content_type='application/zip')
            return response
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
            # Batch mode: multiple files from same directory
            return self._batch_download_parse(request, paths)
        elif remote_path:
            # Single file mode
            return self._single_download_parse(request, remote_path)
        else:
            return Response({'error': '需要 path 或 paths 参数'}, status=400)

    def _single_download_parse(self, request, remote_path):
        transport, sftp = self._get_connection(request)
        if not sftp:
            return Response({'error': 'not_connected'}, status=400)

        try:
            filename = os.path.basename(remote_path)
            upload_dir = _user_upload_dir(request.user.id, 'batch')

            # Handle collision
            file_path = os.path.join(upload_dir, filename)
            if os.path.exists(file_path):
                ts = int(time.time())
                name, ext = os.path.splitext(filename)
                file_path = os.path.join(upload_dir, f"{name}_{ts}{ext}")

            sftp.get(remote_path, file_path)
            file_size = os.path.getsize(file_path)

            # Detect format
            format_type = 'Unknown'
            row_count, col_count = 0, 0
            program_name = ''
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    head = f.read(4096)
                format_type = BaseATEParser.identify_format(head)
                if format_type != 'Unknown':
                    parser = get_parser(format_type)
                    df, metadata = parser.parse(file_path)
                    if df is not None:
                        row_count = df.shape[0]
                        col_count = df.shape[1]
                        program_name = metadata.get('program_name', '')
            except:
                pass

            datafile = DataFile.objects.create(
                owner=request.user,
                filename=os.path.basename(file_path),
                file_path=file_path,
                file_size=file_size,
                format_type=format_type if format_type != 'Unknown' else 'CTA8290D',
                file_type='single',
                row_count=row_count,
                col_count=col_count,
                program_name=program_name,
                status='ready' if format_type != 'Unknown' else 'error',
            )

            ParseHistory.objects.create(
                user=request.user,
                datafile=datafile,
                filename=datafile.filename,
                filepath=file_path,
                format_type=datafile.format_type,
                rows=row_count,
                cols=col_count,
            )

            sftp.close()
            transport.close()
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

            upload_dir = _user_upload_dir(request.user.id, 'batch')
            batch_dir = os.path.join(upload_dir, batch_name)
            os.makedirs(batch_dir, exist_ok=True)

            created = []
            for remote_path in paths:
                try:
                    filename = os.path.basename(remote_path)
                    file_path = os.path.join(batch_dir, filename)

                    sftp.get(remote_path, file_path)
                    file_size = os.path.getsize(file_path)

                    # Detect format
                    format_type = 'Unknown'
                    row_count, col_count = 0, 0
                    program_name = ''
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            head = f.read(4096)
                        format_type = BaseATEParser.identify_format(head)
                        if format_type != 'Unknown':
                            parser = get_parser(format_type)
                            df, metadata = parser.parse(file_path)
                            if df is not None:
                                row_count = df.shape[0]
                                col_count = df.shape[1]
                                program_name = metadata.get('program_name', '')
                    except:
                        pass

                    datafile = DataFile.objects.create(
                        owner=request.user,
                        filename=filename,
                        file_path=file_path,
                        file_size=file_size,
                        format_type=format_type if format_type != 'Unknown' else 'CTA8290D',
                        file_type='batch',
                        batch_name=batch_name,
                        row_count=row_count,
                        col_count=col_count,
                        program_name=program_name,
                        status='ready' if format_type != 'Unknown' else 'error',
                    )

                    ParseHistory.objects.create(
                        user=request.user,
                        datafile=datafile,
                        filename=filename,
                        filepath=file_path,
                        format_type=datafile.format_type,
                        rows=row_count,
                        cols=col_count,
                    )

                    created.append({'id': datafile.id, 'filename': filename})
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
    # Configs (stubs)
    # ------------------------------------------------------------------

    @action(detail=False, methods=['get'])
    def configs(self, request):
        return Response({'configs': []})

    @action(detail=False, methods=['post'])
    def save_config(self, request):
        return Response({'message': 'Config saved'})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _collect_files(self, sftp, remote_dir, result, rel_prefix, only_data):
        """Recursively collect files from a remote directory."""
        try:
            attrs = sftp.listdir_attr(remote_dir)
        except:
            return

        for attr in attrs:
            name = attr.filename
            if name.startswith('.'):
                continue
            remote_path = f"{remote_dir}/{name}"
            if remote_dir.endswith('/'):
                remote_path = f"{remote_dir}{name}"
            rel_path = f"{rel_prefix}{name}" if rel_prefix else name

            if S_ISDIR(attr.st_mode):
                self._collect_files(sftp, remote_path, result, f"{rel_path}/", only_data)
            else:
                ext = os.path.splitext(name)[1].lower()
                if only_data and ext not in ('.csv', '.txt', '.dat'):
                    continue
                result.append((remote_path, rel_path, attr.st_size, attr.st_mtime))
