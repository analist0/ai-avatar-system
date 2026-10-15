export interface Avatar {
  id: string
  name: string
  status: 'ready' | 'processing' | 'failed' | 'pending'
  thumbnail_url?: string
  image_url?: string
  s3_key?: string
  voice_id?: string | null
  avatar_metadata?: {
    system_prompt?: string
    personality?: string
    background_color?: string
    animation_style?: string
  }
  created_at?: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  created_at: string
}

export interface SessionSummary {
  id: string
  user_id: string
  avatar_id: string
  status: 'active' | 'paused' | 'ended'
  started_at: string
  ended_at?: string | null
}

export type WsMessageType =
  | 'token'
  | 'transcription'
  | 'message'
  | 'video_chunk_start'
  | 'video_chunk'
  | 'video_chunk_end'
  | 'status'
  | 'error'
  | 'pong'
  | 'tts_fallback'
  | 'interrupted'

// Discriminated union — each WS event has a well-typed payload so the handler
// can rely on field presence without optional-chaining everywhere.
export type WsMessage =
  | { type: 'token'; token: string }
  | { type: 'transcription'; text: string }
  | { type: 'message'; role: 'assistant'; content: string }
  | { type: 'video_chunk_start'; total_chunks: number }
  | { type: 'video_chunk'; chunk_index: number; total_chunks: number; video_url: string; text: string }
  | { type: 'video_chunk_end'; sent_chunks: number }
  | { type: 'status'; message: string; stage?: string }
  | { type: 'error'; message: string }
  | { type: 'pong' }
  | { type: 'tts_fallback'; engine: string; voice_cloned: boolean; message: string }
  | { type: 'interrupted'; message: string }

export interface VoiceApiResponse {
  id: string
  name: string
  language: string
  duration: number
  created_at?: string
}

export interface YoutubeEngine {
  id: string
  role: string
  source: string
  license: string
  taken: string
  left_out: string
  status: 'builtin' | 'missing' | 'refused' | 'not_integrated' | string
}

export interface YoutubeProject {
  id: string
  avatar_id: string
  title: string
  script: string
  language: string
  aspect: 'landscape' | 'portrait' | 'square' | string
  burn_captions: boolean
  status: 'draft' | 'rendering' | 'ready' | 'failed' | string
  progress: number
  error?: string | null
  engine?: string | null
  video_url?: string | null
  srt_url?: string | null
  chapters_url?: string | null
  description_url?: string | null
  project_metadata?: {
    beats?: number
    chapters?: string[]
    estimated_seconds?: number
    duration_seconds?: number
    warnings?: string[]
    voice_cloned?: boolean
    captions_burned?: boolean
  } | null
}

export interface ApiError {
  response?: {
    data?: {
      detail?: string
    }
  }
  message?: string
}
