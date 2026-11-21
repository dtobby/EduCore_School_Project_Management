import axios from 'axios'

// A single axios instance used by every view and store.
// The request interceptor stamps every outgoing request with the stored JWT.
const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export default api
