import { defineStore } from 'pinia'
import api from '../api'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('token') || null,
    user: null,
  }),

  getters: {
    isAuthenticated: (state) => !!state.token,
  },

  actions: {
    async login(username, password) {
      // POST /api/auth/token/ — returns {access, refresh}
      const { data } = await api.post('/auth/token/', { username, password })
      this.token = data.access
      localStorage.setItem('token', data.access)
    },

    async fetchMe() {
      const { data } = await api.get('/auth/me/')
      this.user = data
    },

    logout() {
      this.token = null
      this.user = null
      localStorage.removeItem('token')
    },
  },
})
