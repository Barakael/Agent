import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Archive, Edit3, Mic, Plus, Search, Trash2, Volume2 } from 'lucide-react'
import AppShell from '../components/layout/AppShell'
import { isMessagingMobile } from '../config/messaging'
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
import { fetchRunnerStatus, type RunnerStatus } from '../services/platformService'
import { playAudioBlob, speakText, transcribeAudio } from '../services/voiceService'
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
  const [voiceRecording, setVoiceRecording] = useState(false)
  const [voiceTranscribing, setVoiceTranscribing] = useState(false)
  const [autoReadReplies, setAutoReadReplies] = useState(isMessagingMobile)
  const [runnerStatus, setRunnerStatus] = useState<RunnerStatus | null>(null)
  const [voiceHint, setVoiceHint] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const recognitionRef = useRef<SpeechRecognition | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const recordChunksRef = useRef<Blob[]>([])

  const scrollToBottom = (behavior: ScrollBehavior = 'smooth') => {
    messagesEndRef.current?.scrollIntoView({ behavior, block: 'end' })
  }

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

  useEffect(() => {
    const behavior: ScrollBehavior =
      messages.length > 0 && messagesEndRef.current ? 'smooth' : 'instant'
    scrollToBottom(behavior)
  }, [messages, assistantTyping])

  useEffect(() => {
    scrollToBottom('instant')
  }, [selectedConversation?.id])

  useEffect(() => {
    return () => {
      recognitionRef.current?.stop()
      mediaRecorderRef.current?.stop()
    }
  }, [])

  useEffect(() => {
    const loadRunner = async () => {
      try {
        const status = await fetchRunnerStatus()
        setRunnerStatus(status)
      } catch {
        setRunnerStatus({ runner_enabled: false, online: false, platform: null })
      }
    }
    void loadRunner()
    const interval = window.setInterval(() => void loadRunner(), 30000)
    return () => window.clearInterval(interval)
  }, [])

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

  const speakAssistantText = async (text: string) => {
    try {
      const blob = await speakText(text)
      playAudioBlob(blob)
    } catch {
      const utterance = new SpeechSynthesisUtterance(text)
      window.speechSynthesis.speak(utterance)
    }
  }

  const submitMessage = async (text: string) => {
    if (!selectedConversation || !text.trim()) return

    setSending(true)
    setAssistantTyping(true)
    try {
      const response = await sendMessage(selectedConversation.id, text.trim())
      const payload = response.data as { user_message: MessagePayload; assistant_message: MessagePayload }
      setMessages((current) => [...current, payload.user_message, payload.assistant_message])
      setNewMessage('')
      setAssistantTyping(false)
      setError(null)
      if (autoReadReplies && payload.assistant_message.content) {
        void speakAssistantText(payload.assistant_message.content)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to send message.')
      setAssistantTyping(false)
    } finally {
      setSending(false)
    }
  }

  const handleSendMessage = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selectedConversation || !newMessage.trim()) return
    await submitMessage(newMessage.trim())
  }

  const handleComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey) {
      return
    }
    event.preventDefault()
    if (sending || !selectedConversation || !newMessage.trim()) {
      return
    }
    event.currentTarget.form?.requestSubmit()
  }

  const stopServerRecording = async () => {
    const recorder = mediaRecorderRef.current
    if (!recorder || recorder.state === 'inactive') {
      return
    }
    setVoiceRecording(false)
    setVoiceTranscribing(true)
    setVoiceHint('Transcribing…')

    await new Promise<void>((resolve) => {
      recorder.onstop = () => resolve()
      recorder.stop()
    })

    try {
      const mime = recorder.mimeType || 'audio/webm'
      const blob = new Blob(recordChunksRef.current, { type: mime })
      recordChunksRef.current = []
      if (blob.size < 100) {
        setVoiceHint('Recording too short. Hold mic and speak.')
        return
      }
      const ext = mime.includes('mp4') ? 'recording.m4a' : 'recording.webm'
      const text = await transcribeAudio(blob, ext)
      setNewMessage(text)
      if (selectedConversation) {
        await submitMessage(text)
      }
      setVoiceHint(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Voice transcription failed.')
      setVoiceHint(null)
    } finally {
      setVoiceTranscribing(false)
      mediaRecorderRef.current = null
    }
  }

  const startServerRecording = async () => {
    if (voiceRecording || voiceTranscribing || sending) return
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mime = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/mp4'
      const recorder = new MediaRecorder(stream, { mimeType: mime })
      recordChunksRef.current = []
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          recordChunksRef.current.push(event.data)
        }
      }
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop())
      }
      mediaRecorderRef.current = recorder
      recorder.start()
      setVoiceRecording(true)
      setVoiceHint('Recording… release to send')
      setError(null)
    } catch {
      setError('Microphone access denied or unavailable.')
    }
  }

  const toggleVoiceInput = () => {
    if (typeof MediaRecorder !== 'undefined' && typeof navigator.mediaDevices?.getUserMedia === 'function') {
      if (voiceRecording) {
        void stopServerRecording()
      } else {
        void startServerRecording()
      }
      return
    }
    if (voiceListening && recognitionRef.current) {
      recognitionRef.current.stop()
      setVoiceListening(false)
      setVoiceHint(null)
      return
    }

    const SpeechRecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SpeechRecognitionCtor) {
      setError('Voice input requires Chrome or Edge. Safari/Firefox are not supported.')
      return
    }

    const recognition = new SpeechRecognitionCtor()
    recognitionRef.current = recognition
    recognition.lang = 'en-US'
    recognition.continuous = false
    recognition.interimResults = true
    recognition.onresult = (event) => {
      let transcript = ''
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        transcript += event.results[index][0]?.transcript ?? ''
      }
      setNewMessage(transcript.trim())
      if (event.results[event.results.length - 1]?.isFinal) {
        setVoiceHint('Voice captured. Press Enter or Send to submit.')
      }
    }
    recognition.onerror = (event) => {
      if (event.error === 'not-allowed') {
        setError('Microphone blocked. Allow mic access for this site in your browser settings.')
      } else if (event.error === 'no-speech') {
        setVoiceHint('No speech detected. Try again.')
      } else {
        setError(`Voice input failed: ${event.error}`)
      }
      setVoiceListening(false)
    }
    recognition.onend = () => {
      setVoiceListening(false)
      recognitionRef.current = null
    }
    setError(null)
    setVoiceHint('Listening… speak now')
    setVoiceListening(true)
    recognition.start()
  }

  const readLastAssistantMessage = () => {
    const latestAssistant = [...messages].reverse().find((message) => message.role === 'assistant')
    if (!latestAssistant) return
    void speakAssistantText(latestAssistant.content)
  }

  const runnerLabel = runnerStatus
    ? runnerStatus.online
      ? `PC online${runnerStatus.platform ? ` (${runnerStatus.platform})` : ''}`
      : runnerStatus.runner_enabled
        ? 'PC offline'
        : 'Runner disabled'
    : 'Checking PC…'

  return (
    <AppShell title="Wayda" fullHeight>
      <section className={`wayda-chat-layout ${isMessagingMobile ? 'wayda-messaging-mobile' : ''}`}>
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
          <div className="wayda-chat-pane-head">
            <span
              className={`wayda-runner-badge ${runnerStatus?.online ? 'online' : 'offline'}`}
              title={runnerLabel}
            >
              {runnerLabel}
            </span>
          </div>
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
                            {['completed', 'playing', 'searched', 'navigated', 'sent'].includes(String(action.output?.result)) ||
                            action.output?.message
                              ? ' ✓'
                              : ''}
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
            <div ref={messagesEndRef} aria-hidden="true" />
          </div>

          <div className="wayda-composer-wrap">
            {error ? <p className="wayda-error">{error}</p> : null}
            {voiceRecording ? <p className="wayda-voice-status">Recording… release mic to send</p> : null}
            {voiceTranscribing ? <p className="wayda-voice-status">Transcribing…</p> : null}
            {voiceListening ? <p className="wayda-voice-status">Listening… speak now (click mic to stop)</p> : null}
            {!voiceRecording && !voiceTranscribing && !voiceListening && voiceHint ? (
              <p className="wayda-voice-status">{voiceHint}</p>
            ) : null}
            <form onSubmit={handleSendMessage} className="wayda-composer">
              <textarea
                value={newMessage}
                onChange={(event) => setNewMessage(event.target.value)}
                onKeyDown={handleComposerKeyDown}
                placeholder={selectedConversation ? 'Message Wayda...' : 'Create or select a conversation...'}
                disabled={sending || !selectedConversation || voiceTranscribing}
              />
              <div className="wayda-composer-actions">
                <button
                  type="button"
                  className={`wayda-icon-button wayda-mic-button ${voiceRecording || voiceListening ? 'wayda-icon-button-active' : ''}`}
                  onClick={toggleVoiceInput}
                  onPointerDown={(event) => {
                    if (event.pointerType === 'touch' && !voiceRecording) {
                      event.preventDefault()
                      void startServerRecording()
                    }
                  }}
                  onPointerUp={(event) => {
                    if (event.pointerType === 'touch' && voiceRecording) {
                      event.preventDefault()
                      void stopServerRecording()
                    }
                  }}
                  disabled={voiceTranscribing || sending}
                  title={voiceRecording ? 'Stop recording' : 'Hold to talk (tap on phone)'}
                >
                  <Mic size={18} className={voiceRecording || voiceListening ? 'text-emerald-400' : ''} />
                </button>
                <button
                  type="button"
                  className={`wayda-icon-button ${autoReadReplies ? 'wayda-icon-button-active' : ''}`}
                  onClick={() => setAutoReadReplies((current) => !current)}
                  onDoubleClick={readLastAssistantMessage}
                  title={autoReadReplies ? 'Auto-read on (double-click to read now)' : 'Auto-read off (double-click to read now)'}
                >
                  <Volume2 size={18} />
                </button>
                <button type="submit" className="btn-primary wayda-send-button" disabled={sending || !selectedConversation || voiceTranscribing}>
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
