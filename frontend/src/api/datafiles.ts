import api from './index'

export const datafilesApi = {
  upload(file: File, onProgress?: (pct: number) => void) {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/upload/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (e.total && onProgress) onProgress(Math.round((e.loaded * 100) / e.total))
      },
    })
  },
  list() {
    return api.get('/files/')
  },
  activate(id: number) {
    return api.put(`/activate/${id}/`)
  },
  remove(id: number) {
    return api.delete(`/files/${id}/`)
  },
  browse(params: { page?: number; search?: string; passfail?: string }) {
    return api.get('/browse/', { params })
  },
  history() {
    return api.get('/history/')
  },
}
