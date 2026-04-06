export default async function ClipDetailPage({ params }: { params: { id: string } }) {
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'

  const res = await fetch(`${backendUrl}/api/clips/${params.id}`, {
    next: { revalidate: 60 },
  })

  if (!res.ok) {
    return <div className="p-6 text-red-500">Clip not found</div>
  }

  const clip = await res.json()

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold mb-4">Clip Details</h1>
      <div className="bg-white rounded-lg border p-6 space-y-4">
        <div><span className="text-gray-500">Hook Score:</span> <span className="font-bold">{clip.hook_score?.toFixed(1)}</span>/10</div>
        <div><span className="text-gray-500">Hook Text:</span> <p className="text-gray-800">{clip.hook_text}</p></div>
        <div><span className="text-gray-500">Status:</span> <span className={`px-2 py-0.5 rounded text-xs ${clip.status === 'ready' ? 'bg-green-100 text-green-700' : 'bg-gray-100'}`}>{clip.status}</span></div>
        <div><span className="text-gray-500">Time:</span> {clip.start_time.toFixed(1)}s → {clip.end_time.toFixed(1)}s</div>
        {clip.storage_url && (
          <a href={`/api/clips/${clip.id}/download`} className="text-blue-600 underline">Download</a>
        )}
        {clip.virality_signals && (
          <pre className="text-xs bg-gray-50 p-3 rounded overflow-auto">{JSON.stringify(clip.virality_signals, null, 2)}</pre>
        )}
      </div>
    </div>
  )
}
