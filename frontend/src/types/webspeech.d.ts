interface SpeechRecognition extends EventTarget {
  continuous: boolean
  interimResults: boolean
  lang: string
  onresult: ((event: SpeechRecognitionEvent) => void) | null
  onerror: ((event: Event) => void) | null
  onend: (() => void) | null
  start(): void
  stop(): void
}

interface SpeechRecognitionEvent extends Event {
  results: {
    [index: number]: {
      [index: number]: {
        transcript: string
      }
    }
    length: number
  }
}

interface Window {
  webkitSpeechRecognition?: new () => SpeechRecognition
  SpeechRecognition?: new () => SpeechRecognition
}
