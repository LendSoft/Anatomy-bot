import axios from 'axios'
import { message } from 'antd'

const TOKEN_KEY = 'anatomy_admin_token'

export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = (token) => localStorage.setItem(TOKEN_KEY, token)
export const clearToken = () => localStorage.removeItem(TOKEN_KEY)

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  // Индексация и генерация ответа занимают время — короткий таймаут
  // обрывал бы нормальные запросы
  timeout: 300000,
})

api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status

    if (status === 401) {
      clearToken()
      // Полная перезагрузка проще, чем разбирать состояние на месте
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
      return Promise.reject(error)
    }

    const detail = error.response?.data?.detail
    if (detail && status !== 404) {
      message.error(typeof detail === 'string' ? detail : 'Ошибка запроса')
    } else if (!error.response) {
      message.error('Сервер недоступен')
    }

    return Promise.reject(error)
  },
)

export default api
