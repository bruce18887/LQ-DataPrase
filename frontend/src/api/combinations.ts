import api from './index'
import type { DataCombination } from '../types'

export interface CombinationInput {
  name: string
  description?: string
}

export const combinationsApi = {
  list: () => api.get<DataCombination[]>('/combinations/'),
  create: (input: CombinationInput) => api.post<DataCombination>('/combinations/', input),
  update: (id: number, input: Partial<CombinationInput>) =>
    api.patch<DataCombination>(`/combinations/${id}/`, input),
  remove: (id: number) => api.delete(`/combinations/${id}/`),
}
