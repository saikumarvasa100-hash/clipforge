'use client'
import { useState } from 'react'

interface AnalysisPanelProps {
  clipId: string
  onClose: () => void
}

// Mock data — will be replaced by API call
const MOCK_ANALYSIS = {
  overall_score: 8.2,
  llm_hook_score: 8.5,
  audio_energy_score: 7.8,
  hook_phrase_score: 9.0,
  signal_weights: { llm: 0.5, audio: 0.3, phrases: 0.2 },
  hook_type: 'controversy',
  why_viral: 'Opens with a bold counterintuitive claim in first 3 seconds',
  hook_phrases_found: ['nobody talks about this', "here's the truth"],
  audio_peaks: [
    { time: 2.3, energy: 0.45 }, { time: 5.1, energy: 0.72 },
    { time: 8.7, energy: 0.87 }, { time: 12.3, energy: 0.65 },
    { time: 15.0, energy: 0.91 }, { time: 18.2, energy: 0.55 },
  ],
  estimated_reach: 'high' as const,
  platform_fit: { tiktok: 9.1, shorts: 8.3, reels: 7.9 },
}

export default function AnalysisPanel({ clipId, onClose }: AnalysisPanelProps) {
  const [data] = useState(MOCK_ANALYSIS)
  const score = data.overall_score

  const scoreColor = score > 7 ? 'text-green-500' : score > 4 ? 'text-amber-500' : 'text-red-500'
  const scoreBg = score > 7 ? '#22c55e' : score > 4 ? '#f59e0b' : '#ef4444'

  const circumference = 2 * Math.PI * 54
  const offset = circumference - (score / 10) * circumference

  return (
    <div className="fixed inset-y-0 right-0 w-96 bg-white shadow-2xl z-50 overflow-y-auto">
      <div className="p-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-bold text-gray-900">AI Analysis</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">&times;</button>
        </div>

        {/* Score Gauge */}
        <div className="flex justify-center mb-6">
          <div className="relative">
            <svg width="140" height="140" viewBox="0 0 140 140">
              <circle cx="70" cy="70" r="54" fill="none" stroke="#e5e7eb" strokeWidth="8" />
              <circle
                cx="70" cy="70" r="54" fill="none"
                stroke={scoreBg} strokeWidth="8"
                strokeLinecap="round"
                strokeDasharray={circumference}
                strokeDashoffset={offset}
                transform="rotate(-90 70 70)"
                className="transition-all duration-700"
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className={`text-3xl font-bold ${scoreColor}`}>{score}</span>
              <span className="text-xs text-gray-500">/ 10</span>
            </div>
          </div>
        </div>

        {/* Signal Bars */}
        <div className="space-y-3 mb-6">
          <SignalBar label="LLM Hook Score" value={data.llm_hook_score} max={10} color="bg-blue-500" />
          <SignalBar label="Audio Energy" value={data.audio_energy_score} max={10} color="bg-purple-500" />
          <SignalBar label="Hook Phrases" value={data.hook_phrase_score} max={10} color="bg-green-500" />
        </div>

        {/* Why Viral */}
        <div className="bg-purple-50 rounded-lg p-4 mb-6">
          <h3 className="text-sm font-semibold text-purple-700 mb-1">Why this clip will perform</h3>
          <p className="text-sm text-purple-800">{data.why_viral}</p>
        </div>

        {/* Hook Phrases */}
        <div className="mb-6">
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Viral phrases detected</h3>
          <div className="flex flex-wrap gap-2">
            {data.hook_phrases_found.map((phrase, i) => (
              <span key={i} className="px-2 py-1 bg-amber-100 text-amber-800 rounded-full text-xs font-medium">
                &ldquo;{phrase}&rdquo;
              </span>
            ))}
          </div>
        </div>

        {/* Audio Energy Timeline */}
        <div className="mb-6">
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Audio energy timeline</h3>
          <div className="bg-gray-50 rounded-lg p-3">
            <div className="flex items-end gap-1 h-20">
              {data.audio_peaks.map((peak, i) => (
                <div key={i} className="flex-1 flex flex-col items-center justify-end h-full">
                  <div
                    className="w-full bg-purple-400 rounded-t transition-all"
                    style={{ height: `${peak.energy * 100}%` }}
                  />
                  <span className="text-[8px] text-gray-400 mt-1">{peak.time}s</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Platform Fit */}
        <div className="mb-6">
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Platform fit</h3>
          <div className="grid grid-cols-3 gap-3">
            <PlatformBadge name="TikTok" score={data.platform_fit.tiktok} />
            <PlatformBadge name="Shorts" score={data.platform_fit.shorts} />
            <PlatformBadge name="Reels" score={data.platform_fit.reels} />
          </div>
        </div>

        {/* Hook Type */}
        <div className="mb-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Hook type</h3>
          <span className="px-3 py-1.5 bg-indigo-100 text-indigo-700 rounded-full text-sm font-medium capitalize">
            {data.hook_type}
          </span>
        </div>
      </div>
    </div>
  )
}

function SignalBar({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  const pct = Math.min(100, (value / max) * 100)
  return (
    <div>
      <div className="flex justify-between text-xs text-gray-500 mb-1">
        <span>{label}</span>
        <span>{value.toFixed(1)} / {max}</span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-1.5">
        <div className={`${color} h-1.5 rounded-full transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function PlatformBadge({ name, score }: { name: string; score: number }) {
  const color = score > 8 ? 'bg-green-100 text-green-700' : score > 6 ? 'bg-amber-100 text-amber-700' : 'bg-red-100 text-red-700'
  return (
    <div className={`rounded-lg p-3 text-center ${color}`}>
      <div className="text-lg font-bold">{score}</div>
      <div className="text-xs">{name}</div>
    </div>
  )
}
