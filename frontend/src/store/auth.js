import { create } from 'zustand'
import { auth } from '../api/endpoints'
import { clearToken, getToken, setToken } from '../api/client'

export const useAuthStore = create((set) => ({
  user: null,
  // true, пока не проверили сохранённый токен — иначе на первом кадре
  // мелькает страница входа у уже авторизованного пользователя
  loading: true,

  async init() {
    if (!getToken()) {
      set({ user: null, loading: false })
      return
    }
    try {
      const { data } = await auth.me()
      set({ user: data, loading: false })
    } catch {
      clearToken()
      set({ user: null, loading: false })
    }
  },

  async login(email, password) {
    const { data } = await auth.login(email, password)
    setToken(data.access_token)
    const me = await auth.me()
    set({ user: me.data })
    return me.data
  },

  logout() {
    clearToken()
    set({ user: null })
  },
}))
