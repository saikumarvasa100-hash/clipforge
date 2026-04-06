import { NextRequest, NextResponse } from 'next/server'

export async function GET(req: NextRequest) {
  const hubChallenge = req.nextUrl.searchParams.get('hub.challenge')
  if (hubChallenge) {
    return new NextResponse(hubChallenge, { status: 200, headers: { 'Content-Type': 'text/plain' } })
  }
  return NextResponse.json({ error: 'Missing hub.challenge' }, { status: 400 })
}

export async function POST(req: NextRequest) {
  const body = await req.text()
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'

  // Forward Atom XML to our backend to trigger job
  try {
    await fetch(`${backendUrl}/api/webhooks/youtube`, {
      method: 'POST',
      body,
      headers: { 'Content-Type': 'application/atom+xml' },
    })
  } catch (e) {
    console.error('Failed to forward YouTube webhook:', e)
  }

  return NextResponse.json({ received: true }, { status: 200 })
}
