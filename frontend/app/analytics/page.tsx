export default async function AnalyticsPage() {
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'

  let channelData = null
  try {
    const res = await fetch(`${backendUrl}/api/channels`, { next: { revalidate: 60 } })
    if (res.ok) {
      const data = await res.json()
      if (data.channels?.length > 0) {
        const ch = data.channels[0]
        const insp = await fetch(`${backendUrl}/api/analysis/channel/${ch.id}/insights`, {
          next: { revalidate: 300 },
        })
        if (insp.ok) channelData = await insp.json()
      }
    }
  } catch (e) { console.error('Analytics error:', e) }

  if (!channelData) {
    return (
      <div>
        <h1 className="text-2xl font-bold text-gray-900 mb-6">Channel Analytics</h1>
        <p className="text-gray-500">No analytics data available yet.</p>
      </div>
    )
  }

  const pct = (n: number) => ((n / channelData.total_clips) * 100).toFixed(0)

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Channel Analytics</h1>
      <div className="grid grid-cols-3 gap-4 mb-8">
        <StatCard label="Total Clips" value={channelData.total_clips} />
        <StatCard label="Avg Score" value={channelData.avg_hook_score} />
        <StatCard label="Published" value={channelData.published} />
      </div>

      {channelData.score_trend?.length > 0 && (
        <div className="bg-white border rounded-lg p-6 mb-6">
          <h2 className="text-lg font-semibold mb-4">Score Trend (30 Days)</h2>
          <div className="flex items-end gap-1 h-32">
            {channelData.score_trend.map((p: any, i: number) => (
              <div key={i} className="flex-1 flex flex-col items-end justify-end h-full">
                <div className="w-full bg-purple-500 rounded-t" style={{ height: `${(p.score / 10) * 100}%` }} />
                <span className="text-[8px] text-gray-400 mt-1">{p.date?.slice(5)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {channelData.hook_type_distribution && Object.keys(channelData.hook_type_distribution).length > 0 && (
        <div className="bg-white border rounded-lg p-6 mb-6">
          <h2 className="text-lg font-semibold mb-4">Hook Type Distribution</h2>
          <div className="space-y-3">
            {Object.entries(channelData.hook_type_distribution).map(([type, count]) => (
              <div key={type}>
                <div className="flex justify-between text-sm mb-1">
                  <span className="capitalize">{type}</span>
                  <span className="text-gray-500">{count} ({pct(Number(count))}%)</span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-2">
                  <div className="bg-purple-500 h-2 rounded-full" style={{ width: `${pct(Number(count))}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {channelData.top_clips?.length > 0 && (
        <div className="bg-white border rounded-lg p-6">
          <h2 className="text-lg font-semibold mb-4">Top 3 Clips</h2>
          <div className="space-y-3">
            {channelData.top_clips.map((c: any, i: number) => (
              <div key={i} className="flex items-center gap-4 p-3 bg-gray-50 rounded-lg">
                <div className="text-2xl font-bold text-purple-600">#{i + 1}</div>
                <div className="flex-1">
                  <p className="text-sm font-medium text-gray-800 truncate">{c.hook_text}</p>
                  <p className="text-xs text-gray-400">{c.created_at?.slice(0, 10)}</p>
                </div>
                <div className={`text-xl font-bold ${c.hook_score > 7 ? 'text-green-500' : 'text-amber-500'}`}>
                  {c.hook_score}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-white border rounded-lg p-4">
      <p className="text-sm text-gray-500">{label}</p>
      <p className="text-2xl font-bold text-gray-900 mt-1">{value}</p>
    </div>
  )
}
