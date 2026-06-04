import api from './index'

export const sftpApi = {
  connect(host: string, port: number, username: string, password: string) {
    return api.post('/sftp/connect/', { host, port, username, password })
  },
  disconnect() {
    return api.post('/sftp/disconnect/')
  },
  listFiles(path: string, sortBy = 'name', sortOrder = 'asc') {
    return api.get('/sftp/list_files/', { params: { path, sort_by: sortBy, sort_order: sortOrder } })
  },
  download(path: string) {
    return api.post('/sftp/download/', { path }, { responseType: 'blob' })
  },
  downloadDir(path: string, onlyData = false) {
    return api.post('/sftp/download_dir/', { path, only_data: onlyData }, { responseType: 'blob' })
  },
  downloadBatch(paths: string[]) {
    return api.post('/sftp/download_batch/', { paths }, { responseType: 'blob' })
  },
  downloadAndParse(path: string) {
    return api.post('/sftp/download_and_parse/', { path })
  },
  downloadAndParseBatch(paths: string[]) {
    return api.post('/sftp/download_and_parse/', { paths })
  },
  getConfigs() {
    return api.get('/sftp/configs/')
  },
  saveConfig(name: string, config: { host: string; port: number; username: string; password: string }) {
    return api.post('/sftp/save_config/', { name, ...config })
  },
}
