import api from './api'

export interface ConversationSummary {
  id: number
  title: string | null
  description: string | null
  status: string
  message_count: number
  last_message_at: string | null
}

export interface MessagePayload {
  id: number
  conversation_id: number
  user_id: number
  role: string
  content: string
  metadata: Record<string, unknown> | null
  status: string
  created_at: string
  updated_at: string
}

export async function fetchConversations() {
  const response = await api.get('/conversations')
  return response.data.data
}

export async function createConversation(title: string, description: string) {
  const response = await api.post('/conversations', { title, description })
  return response.data.data
}

export async function fetchMessages(conversationId: number) {
  const response = await api.get(`/conversations/${conversationId}/messages`)
  return response.data.data
}

export async function sendMessage(conversationId: number, content: string) {
  const response = await api.post(`/conversations/${conversationId}/messages`, { content })
  return response.data
}
