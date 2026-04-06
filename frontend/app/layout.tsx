import { createServerClient, type CookieOptions } from '@supabase/ssr'
import { cookies } from 'next/headers'
import { Inter } from 'next/font/google'
import Link from 'next/link'
import './globals.css'

const inter = Inter({ subsets: ['latin'] })

export const metadata = {
  title: 'ClipForge — Turn Videos into Viral Clips',
  description: 'Automatically detect viral moments in long videos and publish them.',
}

function getSupabase() {
  const cookieStore = cookies()
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        get(name: string) { return cookieStore.get(name)?.value },
        set(name: string, value: string, options: CookieOptions) {
          try { cookieStore.set(name, value, options) } catch {}
        },
        remove(name: string, options: CookieOptions) {
          try { cookieStore.set(name, '', { ...options, maxAge: 0 }) } catch {}
        },
      },
    }
  )
}

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const supabase = getSupabase()
  const { data: { session } } = await supabase.auth.getSession()

  return (
    <html lang="en">
      <body className={inter.className}>
        <div className="flex min-h-screen bg-gray-50">
          {/* Sidebar */}
          <aside className="w-56 bg-white border-r border-gray-200 p-4 flex flex-col">
            <div className="mb-8">
              <h1 className="text-xl font-bold text-purple-700">ClipForge</h1>
              <p className="text-xs text-gray-500 mt-1">Viral Clip Engine</p>
            </div>
            <nav className="flex-1 space-y-1">
              <NavItem href="/dashboard" label="Dashboard" />
              <NavItem href="/channels" label="Channels" />
              <NavItem href="/clips" label="Clips" />
              <NavItem href="/settings" label="Settings" />
            </nav>
            {session ? (
              <form action="/auth/signout" method="post">
                <button type="submit" className="text-sm text-gray-500 hover:text-gray-700">
                  Sign out
                </button>
              </form>
            ) : (
              <Link href="/login" className="text-sm text-purple-600 hover:underline">
                Sign in
              </Link>
            )}
          </aside>
          {/* Main content */}
          <main className="flex-1 p-6">{children}</main>
        </div>
      </body>
    </html>
  )
}

function NavItem({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="block px-3 py-2 text-sm text-gray-600 hover:bg-gray-100 hover:text-gray-900 rounded-md"
    >
      {label}
    </Link>
  )
}
