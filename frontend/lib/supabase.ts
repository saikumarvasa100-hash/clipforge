import { createBrowserClient, createServerClient, type CookieOptions } from '@supabase/ssr'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'

export function createClient() {
  return createBrowserClient(supabaseUrl, supabaseAnonKey)
}

export function createServerClient(cookies: {
  get: (name: string) => string | undefined
  set: (name: string, value: string, options: CookieOptions) => void
  remove: (name: string, options: CookieOptions) => void
}) {
  return createServerClient(supabaseUrl, supabaseAnonKey, {
    cookies: {
      get(name) { return cookies.get(name) },
      set(name, value, options) { cookies.set(name, value, options) },
      remove(name, options) { cookies.remove(name, options) },
    },
  })
}

export { backendUrl }
