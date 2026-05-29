import { useEffect, useState } from 'react'
import AppShell from '../components/layout/AppShell'
import EmptyState from '../components/ui/EmptyState'
import { createMemory, fetchMemories } from '../services/platformService'
import type { MemoryItem } from '../types/platform'

export default function MemoryPage() {
  const [memories, setMemories] = useState<MemoryItem[]>([])
  const [memoryType, setMemoryType] = useState('preference')
  const [memoryKey, setMemoryKey] = useState('')
  const [memoryValue, setMemoryValue] = useState('')

  const loadMemories = async () => {
    const response = await fetchMemories()
    setMemories(response.data)
  }

  useEffect(() => {
    void loadMemories()
  }, [])

  const handleCreateMemory = async () => {
    if (!memoryKey.trim() || !memoryValue.trim()) return
    await createMemory({
      memory_type: memoryType,
      key: memoryKey,
      value: memoryValue,
      importance: 0.6,
    })
    setMemoryKey('')
    setMemoryValue('')
    await loadMemories()
  }

  return (
    <AppShell title="AI Memory Center">
      <section className="grid gap-4 xl:grid-cols-[320px_1fr]">
        <article className="panel">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Add Memory</h2>
          <div className="mt-3 space-y-2">
            <select value={memoryType} onChange={(e) => setMemoryType(e.target.value)} className="form-input">
              <option value="preference">Preference</option>
              <option value="workflow">Workflow</option>
              <option value="context">Context</option>
              <option value="tooling">Tooling</option>
            </select>
            <input className="form-input" placeholder="Memory key" value={memoryKey} onChange={(e) => setMemoryKey(e.target.value)} />
            <textarea className="form-input min-h-24" placeholder="Memory value" value={memoryValue} onChange={(e) => setMemoryValue(e.target.value)} />
            <button type="button" className="btn-primary w-full" onClick={handleCreateMemory}>
              Save Memory
            </button>
          </div>
        </article>
        <article className="panel">
          <h2 className="mb-3 text-sm font-semibold text-slate-900 dark:text-slate-100">Stored Memory</h2>
          {memories.length === 0 ? (
            <EmptyState title="No memory entries" description="Create memory items to personalize assistant behavior." />
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {memories.map((memory) => (
                <article key={memory.id} className="rounded-xl border p-3 dark:border-slate-700">
                  <p className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">{memory.memory_type}</p>
                  <h3 className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-100">{memory.key}</h3>
                  <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{memory.value}</p>
                  <p className="mt-2 text-xs text-slate-500">Importance: {(memory.importance * 100).toFixed(0)}%</p>
                </article>
              ))}
            </div>
          )}
        </article>
      </section>
    </AppShell>
  )
}
