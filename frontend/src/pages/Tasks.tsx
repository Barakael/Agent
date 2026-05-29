import { useEffect, useState } from 'react'
import AppShell from '../components/layout/AppShell'
import EmptyState from '../components/ui/EmptyState'
import { createTask, fetchTasks, retryTask } from '../services/platformService'
import type { AiTask } from '../types/platform'
import { useRealtime } from '../contexts/RealtimeContext'

const statuses: AiTask['status'][] = ['pending', 'running', 'completed', 'failed', 'cancelled']

export default function TasksPage() {
  const { lastMessage } = useRealtime()
  const [tasks, setTasks] = useState<AiTask[]>([])
  const [filterStatus, setFilterStatus] = useState<string>('')
  const [newTaskTitle, setNewTaskTitle] = useState('')
  const [newTaskGoal, setNewTaskGoal] = useState('')

  const loadTasks = async () => {
    const response = await fetchTasks(filterStatus || undefined)
    setTasks(response.data)
  }

  useEffect(() => {
    void loadTasks()
  }, [filterStatus])

  useEffect(() => {
    if (lastMessage?.channel === 'tasks') {
      void loadTasks()
    }
  }, [lastMessage])

  const handleCreateTask = async () => {
    if (!newTaskTitle.trim()) return
    await createTask({ title: newTaskTitle, goal: newTaskGoal, priority: 'medium' })
    setNewTaskTitle('')
    setNewTaskGoal('')
    await loadTasks()
  }

  return (
    <AppShell title="Task Queue">
      <section className="grid gap-4 xl:grid-cols-[320px_1fr]">
        <article className="panel">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Create Task</h2>
          <div className="mt-3 space-y-2">
            <input className="form-input" placeholder="Task title" value={newTaskTitle} onChange={(e) => setNewTaskTitle(e.target.value)} />
            <textarea className="form-input min-h-24" placeholder="Goal (optional)" value={newTaskGoal} onChange={(e) => setNewTaskGoal(e.target.value)} />
            <button type="button" className="btn-primary w-full" onClick={handleCreateTask}>
              Queue Task
            </button>
          </div>
          <h3 className="mt-6 text-sm font-semibold text-slate-900 dark:text-slate-100">Filter Status</h3>
          <select className="form-input mt-2" value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
            <option value="">All</option>
            {statuses.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </article>

        <article className="panel">
          <h2 className="mb-3 text-sm font-semibold text-slate-900 dark:text-slate-100">Task Queue Visualization</h2>
          {tasks.length === 0 ? (
            <EmptyState title="No tasks found" description="Create your first task to start autonomous execution tracking." />
          ) : (
            <div className="space-y-3">
              {tasks.map((task) => (
                <div key={task.id} className="rounded-xl border p-4 dark:border-slate-700">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <h3 className="font-semibold text-slate-900 dark:text-slate-100">{task.title}</h3>
                      <p className="text-xs text-slate-500 dark:text-slate-400">{task.goal ?? 'No goal details'}</p>
                    </div>
                    <span className="rounded-md bg-slate-100 px-2 py-1 text-xs font-semibold uppercase dark:bg-slate-800">{task.status}</span>
                  </div>
                  <div className="mt-3 h-2 rounded-full bg-slate-200 dark:bg-slate-800">
                    <div
                      className={`h-2 rounded-full ${
                        task.status === 'completed'
                          ? 'bg-emerald-500'
                          : task.status === 'running'
                            ? 'bg-brand-500'
                            : task.status === 'failed'
                              ? 'bg-red-500'
                              : 'bg-slate-400'
                      }`}
                      style={{ width: task.status === 'completed' ? '100%' : task.status === 'running' ? '55%' : task.status === 'failed' ? '100%' : '20%' }}
                    />
                  </div>
                  {task.status === 'failed' ? (
                    <button type="button" className="btn-secondary mt-3" onClick={() => void retryTask(task.id).then(loadTasks)}>
                      Retry Task
                    </button>
                  ) : null}
                  {task.logs && task.logs.length > 0 ? (
                    <div className="mt-3 rounded-lg bg-slate-50 p-3 text-xs dark:bg-slate-800">
                      {task.logs.slice(-3).map((log) => (
                        <p key={log.id} className="text-slate-600 dark:text-slate-300">
                          {new Date(log.created_at).toLocaleTimeString()} · {log.event}
                        </p>
                      ))}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </article>
      </section>
    </AppShell>
  )
}
