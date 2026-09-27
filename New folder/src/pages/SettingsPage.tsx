import { useState } from 'react'
import toast from 'react-hot-toast'
import { Bell, KeyRound, Laptop, Lock, LogOut, Smartphone, User as UserIcon, Wallet } from 'lucide-react'
import { PageWrapper } from '@/components/layout/PageWrapper'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Toggle } from '@/components/ui/Toggle'
import { PasswordStrengthMeter } from '@/components/ui/PasswordStrengthMeter'
import { cn, CURRENCY_META, formatCost, type Currency } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'
import { useSettingsStore } from '@/store/settingsStore'
import { useBudget, useSetBudget } from '@/hooks/useCost'

type Tab = 'profile' | 'security' | 'budget' | 'notifications'

const TABS: Array<{ key: Tab; label: string; icon: typeof UserIcon }> = [
  { key: 'profile', label: 'Profile', icon: UserIcon },
  { key: 'security', label: 'Security', icon: KeyRound },
  { key: 'budget', label: 'Budget & Limits', icon: Wallet },
  { key: 'notifications', label: 'Notifications', icon: Bell },
]

interface Session {
  id: string
  device: string
  location: string
  lastActive: string
  current?: boolean
}

const INITIAL_SESSIONS: Session[] = [
  { id: 's1', device: 'MacBook Pro · Chrome', location: 'Bengaluru, IN', lastActive: 'Now', current: true },
  { id: 's2', device: 'iPhone 15 · Safari', location: 'Bengaluru, IN', lastActive: '2 hours ago' },
  { id: 's3', device: 'Windows · Edge', location: 'Mumbai, IN', lastActive: '3 days ago' },
]

