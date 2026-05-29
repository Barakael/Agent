import api from './api'

export interface ConversationSummary {
  id: number
  title: string | null
  description: string | null
  status: string
  message_count: number
  last_message_at: string | null
}

export interface ToolActionPayload {
  tool: string
  action: string
  payload: Record<string, unknown>
  output: Record<string, unknown>
  trace_id?: string
}

export interface MessagePayload {
  id: number
  conversation_id: number
  user_id: number
  role: string
  content: string
  metadata: {
    tool_actions?: ToolActionPayload[]
    agent_mode?: boolean
    [key: string]: unknown
  } | null
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

export async function updateConversation(conversationId: number, payload: { title?: string; description?: string }) {
  const response = await api.put(`/conversations/${conversationId}`, payload)
  return response.data.data
}

export async function archiveConversation(conversationId: number) {
  const response = await api.post(`/conversations/${conversationId}/archive`)
  return response.data.data
}

export async function deleteConversation(conversationId: number) {
  await api.delete(`/conversations/${conversationId}`)
}
