import api from './client'

export const auth = {
  login: (email, password) => api.post('/auth/login', { email, password }),
  me: () => api.get('/auth/me'),
  changePassword: (current_password, new_password) =>
    api.post('/auth/change-password', { current_password, new_password }),
  listUsers: () => api.get('/auth/users'),
  createUser: (payload) => api.post('/auth/users', payload),
  deleteUser: (id) => api.delete(`/auth/users/${id}`),
}

export const stats = {
  overview: (days = 30) => api.get('/stats/overview', { params: { days } }),
  daily: (days = 30) => api.get('/stats/daily', { params: { days } }),
  topQuestions: (days = 30, limit = 20) =>
    api.get('/stats/top-questions', { params: { days, limit } }),
  unanswered: (days = 30, limit = 50) =>
    api.get('/stats/unanswered', { params: { days, limit } }),
}

export const documents = {
  list: (params) => api.get('/documents', { params }),
  get: (id) => api.get(`/documents/${id}`),
  update: (id, payload) => api.patch(`/documents/${id}`, payload),
  remove: (id) => api.delete(`/documents/${id}`),
  reindex: (id) => api.post(`/documents/${id}/reindex`),
  chunks: (id, params) => api.get(`/documents/${id}/chunks`, { params }),
  sections: () => api.get('/documents/meta/sections'),
  upload: (formData, onProgress) =>
    api.post('/documents', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (event) => {
        if (onProgress && event.total) {
          onProgress(Math.round((event.loaded * 100) / event.total))
        }
      },
    }),
}

export const images = {
  list: (params) => api.get('/images', { params }),
  update: (id, payload) => api.patch(`/images/${id}`, payload),
  remove: (id) => api.delete(`/images/${id}`),
  reindexAll: () => api.post('/images/reindex'),
  fileUrl: (id, thumbnail = false) =>
    `${import.meta.env.VITE_API_BASE_URL || '/api/v1'}/images/${id}/file${
      thumbnail ? '?thumbnail=true' : ''
    }`,
  upload: (formData, onProgress) =>
    api.post('/images', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (event) => {
        if (onProgress && event.total) {
          onProgress(Math.round((event.loaded * 100) / event.total))
        }
      },
    }),
}

export const prompts = {
  list: (params) => api.get('/prompts', { params }),
  active: (kind) => api.get(`/prompts/active/${kind}`),
  defaults: (kind) => api.get(`/prompts/defaults/${kind}`),
  create: (payload) => api.post('/prompts', payload),
  activate: (id) => api.post(`/prompts/${id}/activate`),
  remove: (id) => api.delete(`/prompts/${id}`),
}

export const settings = {
  get: () => api.get('/settings'),
  update: (values) => api.put('/settings', { values }),
  reset: () => api.post('/settings/reset'),
}

export const chat = {
  ask: (payload) => api.post('/chat/ask', payload),
  feedback: (messageId, value) =>
    api.post(`/chat/messages/${messageId}/feedback`, { value }),
}

export const logs = {
  conversations: (params) => api.get('/logs/conversations', { params }),
  conversationMessages: (id) => api.get(`/logs/conversations/${id}/messages`),
  messages: (params) => api.get('/logs/messages', { params }),
  message: (id) => api.get(`/logs/messages/${id}`),
}

export const testing = {
  listSets: () => api.get('/testing/sets'),
  createSet: (payload) => api.post('/testing/sets', payload),
  deleteSet: (id) => api.delete(`/testing/sets/${id}`),
  listQuestions: (setId) => api.get(`/testing/sets/${setId}/questions`),
  createQuestion: (setId, payload) =>
    api.post(`/testing/sets/${setId}/questions`, payload),
  deleteQuestion: (id) => api.delete(`/testing/questions/${id}`),
  importQuestions: (setId, formData) =>
    api.post(`/testing/sets/${setId}/questions/import`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  listRuns: (params) => api.get('/testing/runs', { params }),
  startRun: (payload) => api.post('/testing/runs', payload),
  getRun: (id) => api.get(`/testing/runs/${id}`),
  runResults: (id) => api.get(`/testing/runs/${id}/results`),
  deleteRun: (id) => api.delete(`/testing/runs/${id}`),
  setManualScore: (resultId, payload) =>
    api.post(`/testing/results/${resultId}/score`, payload),
}

export const glossary = {
  list: (params) => api.get('/glossary', { params }),
  create: (payload) => api.post('/glossary', payload),
  remove: (id) => api.delete(`/glossary/${id}`),
  import: (formData) =>
    api.post('/glossary/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
}

export const health = {
  full: () => api.get('/health/full'),
}
