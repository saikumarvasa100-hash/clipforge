'use client'
import { useState } from 'react'

const PLANS = [
  {
    name: 'Free',
    price: '$0',
    period: '/month',
    clips: '5',
    features: ['1 platform', 'Basic virality scoring', 'Standard captions', 'Manual publish'],
    highlight: false,
  },
  {
    name: 'Pro',
    price: '$19',
    period: '/month',
    clips: '100',
    features: ['3 platforms', 'Advanced virality scoring', 'Burned-in captions', 'Auto-posting', 'Priority queue'],
    highlight: true,
  },
  {
    name: 'Agency',
    price: '$49',
    period: '/month',
    clips: 'Unlimited',
    features: ['All platforms', 'Custom scoring model', 'Multi-channel', 'Dedicated support', 'API access', 'White-label'],
    highlight: false,
  },
]

export default function PricingTable() {
  const [loading, setLoading] = useState<string | null>(null)

  const handleCheckout = async (plan: string) => {
    setLoading(plan)
    // Call backend to create checkout session
    try {
      const res = await fetch('/api/webhooks/stripe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'checkout', plan: plan.toLowerCase() }),
      })
      const data = await res.json()
      if (data.url) window.location.href = data.url
    } catch (e) {
      console.error('Checkout failed:', e)
    }
    setLoading(null)
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-6 max-w-4xl mx-auto py-12">
      {PLANS.map((plan) => (
        <div
          key={plan.name}
          className={`rounded-xl border-2 p-6 text-center ${
            plan.highlight
              ? 'border-purple-500 bg-purple-50 shadow-lg'
              : 'border-gray-200 bg-white'
          }`}
        >
          {plan.highlight && (
            <span className="text-xs font-semibold bg-purple-600 text-white px-3 py-1 rounded-full">
              Most Popular
            </span>
          )}
          <h3 className="text-lg font-bold mt-3">{plan.name}</h3>
          <div className="mt-2">
            <span className="text-4xl font-extrabold">{plan.price}</span>
            <span className="text-gray-500 ml-1">{plan.period}</span>
          </div>
          <p className="text-sm text-gray-500 mt-1">{plan.clips} clips/month</p>
          <button
            onClick={() => handleCheckout(plan.name)}
            disabled={loading === plan.name}
            className={`mt-6 w-full py-2.5 rounded-lg text-sm font-semibold transition ${
              plan.highlight
                ? 'bg-purple-600 text-white hover:bg-purple-700'
                : 'bg-gray-100 text-gray-800 hover:bg-gray-200'
            } disabled:opacity-50`}
          >
            {loading === plan.name ? 'Redirecting...' : plan.price === '$0' ? 'Get Started' : 'Subscribe'}
          </button>
          <ul className="mt-6 text-sm text-left space-y-2">
            {plan.features.map((f: string) => (
              <li key={f} className="flex items-center gap-2 text-gray-600">
                <span className="text-purple-500">✓</span> {f}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}
