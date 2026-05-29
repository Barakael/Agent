import { useEffect, useState } from 'react'
import AppShell from '../components/layout/AppShell'
import { createApproval, executeTaskTool, fetchApprovals, fetchTasks } from '../services/platformService'
import type { AiTask, ApprovalRequest } from '../types/platform'

export default function AutomationMonitorPage() {
  const [tasks, setTasks] = useState<AiTask[]>([])
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([])
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null)
  const [toolAction, setToolAction] = useState('browser.navigate')
  const [target, setTarget] = useState('https://example.com')
  const [resultMessage, setResultMessage] = useState('')

  useEffect(() => {
    void loadData()
  }, [])

  const loadData = async () => {
    const [taskResponse, approvalResponse] = await Promise.all([fetchTasks(), fetchApprovals('approved')])
    setTasks(taskResponse.data)
    setApprovals(approvalResponse.data)
    if (taskResponse.data.length > 0) {
      setSelectedTaskId((current) => current ?? taskResponse.data[0].id)
    }
  }

  const runToolAction = async () => {
    if (!selectedTaskId) return
    if (!window.confirm(`Confirm running ${toolAction} on ${target}?`)) {
      return
    }
    const approval = approvals[0]
    if (!approval) {
      await createApproval({
        task_id: selectedTaskId,
        action_type: toolAction,
        target,
        payload: { requested_from: 'automation_monitor' },
      })
      setResultMessage('Approval request created. Ask an admin to approve before execution.')
      return
    }
    const [tool, action] = toolAction.split('.')
    await executeTaskTool(selectedTaskId, {
      tool,
      action,
      payload: { target },
      approval_request_id: approval.id,
    })
    setResultMessage(`Tool action ${toolAction} submitted successfully.`)
  }

  return (
    <AppShell title="Browser Automation Monitor">
      <section className="panel">
        <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Execution Timeline</h2>
        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
          This stream shows the most recent autonomous runs and step traces captured by the AI execution service.
        </p>
        <div className="mt-4 space-y-3">
          <div className="rounded-lg border p-3 dark:border-slate-700">
            <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Controlled Tool Execution</h3>
            <div className="mt-2 grid gap-2 sm:grid-cols-4">
              <select className="form-input" value={selectedTaskId ?? ''} onChange={(e) => setSelectedTaskId(Number(e.target.value))}>
                {tasks.map((task) => (
                  <option key={task.id} value={task.id}>
                    Task #{task.id}
                  </option>
                ))}
              </select>
              <input className="form-input sm:col-span-1" value={toolAction} onChange={(e) => setToolAction(e.target.value)} />
              <input className="form-input sm:col-span-1" value={target} onChange={(e) => setTarget(e.target.value)} />
              <button type="button" className="btn-primary" onClick={runToolAction}>
                Execute
              </button>
            </div>
            {resultMessage ? <p className="mt-2 text-xs text-slate-500">{resultMessage}</p> : null}
          </div>
          {tasks.map((task) => (
            <div key={task.id} className="rounded-lg border p-4 dark:border-slate-700">
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{task.title}</p>
                <span className="rounded-md bg-slate-100 px-2 py-1 text-xs dark:bg-slate-800">{task.status}</span>
              </div>
              <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{task.goal ?? 'No goal summary.'}</p>
              <div className="mt-3 rounded-lg bg-slate-100 p-3 text-xs dark:bg-slate-800">
                <p>Step 1: Open target</p>
                <p>Step 2: Execute action sequence</p>
                <p>Step 3: Capture output snapshot</p>
              </div>
            </div>
          ))}
        </div>
      </section>
    </AppShell>
  )
}
