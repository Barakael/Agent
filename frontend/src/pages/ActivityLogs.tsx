import { useEffect, useState } from 'react'
import AppShell from '../components/layout/AppShell'
import EmptyState from '../components/ui/EmptyState'
import { fetchActivityLogs } from '../services/platformService'
import type { ActivityLog } from '../types/platform'
import { useRealtime } from '../contexts/RealtimeContext'

export default function ActivityLogsPage() {
  const { lastMessage } = useRealtime()
  const [logs, setLogs] = useState<ActivityLog[]>([])
  const [actionFilter, setActionFilter] = useState('')
  const [entityFilter, setEntityFilter] = useState('')

  const loadLogs = async () => {
    const response = await fetchActivityLogs({
      action: actionFilter || undefined,
      entity_type: entityFilter || undefined,
    })
    setLogs(response.data)
  }

  useEffect(() => {
    void loadLogs()
  }, [actionFilter, entityFilter])

  useEffect(() => {
    if (lastMessage?.channel === 'activity') {
      void loadLogs()
    }
  }, [lastMessage])

  return (
    <AppShell title="Activity Logs">
      <section className="panel">
        <div className="mb-4 grid gap-2 sm:grid-cols-3">
          <input className="form-input" placeholder="Filter by action (GET, POST...)" value={actionFilter} onChange={(e) => setActionFilter(e.target.value)} />
          <input className="form-input" placeholder="Filter by entity (task, api...)" value={entityFilter} onChange={(e) => setEntityFilter(e.target.value)} />
          <button type="button" className="btn-secondary" onClick={loadLogs}>
            Refresh Logs
          </button>
        </div>
        {logs.length === 0 ? (
          <EmptyState title="No activity logs" description="Logs will appear as soon as API operations occur." />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead>
                <tr className="border-b text-xs uppercase tracking-wide text-slate-500 dark:border-slate-700">
                  <th className="px-2 py-3">Time</th>
                  <th className="px-2 py-3">Action</th>
                  <th className="px-2 py-3">Entity</th>
                  <th className="px-2 py-3">Endpoint</th>
                  <th className="px-2 py-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <tr key={log.id} className="border-b dark:border-slate-800">
                    <td className="px-2 py-3">{new Date(log.created_at).toLocaleString()}</td>
                    <td className="px-2 py-3 font-semibold">{log.action}</td>
                    <td className="px-2 py-3">{log.entity_type ?? 'api'}</td>
                    <td className="px-2 py-3">{log.endpoint ?? '-'}</td>
                    <td className="px-2 py-3">{log.status_code ?? '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </AppShell>
  )
}
