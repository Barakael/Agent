import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000/api',
  headers: {
    'Content-Type': 'application/json',
    Accept: 'application/json',
  },
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('agent_auth_token')
      localStorage.removeItem('agent_user')
      delete api.defaults.headers.common.Authorization
      if (window.location.pathname !== '/login') {
        window.location.assign('/login')
      }
    }
    if (error.response?.data?.message) {
      return Promise.reject(new Error(error.response.data.message))
    }
    return Promise.reject(error)
  },
)

export default api
