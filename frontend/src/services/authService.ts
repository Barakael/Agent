import api from './api'

interface AuthResponse {
  message: string
  user: {
    id: number
    name: string
    email: string
    role: string
  }
  token: string
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  const response = await api.post('/auth/login', { email, password })
  return response.data
}

export async function register(
  name: string,
  email: string,
  password: string,
  password_confirmation: string,
): Promise<AuthResponse> {
  const response = await api.post('/auth/register', {
    name,
    email,
    password,
    password_confirmation,
  })
  return response.data
}

export async function logout() {
  await api.post('/auth/logout')
}

export async function updateProfile(payload: { name?: string; email?: string }) {
  const response = await api.put('/auth/profile', payload)
  return response.data.user as AuthResponse['user']
}

export async function changePassword(payload: {
  current_password: string
  password: string
  password_confirmation: string
}) {
  await api.post('/auth/change-password', payload)
}
