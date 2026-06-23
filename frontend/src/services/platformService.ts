import api from './api'
import type {
  ActivityLog,
  AiTask,
  ApprovalRequest,
  HealthSnapshot,
  MemoryItem,
  PaginationPayload,
  PermissionPolicy,
  UserNotification,
} from '../types/platform'

type Paginated<T> = { data: T[]; pagination: PaginationPayload }

export async function fetchTasks(status?: string) {
  const response = await api.get<Paginated<AiTask>>('/tasks', {
    params: status ? { status } : undefined,
  })
  return response.data
}

export async function createTask(payload: { title: string; goal?: string; priority?: string }) {
  const response = await api.post<{ data: AiTask }>('/tasks', payload)
  return response.data.data
}

export async function retryTask(taskId: number) {
  const response = await api.post<{ data: AiTask }>(`/tasks/${taskId}/retry`)
  return response.data.data
}

export async function executeTaskTool(
  taskId: number,
  payload: {
    tool: string
    action: string
    payload?: Record<string, unknown>
    approval_request_id: number
  },
) {
  const response = await api.post(`/tasks/${taskId}/tools/execute`, payload)
  return response.data.data
}

export async function fetchActivityLogs(params?: {
  action?: string
  entity_type?: string
  user_id?: number
}) {
  const response = await api.get<Paginated<ActivityLog>>('/activity-logs', { params })
  return response.data
}

export async function fetchMemories(memoryType?: string) {
  const response = await api.get<Paginated<MemoryItem>>('/memories', {
    params: memoryType ? { memory_type: memoryType } : undefined,
  })
  return response.data
}

export async function createMemory(payload: {
  memory_type: string
  key: string
  value: string
  importance?: number
}) {
  const response = await api.post<{ data: MemoryItem }>('/memories', payload)
  return response.data.data
}

export async function fetchPermissionPolicies() {
  const response = await api.get<{ data: PermissionPolicy[] }>('/permissions')
  return response.data.data
}

export async function upsertPermissionPolicy(payload: {
  scope: string
  resource: string
  access: string
  requires_confirmation: boolean
}) {
  const response = await api.post<{ data: PermissionPolicy }>('/permissions', payload)
  return response.data.data
}

export async function fetchApprovals(status?: string) {
  const response = await api.get<Paginated<ApprovalRequest>>('/permissions/approvals', {
    params: status ? { status } : undefined,
  })
  return response.data
}

export async function createApproval(payload: {
  task_id?: number
  action_type: string
  target: string
  payload?: Record<string, unknown>
}) {
  const response = await api.post<{ data: ApprovalRequest }>('/permissions/approvals', payload)
  return response.data.data
}

export async function decideApproval(approvalId: number, decision: 'approved' | 'rejected', reason?: string) {
  const response = await api.post<{ data: ApprovalRequest }>(`/permissions/approvals/${approvalId}/decision`, {
    decision,
    reason,
  })
  return response.data.data
}

export async function fetchNotifications(unreadOnly = false) {
  const response = await api.get<Paginated<UserNotification>>('/notifications', {
    params: unreadOnly ? { unread: true } : undefined,
  })
  return response.data
}

export async function markNotificationRead(notificationId: number) {
  await api.post(`/notifications/${notificationId}/read`)
}

export async function markAllNotificationsRead() {
  await api.post('/notifications/read-all')
}

export async function fetchSystemHealth() {
  const response = await api.get<{ data: HealthSnapshot }>('/system/health')
  return response.data.data
}

export type RunnerStatus = {
  runner_enabled: boolean
  online: boolean
  platform: string | null
}

export async function fetchRunnerStatus(): Promise<RunnerStatus> {
  const response = await api.get<{ data: RunnerStatus }>('/runner/status')
  return response.data.data
}
