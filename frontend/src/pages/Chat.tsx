import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Archive, Edit3, Mic, Plus, Search, Trash2, Volume2 } from 'lucide-react'
import AppShell from '../components/layout/AppShell'
import {
  archiveConversation,
  createConversation,
  deleteConversation,
  fetchConversations,
  fetchMessages,
  sendMessage,
  updateConversation,
  type ConversationSummary,
  type MessagePayload,
} from '../services/conversationService'
import { useRealtime } from '../contexts/RealtimeContext'

export default function ChatPage() {
  const { connected, lastMessage } = useRealtime()
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [selectedConversation, setSelectedConversation] = useState<ConversationSummary | null>(null)
  const [messages, setMessages] = useState<MessagePayload[]>([])
  const [newMessage, setNewMessage] = useState('')
  const [conversationQuery, setConversationQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [assistantTyping, setAssistantTyping] = useState(false)
  const [voiceListening, setVoiceListening] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadConversations = async () => {
    setLoading(true)
    try {
      const list = await fetchConversations()
      setConversations(list)
      setSelectedConversation((current) => current ?? list[0] ?? null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load conversations.')
    } finally {
      setLoading(false)
    }
  }

  const loadMessages = async (conversationId: number) => {
    try {
      const response = await fetchMessages(conversationId)
      setMessages(response)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load messages.')
    }
  }

  useEffect(() => {
    void loadConversations()
  }, [])

  useEffect(() => {
    if (selectedConversation) {
      void loadMessages(selectedConversation.id)
    }
  }, [selectedConversation])

  useEffect(() => {
    if (!lastMessage || !selectedConversation) {
      return
    }
    if (lastMessage.channel === 'chat' && Number(lastMessage.payload.conversation_id) === selectedConversation.id) {
      void loadMessages(selectedConversation.id)
      setAssistantTyping(false)
    }
  }, [lastMessage, selectedConversation])

  const filteredConversations = useMemo(
    () =>
      conversations.filter((conversation) =>
        (conversation.title ?? `Conversation ${conversation.id}`).toLowerCase().includes(conversationQuery.toLowerCase()),
      ),
    [conversations, conversationQuery],
  )

  const handleCreateConversation = async () => {
    try {
      const newConversation = await createConversation(`Wayda chat ${new Date().toLocaleTimeString()}`, 'New Wayda thread')
      setConversations((current) => [newConversation, ...current])
      setSelectedConversation(newConversation)
      setMessages([])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create conversation.')
    }
  }

  const handleRenameConversation = async () => {
    if (!selectedConversation) return
    const nextTitle = window.prompt('Rename conversation', selectedConversation.title ?? '')
    if (!nextTitle) return
    try {
      const updated = await updateConversation(selectedConversation.id, { title: nextTitle })
      setConversations((current) => current.map((item) => (item.id === updated.id ? updated : item)))
      setSelectedConversation(updated)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to rename conversation.')
    }
  }

  const handleArchiveConversation = async () => {
    if (!selectedConversation) return
    try {
      await archiveConversation(selectedConversation.id)
      await loadConversations()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to archive conversation.')
    }
  }

  const handleDeleteConversation = async () => {
    if (!selectedConversation) return
    if (!window.confirm('Delete this conversation?')) return
    try {
      await deleteConversation(selectedConversation.id)
      const remaining = conversations.filter((item) => item.id !== selectedConversation.id)
      setConversations(remaining)
      setSelectedConversation(remaining[0] ?? null)
      setMessages([])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to delete conversation.')
    }
  }

  const handleSendMessage = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selectedConversation || !newMessage.trim()) return

    setSending(true)
    setAssistantTyping(true)
    try {
      const response = await sendMessage(selectedConversation.id, newMessage.trim())
      const payload = response.data as { user_message: MessagePayload; assistant_message: MessagePayload }
      setMessages((current) => [...current, payload.user_message, payload.assistant_message])
      setNewMessage('')
      setAssistantTyping(false)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to send message.')
      setAssistantTyping(false)
    } finally {
      setSending(false)
    }
  }

  const startVoiceInput = () => {
    const SpeechRecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SpeechRecognitionCtor) {
      setError('Speech recognition is not supported in this browser.')
      return
    }
    const recognition = new SpeechRecognitionCtor()
    recognition.lang = 'en-US'
    recognition.continuous = false
    recognition.interimResults = false
    recognition.onresult = (event) => {
      const transcript = event.results[0]?.[0]?.transcript
      if (transcript) {
        setNewMessage((current) => `${current} ${transcript}`.trim())
      }
    }
    recognition.onerror = () => setError('Voice input failed. Please try again.')
    recognition.onend = () => setVoiceListening(false)
    setVoiceListening(true)
    recognition.start()
  }

  const readLastAssistantMessage = () => {
    const latestAssistant = [...messages].reverse().find((message) => message.role === 'assistant')
    if (!latestAssistant) return
    const utterance = new SpeechSynthesisUtterance(latestAssistant.content)
    window.speechSynthesis.speak(utterance)
  }

  return (
    <AppShell title="Wayda" fullHeight>
      <section className="wayda-chat-layout">
        <aside className="wayda-thread-pane">
          <div className="wayda-thread-toolbar">
            <button type="button" className="wayda-ghost-button" onClick={handleCreateConversation}>
              <Plus size={15} />
              <span>New</span>
            </button>
            <div className="wayda-inline-actions">
              <button type="button" className="wayda-icon-button" onClick={handleRenameConversation} title="Rename">
                <Edit3 size={14} />
              </button>
              <button type="button" className="wayda-icon-button" onClick={handleArchiveConversation} title="Archive">
                <Archive size={14} />
              </button>
              <button type="button" className="wayda-icon-button" onClick={handleDeleteConversation} title="Delete">
                <Trash2 size={14} />
              </button>
            </div>
          </div>

          <label className="wayda-search">
            <Search size={14} />
            <input
              value={conversationQuery}
              onChange={(event) => setConversationQuery(event.target.value)}
              placeholder="Search threads"
            />
          </label>

          <div className="wayda-thread-list">
            {loading ? <p className="wayda-empty-copy">Loading conversations...</p> : null}
            {!loading && filteredConversations.length === 0 ? <p className="wayda-empty-copy">No conversations found.</p> : null}
            {filteredConversations.map((conversation) => (
              <button
                key={conversation.id}
                type="button"
                className={`wayda-thread-item ${selectedConversation?.id === conversation.id ? 'active' : ''}`}
                onClick={() => setSelectedConversation(conversation)}
              >
                <strong>{conversation.title ?? `Conversation ${conversation.id}`}</strong>
                <span>{conversation.message_count} messages</span>
              </button>
            ))}
          </div>
        </aside>

        <div className="wayda-chat-pane">
          <div className="wayda-messages">
            {messages.length === 0 ? (
              <div className="wayda-empty-state">
                <h2>How can Wayda help?</h2>
                <p>Ask for coding help, planning, debugging, or workflow automation.</p>
              </div>
            ) : (
              messages.map((message) => (
                <article key={message.id} className={`wayda-message-row ${message.role === 'user' ? 'user' : 'assistant'}`}>
                  <div className="wayda-message-inner">
                    {message.role === 'assistant' && message.metadata?.tool_actions?.length ? (
                      <div className="wayda-tool-actions">
                        {message.metadata.tool_actions.map((action, index) => (
                          <span key={`${message.id}-tool-${index}`} className="wayda-tool-badge">
                            {action.tool}.{action.action}
                            {action.output?.result === 'completed' || action.output?.message ? ' ✓' : ''}
                          </span>
                        ))}
                      </div>
                    ) : null}
                    <p>{message.content}</p>
                    <span>{new Date(message.created_at).toLocaleTimeString()}</span>
                  </div>
                </article>
              ))
            )}

            {assistantTyping ? (
              <article className="wayda-message-row assistant">
                <div className="wayda-message-inner typing">
                  <span className="dot" />
                  <span>Wayda is typing...</span>
                </div>
              </article>
            ) : null}
          </div>

          <div className="wayda-composer-wrap">
            {error ? <p className="wayda-error">{error}</p> : null}
            <form onSubmit={handleSendMessage} className="wayda-composer">
              <textarea
                value={newMessage}
                onChange={(event) => setNewMessage(event.target.value)}
                placeholder={selectedConversation ? 'Message Wayda...' : 'Create or select a conversation...'}
                disabled={sending || !selectedConversation}
              />
              <div className="wayda-composer-actions">
                <button type="button" className="wayda-icon-button" onClick={startVoiceInput} title="Voice input">
                  <Mic size={15} className={voiceListening ? 'text-emerald-500' : ''} />
                </button>
                <button type="button" className="wayda-icon-button" onClick={readLastAssistantMessage} title="Read response">
                  <Volume2 size={15} />
                </button>
                <button type="submit" className="btn-primary" disabled={sending || !selectedConversation}>
                  {sending ? 'Sending...' : 'Send'}
                </button>
              </div>
            </form>
            <p className="wayda-disclaimer">{connected ? 'Realtime connected' : 'Realtime offline'} · Responses can be inaccurate.</p>
          </div>
        </div>
      </section>
    </AppShell>
  )
}
