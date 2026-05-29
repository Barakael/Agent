import { useEffect, useState } from 'react'
import AppShell from '../components/layout/AppShell'
import EmptyState from '../components/ui/EmptyState'
import { createApproval, decideApproval, fetchApprovals, fetchPermissionPolicies, upsertPermissionPolicy } from '../services/platformService'
import { useAuth } from '../contexts/AuthContext'
import type { ApprovalRequest, PermissionPolicy } from '../types/platform'

export default function PermissionsPage() {
  const { user } = useAuth()
  const [policies, setPolicies] = useState<PermissionPolicy[]>([])
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([])
  const [scope, setScope] = useState('domain')
  const [resource, setResource] = useState('')
  const [access, setAccess] = useState('allow')
  const [approvalTarget, setApprovalTarget] = useState('')

  const isAdmin = user?.role === 'admin'

  const loadData = async () => {
    const [policyData, approvalData] = await Promise.all([fetchPermissionPolicies(), fetchApprovals()])
    setPolicies(policyData)
    setApprovals(approvalData.data)
  }

  useEffect(() => {
    void loadData()
  }, [])

  const savePolicy = async () => {
    if (!resource.trim()) return
    await upsertPermissionPolicy({
      scope,
      resource,
      access,
      requires_confirmation: true,
    })
    setResource('')
    await loadData()
  }

  const requestApproval = async () => {
    if (!approvalTarget.trim()) return
    await createApproval({
      action_type: 'restricted_action',
      target: approvalTarget,
      payload: { source: 'permissions_ui' },
    })
    setApprovalTarget('')
    await loadData()
  }

  return (
    <AppShell title="Permissions and Approvals">
      <section className="grid gap-4 xl:grid-cols-[1fr_1fr]">
        <article className="panel">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Policy Rules</h2>
          {isAdmin ? (
            <div className="mt-3 grid gap-2 sm:grid-cols-4">
              <select value={scope} onChange={(e) => setScope(e.target.value)} className="form-input">
                <option value="domain">Domain</option>
                <option value="folder">Folder</option>
                <option value="tool">Tool</option>
              </select>
              <input className="form-input sm:col-span-2" placeholder="Resource value" value={resource} onChange={(e) => setResource(e.target.value)} />
              <select value={access} onChange={(e) => setAccess(e.target.value)} className="form-input">
                <option value="allow">Allow</option>
                <option value="deny">Deny</option>
              </select>
              <button type="button" className="btn-primary sm:col-span-4" onClick={savePolicy}>
                Save Policy
              </button>
            </div>
          ) : (
            <p className="mt-3 text-sm text-amber-600 dark:text-amber-300">Read-only mode: only admins can change policies.</p>
          )}
          <div className="mt-4 space-y-2">
            {policies.length === 0 ? (
              <EmptyState title="No policies configured" description="Add allow/deny policies for domain, folder, and tool access." />
            ) : (
              policies.map((policy) => (
                <div key={policy.id} className="rounded-lg border p-3 text-sm dark:border-slate-700">
                  <p className="font-semibold text-slate-900 dark:text-slate-100">
                    {policy.scope}: {policy.resource}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    Access: {policy.access} · Confirm: {policy.requires_confirmation ? 'yes' : 'no'}
                  </p>
                </div>
              ))
            )}
          </div>
        </article>

        <article className="panel">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Approval Center</h2>
          <div className="mt-3 flex gap-2">
            <input className="form-input" placeholder="Action target (path/domain/tool)" value={approvalTarget} onChange={(e) => setApprovalTarget(e.target.value)} />
            <button type="button" className="btn-secondary" onClick={requestApproval}>
              Request
            </button>
          </div>
          <div className="mt-4 space-y-2">
            {approvals.length === 0 ? (
              <EmptyState title="No approvals" description="Approval requests will appear here." />
            ) : (
              approvals.map((approval) => (
                <div key={approval.id} className="rounded-lg border p-3 dark:border-slate-700">
                  <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{approval.action_type}</p>
                  <p className="text-xs text-slate-500">{approval.target}</p>
                  <p className="mt-1 text-xs uppercase text-slate-500">{approval.status}</p>
                  {isAdmin && approval.status === 'pending' ? (
                    <div className="mt-2 flex gap-2">
                      <button type="button" className="btn-primary" onClick={() => void decideApproval(approval.id, 'approved').then(loadData)}>
                        Approve
                      </button>
                      <button type="button" className="btn-secondary" onClick={() => void decideApproval(approval.id, 'rejected').then(loadData)}>
                        Reject
                      </button>
                    </div>
                  ) : null}
                </div>
              ))
            )}
          </div>
        </article>
      </section>
    </AppShell>
  )
}
