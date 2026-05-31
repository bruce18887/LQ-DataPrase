import api from './index'

export const sftpApi = {
  connect(host: string, port: number, username: string, password: string) {
    return api.post('/sftp/connect/', { host, port, username, password })
  },
  disconnect() {
    return api.post('/sftp/disconnect/')
  },
  listFiles(path: string) {
    return api.get('/sftp/list_files/', { params: { path } })
  },
  download(path: string) {
    return api.post('/sftp/download/', { path }, { responseType: 'blob' })
  },
  getConfigs() {
    return api.get('/sftp/configs/')
  },
  saveConfig(name: string, config: { host: string; port: number; username: string; password: string }) {
    return api.post('/sftp/save_config/', { name, ...config })
  },
}
