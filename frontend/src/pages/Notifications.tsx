import { useEffect, useState } from 'react'
import AppShell from '../components/layout/AppShell'
import EmptyState from '../components/ui/EmptyState'
import { fetchNotifications, markAllNotificationsRead, markNotificationRead } from '../services/platformService'
import type { UserNotification } from '../types/platform'
import { useRealtime } from '../contexts/RealtimeContext'

export default function NotificationsPage() {
  const { lastMessage } = useRealtime()
  const [notifications, setNotifications] = useState<UserNotification[]>([])
  const [showUnreadOnly, setShowUnreadOnly] = useState(false)

  const loadNotifications = async () => {
    const response = await fetchNotifications(showUnreadOnly)
    setNotifications(response.data)
  }

  useEffect(() => {
    void loadNotifications()
  }, [showUnreadOnly])

  useEffect(() => {
    if (lastMessage?.channel === 'notifications') {
      void loadNotifications()
    }
  }, [lastMessage])

  return (
    <AppShell title="Notifications Center">
      <section className="panel">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <button type="button" className="btn-secondary" onClick={() => setShowUnreadOnly((value) => !value)}>
            {showUnreadOnly ? 'Show All' : 'Show Unread'}
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={() => void markAllNotificationsRead().then(loadNotifications)}
          >
            Mark all as read
          </button>
        </div>
        {notifications.length === 0 ? (
          <EmptyState title="No notifications" description="You are all caught up." />
        ) : (
          <div className="space-y-2">
            {notifications.map((notification) => (
              <article
                key={notification.id}
                className={`rounded-lg border p-4 dark:border-slate-700 ${
                  notification.read_at ? 'bg-white dark:bg-slate-900' : 'bg-brand-50 dark:bg-brand-500/10'
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{notification.title}</h3>
                    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{notification.body ?? 'No details available'}</p>
                  </div>
                  {!notification.read_at ? (
                    <button
                      type="button"
                      className="btn-secondary px-3 py-1 text-xs"
                      onClick={() => void markNotificationRead(notification.id).then(loadNotifications)}
                    >
                      Mark read
                    </button>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </AppShell>
  )
}
