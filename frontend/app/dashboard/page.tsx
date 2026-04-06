export default async function DashboardPage() {
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'

  let clips: any[] = []
  try {
    const res = await fetch(`${backendUrl}/api/clips?page_size=20`, {
      next: { revalidate: 60 },
    })
    if (res.ok) {
      const data = await res.json()
      clips = data.clips || []
    }
  } catch (e) {
    console.error('Failed to fetch clips:', e)
  }

  const totalClips = clips.length
  const published = clips.filter((c: any) => c.status === 'published').length
  const avgScore = clips.length
    ? (clips.reduce((s: number, c: any) => s + (c.hook_score || 0), 0) / clips.length).toFixed(1)
    : '—'

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Dashboard</h1>

      {/* Stats bar */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        <StatCard label="Total Clips (Month)" value={totalClips} />
        <StatCard label="Published" value={published} />
        <StatCard label="Avg Hook Score" value={avgScore} />
      </div>

      {/* Clip grid */}
      {clips.length === 0 ? (
        <div className="text-center py-20">
          <p className="text-gray-400 text-lg">No clips yet</p>
          <p className="text-gray-300 text-sm mt-2">Connect a YouTube channel to get started.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {clips.map((clip: any) => (
            <a
              key={clip.id}
              href={`/clips/${clip.id}`}
              className="block bg-white rounded-lg border border-gray-200 p-4 hover:shadow-md transition"
            >
              <div className="aspect-[9/16] bg-gray-100 rounded-md mb-3 flex items-center justify-center text-gray-300">
                <span className="text-sm">Preview</span>
              </div>
              <div className="flex items-center justify-between mb-2">
                <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                  (clip.hook_score || 0) > 7
                    ? 'bg-green-100 text-green-700'
                    : (clip.hook_score || 0) > 4
                    ? 'bg-amber-100 text-amber-700'
                    : 'bg-red-100 text-red-700'
                }`}>
                  Score: {(clip.hook_score || 0).toFixed(1)}
                </span>
                <span className="text-xs text-gray-400">
                  {new Date(clip.created_at).toLocaleDateString()}
                </span>
              </div>
              <p className="text-sm font-medium text-gray-800 truncate">
                {clip.hook_text || 'No hook text'}
              </p>
              <div className="flex gap-2 mt-2">
                <PlatformBadge platform="TikTok" />
                <PlatformBadge platform="Shorts" />
                <PlatformBadge platform="Reels" />
              </div>
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4">
      <p className="text-sm text-gray-500">{label}</p>
      <p className="text-2xl font-bold text-gray-900 mt-1">{value}</p>
    </div>
  )
}

function PlatformBadge({ platform }: { platform: string }) {
  return (
    <span className="text-[10px] px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded">
      {platform}
    </span>
  )
}
