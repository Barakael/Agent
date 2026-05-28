import { type FormEvent, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import {
  createConversation,
  fetchConversations,
  fetchMessages,
  sendMessage,
} from '../services/conversationService'

interface Conversation {
  id: number
  title: string | null
  description: string | null
  message_count: number
}

interface Message {
  id: number
  role: string
  content: string
  created_at: string
}

function ChatPage() {
  const { user } = useAuth()
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedConversation, setSelectedConversation] = useState<Conversation | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [newMessage, setNewMessage] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')

  useEffect(() => {
    loadConversations()
  }, [])

  useEffect(() => {
    if (selectedConversation) {
      loadMessages(selectedConversation.id)
    }
  }, [selectedConversation])

  const loadConversations = async () => {
    setLoading(true)
    try {
      const data = await fetchConversations()
      setConversations(data)
      if (data.data.length > 0 && !selectedConversation) {
        setSelectedConversation(data.data[0])
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load conversations')
    } finally {
      setLoading(false)
    }
  }

  const loadMessages = async (conversationId: number) => {
    try {
      const response = await fetchMessages(conversationId)
      setMessages(response)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load messages')
    }
  }

  const handleCreateConversation = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!title.trim()) {
      setError('Conversation title is required.')
      return
    }

    try {
      const response = await createConversation(title, description)
      const conversation = response.data
      setConversations((current) => [conversation, ...current])
      setSelectedConversation(conversation)
      setTitle('')
      setDescription('')
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create conversation')
    }
  }

  const handleSendMessage = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()

    if (!selectedConversation) {
      setError('Select or create a conversation first.')
      return
    }

    if (!newMessage.trim()) {
      return
    }

    try {
      const response = await sendMessage(selectedConversation.id, newMessage)
      setMessages((current) => [...current, response.data.assistant_message, response.data.user_message])
      setNewMessage('')
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to send message')
    }
  }

  return (
    <main className="chat-page">
      <header className="chat-header">
        <div>
          <h1>AI Assistant Chat</h1>
          <p>Welcome back, {user?.name}. Choose a conversation or start a new one.</p>
        </div>
        <Link to="/">Back to dashboard</Link>
      </header>

      <section className="chat-grid">
        <aside className="chat-sidebar">
          <h2>Conversations</h2>
          <div className="conversation-list">
            {loading ? (
              <div>Loading conversations…</div>
            ) : conversations.length === 0 ? (
              <div>No conversations yet.</div>
            ) : (
              conversations.map((conversation) => (
                <button
                  type="button"
                  key={conversation.id}
                  className={conversation.id === selectedConversation?.id ? 'active' : ''}
                  onClick={() => setSelectedConversation(conversation)}
                >
                  {conversation.title || `Conversation ${conversation.id}`}
                </button>
              ))
            )}
          </div>

          <form className="conversation-form" onSubmit={handleCreateConversation}>
            <h3>New conversation</h3>
            <label>
              Title
              <input value={title} onChange={(event) => setTitle(event.target.value)} required />
            </label>
            <label>
              Description
              <textarea value={description} onChange={(event) => setDescription(event.target.value)} />
            </label>
            <button type="submit">Create</button>
          </form>
        </aside>

        <section className="chat-panel">
          <div className="chat-panel-header">
            <h2>{selectedConversation?.title || 'New conversation'}</h2>
            {selectedConversation && <p>{selectedConversation.description}</p>}
          </div>

          <div className="message-feed">
            {messages.map((message) => (
              <div key={message.id} className={`message-bubble ${message.role}`}>
                <span>{message.content}</span>
                <small>{new Date(message.created_at).toLocaleString()}</small>
              </div>
            ))}
          </div>

          {error && <div className="error-message">{error}</div>}

          <form className="compose-form" onSubmit={handleSendMessage}>
            <textarea
              value={newMessage}
              onChange={(event) => setNewMessage(event.target.value)}
              placeholder="Ask the assistant a question..."
              required
            />
            <button type="submit">Send</button>
          </form>
        </section>
      </section>
    </main>
  )
}

export default ChatPage
