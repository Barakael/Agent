import api from './api'

let audioUnlocked = false
let sharedAudio: HTMLAudioElement | null = null

function getSharedAudio(): HTMLAudioElement {
  if (!sharedAudio) {
    sharedAudio = new Audio()
    sharedAudio.setAttribute('playsinline', 'true')
  }
  return sharedAudio
}

/** Call on first user gesture (mic tap, Send) so Safari allows playback later. */
export async function unlockAudio(): Promise<void> {
  if (audioUnlocked) return
  try {
    const audio = getSharedAudio()
    audio.muted = true
    audio.src =
      'data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA'
    await audio.play()
    audio.pause()
    audio.muted = false
    audio.removeAttribute('src')
    audioUnlocked = true
  } catch {
    // Gesture may still help a later play(); ignore unlock failure.
  }
}

export function isAudioUnlocked(): boolean {
  return audioUnlocked
}

export async function transcribeAudio(blob: Blob, filename = 'recording.webm'): Promise<string> {
  const form = new FormData()
  form.append('audio', blob, filename)
  const response = await api.post<{ data: { text: string } }>('/voice/transcribe', form)
  return response.data.data.text
}

export async function speakText(text: string): Promise<Blob> {
  const response = await api.post('/voice/speak', { text }, { responseType: 'blob' })
  const raw = response.data as Blob
  if (raw.type === 'audio/mpeg' || raw.type === 'audio/mp3') {
    return raw
  }
  return new Blob([raw], { type: 'audio/mpeg' })
}

export class AudioPlaybackError extends Error {
  constructor(message = 'Audio playback blocked') {
    super(message)
    this.name = 'AudioPlaybackError'
  }
}

export async function playAudioBlob(blob: Blob): Promise<void> {
  const url = URL.createObjectURL(blob)
  const audio = getSharedAudio()
  audio.setAttribute('playsinline', 'true')
  audio.src = url
  try {
    await audio.play()
  } catch {
    URL.revokeObjectURL(url)
    throw new AudioPlaybackError()
  }
  audio.onended = () => URL.revokeObjectURL(url)
}

export function speakWithBrowserTts(text: string): void {
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = 'en-US'
  const speak = () => window.speechSynthesis.speak(utterance)
  if (window.speechSynthesis.getVoices().length === 0) {
    window.speechSynthesis.onvoiceschanged = () => {
      window.speechSynthesis.onvoiceschanged = null
      speak()
    }
  } else {
    speak()
  }
}
