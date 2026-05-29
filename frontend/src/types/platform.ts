export interface PaginationPayload {
  current_page: number
  total: number
  per_page: number
  last_page: number
}

export interface AiTask {
  id: number
  title: string
  goal: string | null
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  priority: 'low' | 'medium' | 'high'
  metadata: Record<string, unknown> | null
  started_at: string | null
  completed_at: string | null
  created_at: string
  logs?: TaskLog[]
}

export interface TaskLog {
  id: number
  task_id: number
  level: string
  event: string
  message: string | null
  context: Record<string, unknown> | null
  created_at: string
}

export interface ActivityLog {
  id: number
  action: string
  entity_type: string | null
  entity_id: number | null
  method: string | null
  endpoint: string | null
  status_code: number | null
  description: string | null
  created_at: string
  user?: {
    id: number
    name: string
    email: string
  } | null
}

export interface MemoryItem {
  id: number
  memory_type: 'preference' | 'workflow' | 'context' | 'tooling'
  key: string
  value: string
  importance: number
  last_used_at: string | null
  updated_at: string
}

export interface PermissionPolicy {
  id: number
  scope: 'domain' | 'folder' | 'tool'
  resource: string
  access: 'allow' | 'deny'
  requires_confirmation: boolean
}

export interface ApprovalRequest {
  id: number
  user_id: number
  task_id: number | null
  action_type: string
  target: string
  payload: Record<string, unknown> | null
  status: 'pending' | 'approved' | 'rejected'
  reviewed_by: number | null
  decision_reason: string | null
  reviewed_at: string | null
  created_at: string
}

export interface UserNotification {
  id: number
  type: string
  title: string
  body: string | null
  data: Record<string, unknown> | null
  read_at: string | null
  created_at: string
}

export interface HealthSnapshot {
  services: {
    backend: { status: string; timestamp: string }
    ai_service: { status: string }
    queue: { status: string; pending_tasks: number; running_tasks: number }
    realtime: { status: string; transport: string }
  }
  counts: {
    unread_notifications: number
    pending_approvals: number
  }
}
