import api from './api'

export async function transcribeAudio(blob: Blob, filename = 'recording.webm'): Promise<string> {
  const form = new FormData()
  form.append('audio', blob, filename)
  const response = await api.post<{ data: { text: string } }>('/voice/transcribe', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return response.data.data.text
}

export async function speakText(text: string): Promise<Blob> {
  const response = await api.post('/voice/speak', { text }, { responseType: 'blob' })
  return response.data as Blob
}

export function playAudioBlob(blob: Blob): void {
  const url = URL.createObjectURL(blob)
  const audio = new Audio(url)
  audio.onended = () => URL.revokeObjectURL(url)
  void audio.play()
}
