import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'

export default function SectionCard({
  title,
  icon: Icon,
  action,
  children,
  className = '',
}: {
  title: string
  icon?: LucideIcon
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`section-card fade-in ${className}`}>
      <div className="section-card-head">
        <h2>
          {Icon ? <Icon size={16} className="accent-icon" /> : null}
          {title}
        </h2>
        {action ?? null}
      </div>
      <div className="section-card-body">{children}</div>
    </section>
  )
}
