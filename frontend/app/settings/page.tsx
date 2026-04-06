export default function SettingsPage() {
  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Settings</h1>

      <div className="space-y-6">
        {/* Billing */}
        <div className="bg-white border rounded-lg p-6">
          <h2 className="text-lg font-semibold mb-4">Billing</h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-gray-500">Current Plan</p>
              <p className="text-xl font-bold text-gray-900">Free</p>
              <p className="text-xs text-gray-400">5 clips/month</p>
            </div>
            <div>
              <p className="text-sm text-gray-500">Usage</p>
              <div className="w-full bg-gray-200 rounded-full h-2 mt-2">
                <div className="bg-purple-600 h-2 rounded-full" style={{ width: '40%' }}></div>
              </div>
              <p className="text-xs text-gray-400 mt-1">2 / 5 clips used</p>
            </div>
          </div>
          <button className="mt-4 px-4 py-2 bg-purple-600 text-white rounded-md text-sm hover:bg-purple-700">
            Upgrade Plan
          </button>
        </div>

        {/* Connected Accounts */}
        <div className="bg-white border rounded-lg p-6">
          <h2 className="text-lg font-semibold mb-4">Connected Accounts</h2>
          <div className="space-y-3">
            <AccountRow name="YouTube" connected={false} />
            <AccountRow name="TikTok" connected={false} />
            <AccountRow name="Instagram" connected={false} />
          </div>
        </div>

        {/* Preferences */}
        <div className="bg-white border rounded-lg p-6">
          <h2 className="text-lg font-semibold mb-4">Preferences</h2>
          <div className="space-y-3">
            <label className="flex items-center gap-2">
              <input type="checkbox" defaultChecked />
              <span className="text-sm">Auto-process new videos</span>
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" />
              <span className="text-sm">Auto-publish clips</span>
            </label>
          </div>
        </div>
      </div>
    </div>
  )
}

function AccountRow({ name, connected }: { name: string; connected: boolean }) {
  return (
    <div className="flex items-center justify-between py-2 border-b last:border-b-0">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 bg-gray-200 rounded-full flex items-center justify-center text-xs">
          {name[0]}
        </div>
        <span className="text-sm">{name}</span>
      </div>
      {connected ? (
        <span className="text-xs text-green-600">Connected</span>
      ) : (
        <button className="text-xs text-purple-600 hover:underline">Connect</button>
      )}
    </div>
  )
}
