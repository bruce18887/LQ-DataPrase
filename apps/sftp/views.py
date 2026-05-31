import os, io, tempfile
import paramiko
from stat import S_ISDIR
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.core.cache import cache
from django.http import FileResponse

from apps.datafiles.models import DataFile
from apps.datafiles.parsers import get_parser, BaseATEParser

SFTP_CACHE_PREFIX = 'sftp_conn_'

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

    @action(detail=False, methods=['get'])
    def list_files(self, request):
        path = request.query_params.get('path', '/')
        transport, sftp = self._get_connection(request)
        if not sftp:
            return Response({'error': 'not_connected'}, status=400)

        try:
            items = []
            for entry in sorted(sftp.listdir_attr(path), key=lambda x: (not S_ISDIR(x.st_mode), x.filename.lower())):
                items.append({
                    'name': entry.filename,
                    'is_dir': S_ISDIR(entry.st_mode),
                    'size': entry.st_size,
                    'mtime': entry.st_mtime,
                })
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

    @action(detail=False, methods=['post'])
    def download(self, request):
        remote_path = request.data.get('path')
        transport, sftp = self._get_connection(request)
        if not sftp:
            return Response({'error': 'not_connected'}, status=400)

        try:
            local_file = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
            sftp.get(remote_path, local_file.name)
            sftp.close()
            transport.close()

            with open(local_file.name, 'rb') as f:
                content = f.read()

            os.unlink(local_file.name)
            filename = os.path.basename(remote_path)
            response = FileResponse(io.BytesIO(content), as_attachment=True, filename=filename,
                                   content_type='application/octet-stream')
            return response
        except Exception as e:
            try:
                sftp.close()
                transport.close()
            except:
                pass
            return Response({'error': str(e)}, status=400)

    @action(detail=False, methods=['get'])
    def configs(self, request):
        return Response({'configs': []})

    @action(detail=False, methods=['post'])
    def save_config(self, request):
        return Response({'message': 'Config saved'})
