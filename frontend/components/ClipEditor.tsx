'use client'
import { useState, useCallback, useRef, useEffect } from 'react'

interface CaptionChunk {
  text: string
  start: number
  end: number
}

interface ClipEditorProps {
  clip: {
    id: string
    storage_url: string | null
    hook_text: string | null
    hook_score: number | null
    caption_data: CaptionChunk[] | null
    start_time: number
    end_time: number
    duration?: number
  }
  onSave: (data: { trim_start: number; trim_end: number; edited_captions: CaptionChunk[]; style_name: string }) => void
  onClose: () => void
}

const CAPTION_STYLES = [
  { name: 'classic', label: 'Classic', preview: 'white text' },
  { name: 'highlighted', label: 'Highlighted', preview: 'orange bg' },
  { name: 'dark_box', label: 'Dark Box', preview: 'black bg' },
  { name: 'tiktok_style', label: 'TikTok', preview: 'UPPERCASE' },
  { name: 'minimal', label: 'Minimal', preview: 'thin' },
  { name: 'karaoke', label: 'Karaoke', preview: 'gold words' },
]

export default function ClipEditor({ clip, onSave, onClose }: ClipEditorProps) {
  const duration = clip.end_time - clip.start_time
  const [trimStart, setTrimStart] = useState(0)
  const [trimEnd, setTrimEnd] = useState(duration)
  const [styleName, setStyleName] = useState('classic')
  const [captions, setCaptions] = useState<CaptionChunk[]>(clip.caption_data || [])
  const [saving, setSaving] = useState(false)
  const videoRef = useRef<HTMLVideoElement>(null)
  const [isDragging, setIsDragging] = useState<'left' | 'right' | null>(null)
  const timelineRef = useRef<HTMLDivElement>(null)

  const selectedDuration = trimEnd - trimStart

  const handleTimelineMouseDown = (side: 'left' | 'right') => {
    setIsDragging(side)
  }

  useEffect(() => {
    if (!isDragging) return
    const handleMouseMove = (e: MouseEvent) => {
      if (!timelineRef.current) return
      const rect = timelineRef.current.getBoundingClientRect()
      const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
      const time = pct * duration
      if (isDragging === 'left') {
        setTrimStart(Math.min(time, trimEnd - 0.5))
      } else {
        setTrimEnd(Math.max(time, trimStart + 0.5))
      }
    }
    const handleMouseUp = () => setIsDragging(null)
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isDragging, duration, trimEnd, trimStart])

  const updateCaption = (idx: number, text: string) => {
    setCaptions(prev => prev.map((c, i) => i === idx ? { ...c, text } : c))
  }

  const handleSave = async () => {
    setSaving(true)
    onSave({
      trim_start: trimStart,
      trim_end: trimEnd,
      edited_captions: captions,
      style_name: styleName,
    })
    setSaving(false)
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b">
          <h2 className="text-lg font-bold">Edit Clip</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">&times;</button>
        </div>

        {/* Video Player */}
        <div className="p-4">
          <div className="relative bg-black rounded-lg overflow-hidden aspect-[9/16] max-h-64 mx-auto w-36">
            <video
              ref={videoRef}
              src={clip.storage_url || ''}
              className="w-full h-full object-contain"
              controls
            />
          </div>

          {/* Timeline with Trim Handles */}
          <div className="mt-4">
            <div className="flex justify-between text-xs text-gray-400 mb-1">
              <span>{trimStart.toFixed(1)}s</span>
              <span className="text-purple-600 font-bold">{selectedDuration.toFixed(1)}s</span>
              <span>{trimEnd.toFixed(1)}s</span>
            </div>
            <div
              ref={timelineRef}
              className="relative h-8 bg-gray-200 rounded-full cursor-pointer"
              onMouseDown={(e) => {
                const rect = timelineRef.current!.getBoundingClientRect()
                const pct = (e.clientX - rect.left) / rect.width
                if (pct < 0.5) handleTimelineMouseDown('left')
                else handleTimelineMouseDown('right')
              }}
            >
              {/* Selected region */}
              <div
                className="absolute top-0 bottom-0 bg-purple-200 rounded-full"
                style={{
                  left: `${(trimStart / duration) * 100}%`,
                  width: `${((trimEnd - trimStart) / duration) * 100}%`,
                }}
              />
              {/* Left handle */}
              <div
                className="absolute top-0 bottom-0 w-3 bg-purple-600 rounded-full cursor-ew-resize"
                style={{ left: `${(trimStart / duration) * 100}%` }}
                onMouseDown={() => handleTimelineMouseDown('left')}
              />
              {/* Right handle */}
              <div
                className="absolute top-0 bottom-0 w-3 bg-purple-600 rounded-full cursor-ew-resize"
                style={{ left: `${(trimEnd / duration) * 100}%` }}
                onMouseDown={() => handleTimelineMouseDown('right')}
              />
            </div>
          </div>

          {/* Caption Style Selector */}
          <div className="mt-4">
            <p className="text-sm font-medium text-gray-700 mb-2">Caption Style</p>
            <div className="grid grid-cols-3 gap-2">
              {CAPTION_STYLES.map(s => (
                <button
                  key={s.name}
                  onClick={() => setStyleName(s.name)}
                  className={`p-2 text-xs rounded-lg border-2 transition ${
                    styleName === s.name
                      ? 'border-purple-500 bg-purple-50 text-purple-700'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <div className="font-medium">{s.label}</div>
                  <div className="text-gray-400">{s.preview}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Caption Editor */}
          {captions.length > 0 && (
            <div className="mt-4">
              <p className="text-sm font-medium text-gray-700 mb-2">Captions (editable)</p>
              <div className="space-y-2 max-h-40 overflow-y-auto">
                {captions.map((cap, idx) => (
                  <div key={idx} className="flex items-center gap-2">
                    <span className="text-xs text-gray-400 w-16 flex-shrink-0">
                      {cap.start.toFixed(1)}s
                    </span>
                    <input
                      value={cap.text}
                      onChange={(e) => updateCaption(idx, e.target.value)}
                      className="flex-1 text-sm border rounded px-2 py-1"
                      placeholder="Edit caption text..."
                    />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Save Button */}
          <div className="mt-6 flex gap-3">
            <button
              onClick={onClose}
              className="flex-1 px-4 py-2 border rounded-lg text-gray-700 hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex-1 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50"
            >
              {saving ? 'Re-rendering...' : 'Save & Re-render'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
