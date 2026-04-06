import { NextRequest, NextResponse } from 'next/server'
import Stripe from 'stripe'
import { createClient } from '@supabase/supabase-js'

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, { apiVersion: '2024-12-18.acacia' })
const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_KEY!
)

export async function POST(req: NextRequest) {
  const body = await req.text()
  const signature = req.headers.get('stripe-signature')!

  let event: Stripe.Event
  try {
    event = stripe.webhooks.constructEvent(body, signature, process.env.STRIPE_WEBHOOK_SECRET!)
  } catch {
    return NextResponse.json({ error: 'Invalid signature' }, { status: 400 })
  }

  const data = event.data.object as Stripe.Checkout.Session | Stripe.Subscription

  if (event.type === 'checkout.session.completed') {
    const session = data as Stripe.Checkout.Session
    await supabase
      .from('users')
      .update({ plan: session.metadata?.plan || 'pro' })
      .eq('stripe_customer_id', session.customer)
  }

  if (event.type === 'customer.subscription.updated' || event.type === 'customer.subscription.deleted') {
    const sub = data as Stripe.Subscription
    await supabase
      .from('users')
      .update({ plan: sub.metadata?.plan || 'free' })
      .eq('stripe_customer_id', sub.customer)
  }

  return NextResponse.json({ received: true })
}