export function SettingsPage() {
  const [tab, setTab] = useState<Tab>('profile')
  const user = useAuthStore((s) => s.user)
  const settings = useSettingsStore()
  const { data: budget } = useBudget()
  const setBudget = useSetBudget()

  // Profile
  const [fullName, setFullName] = useState(user?.full_name ?? '')
  const [savingProfile, setSavingProfile] = useState(false)

  // Security
  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [sessions, setSessions] = useState(INITIAL_SESSIONS)

  // Budget
  const currency = settings.currency
  const rate = CURRENCY_META[currency].rate
  const [budgetInput, setBudgetInput] = useState(budget ? (budget.monthly_budget_usd * rate).toFixed(2) : '')
  const [savingBudget, setSavingBudget] = useState(false)

  const saveProfile = () => {
    setSavingProfile(true)
    window.setTimeout(() => {
      useAuthStore.getState().setUser({ ...user!, full_name: fullName.trim() || null })
      setSavingProfile(false)
      toast.success('Profile saved')
    }, 500)
  }

  const updatePassword = () => {
    if (newPw.length < 8) return toast.error('New password must be at least 8 characters')
    if (newPw !== confirmPw) return toast.error('Passwords do not match')
    if (currentPw.length === 0) return toast.error('Enter your current password')
    toast.success('Password updated')
    setCurrentPw('')
    setNewPw('')
    setConfirmPw('')
  }

  const saveBudget = () => {
    const v = parseFloat(budgetInput)
    if (Number.isNaN(v) || v <= 0) return toast.error('Enter a valid budget')
    const usd = Math.round((v / rate) * 100) / 100
    setSavingBudget(true)
    settings.setMonthlyBudget(usd)
    setBudget.mutate(usd, {
      onSettled: () => setSavingBudget(false),
    })
  }

  return (
    <PageWrapper maxWidth="max-w-5xl">
      <div className="grid gap-4 md:grid-cols-[220px_1fr]">
        {/* Tab nav */}
        <div className="flex gap-1 overflow-x-auto md:flex-col md:overflow-visible">
          {TABS.map((t) => {
            const Icon = t.icon
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={cn(
                  'flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                  tab === t.key ? 'bg-brand/15 text-brand-light' : 'text-text-secondary hover:bg-elevated hover:text-text-primary',
                )}
              >
                <Icon className="h-4 w-4" />
                {t.label}
              </button>
            )
          })}
        </div>

        {/* Content */}
        <div className="min-w-0">
          {tab === 'profile' && (
            <Card title="Profile">
              <div className="space-y-4">
                <Input label="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Your name" />
                <Input label="Email" value={user?.email ?? ''} readOnly hint="Contact support to change your email." />
                <div className="flex justify-end">
                  <Button loading={savingProfile} onClick={saveProfile}>
                    Save Profile
                  </Button>
                </div>
              </div>
            </Card>
          )}

          {tab === 'security' && (
            <div className="space-y-4">
              <Card title="Change Password">
                <div className="space-y-4">
                  <Input type="password" label="Current password" value={currentPw} onChange={(e) => setCurrentPw(e.target.value)} placeholder="••••••••" />
                  <Input type="password" label="New password" value={newPw} onChange={(e) => setNewPw(e.target.value)} placeholder="At least 8 characters" />
                  <PasswordStrengthMeter password={newPw} />
                  <Input type="password" label="Confirm new password" value={confirmPw} onChange={(e) => setConfirmPw(e.target.value)} placeholder="Repeat new password" />
                  <div className="flex justify-end">
                    <Button onClick={updatePassword}>
                      <Lock className="h-4 w-4" /> Update Password
                    </Button>
                  </div>
                </div>
              </Card>

              <Card title="Active Sessions" padded={false}>
                <div className="divide-y divide-border/60">
                  {sessions.map((s) => (
                    <div key={s.id} className="flex items-center gap-3 px-4 py-3">
                      <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-elevated text-text-secondary">
                        {s.device.includes('iPhone') ? <Smartphone className="h-4 w-4" /> : <Laptop className="h-4 w-4" />}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="flex items-center gap-2 text-sm font-medium text-text-primary">
                          {s.device}
                          {s.current && <span className="rounded-full bg-success/15 px-2 py-0.5 text-[10px] font-medium text-success">This device</span>}
                        </p>
                        <p className="text-xs text-text-muted">
                          {s.location} · active {s.lastActive}
                        </p>
                      </div>
                      {!s.current && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setSessions((list) => list.filter((x) => x.id !== s.id))
                            toast.success('Session signed out')
                          }}
                        >
                          <LogOut className="h-3.5 w-3.5" /> Sign out
                        </Button>
                      )}
                    </div>
                  ))}
                </div>
              </Card>
            </div>
          )}

          {tab === 'budget' && (
            <div className="space-y-4">
              <Card title="Monthly Budget">
                <div className="space-y-4">
                  <div className="max-w-xs">
                    <Input
                      type="number"
                      min="0"
                      step="0.01"
                      label={`Monthly Budget (${CURRENCY_META[currency].symbol})`}
                      value={budgetInput}
                      onChange={(e) => setBudgetInput(e.target.value)}
                    />
                    <p className="mt-1.5 text-xs text-text-muted">Current: {formatCost(budget?.monthly_budget_usd)}</p>
                  </div>

                  <div>
                    <label className="label">Budget alerts</label>
                    <div className="space-y-3 rounded-lg border border-border bg-elevated/40 p-4">
                      <ToggleRow label="Alert at 70% of budget" checked={settings.budgetAlerts.alertAt70} onChange={(v) => settings.setBudgetAlerts({ alertAt70: v })} />
                      <ToggleRow label="Alert at 90% of budget" checked={settings.budgetAlerts.alertAt90} onChange={(v) => settings.setBudgetAlerts({ alertAt90: v })} />
                      <ToggleRow label="Hard stop at 100% (block new tasks)" checked={settings.budgetAlerts.hardStopAt100} onChange={(v) => settings.setBudgetAlerts({ hardStopAt100: v })} />
                    </div>
                  </div>

                  <div className="max-w-xs">
                    <Select
                      label="Cost display currency"
                      value={currency}
                      onChange={(e) => settings.setCurrency(e.target.value as Currency)}
                      options={(Object.keys(CURRENCY_META) as Currency[]).map((c) => ({ value: c, label: CURRENCY_META[c].label }))}
                    />
                  </div>

                  <div className="flex justify-end">
                    <Button loading={savingBudget} onClick={saveBudget}>
                      Save Budget
                    </Button>
                  </div>
                </div>
              </Card>
            </div>
          )}

          {tab === 'notifications' && (
            <Card title="Notifications">
              <div className="space-y-3">
                <ToggleRow label="Task completed" checked={settings.notifications.taskCompleted} onChange={(v) => settings.setNotifications({ taskCompleted: v })} />
                <ToggleRow label="Task failed" checked={settings.notifications.taskFailed} onChange={(v) => settings.setNotifications({ taskFailed: v })} />
                <ToggleRow label="HITL approval required" checked={settings.notifications.hitlRequired} onChange={(v) => settings.setNotifications({ hitlRequired: v })} />
                <ToggleRow label="Budget alert (70%)" checked={settings.notifications.budgetAlert70} onChange={(v) => settings.setNotifications({ budgetAlert70: v })} />
                <ToggleRow label="Budget alert (90%)" checked={settings.notifications.budgetAlert90} onChange={(v) => settings.setNotifications({ budgetAlert90: v })} />
                <ToggleRow label="Agent performance reports (weekly)" checked={settings.notifications.weeklyReport} onChange={(v) => settings.setNotifications({ weeklyReport: v })} />
              </div>
            </Card>
          )}
        </div>
      </div>
    </PageWrapper>
  )
}

function ToggleRow({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-sm text-text-primary">{label}</span>
      <Toggle checked={checked} onChange={onChange} label={label} />
    </div>
  )
}
