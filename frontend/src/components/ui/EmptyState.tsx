export default function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div className="panel text-center">
      <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">{title}</h3>
      <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">{description}</p>
    </div>
  )
}
