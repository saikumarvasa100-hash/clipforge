import { loadStripe } from '@stripe/stripe-js'

const stripePromise = loadStripe(process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY!)

export async function createCheckoutSession(plan: string) {
  const res = await fetch('/api/webhooks/stripe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'checkout', plan }),
  })
  const data = await res.json()
  if (data.url) {
    window.location.href = data.url
  }
  return data
}

export { stripePromise }
