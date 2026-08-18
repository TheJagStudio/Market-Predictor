import { useCallback, useEffect, useState } from "react"
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom"
import { Toaster } from "sonner"

import { AppShell } from "@/components/app-shell"
import { TooltipProvider } from "@/components/ui/tooltip"
import { Skeleton } from "@/components/ui/skeleton"
import { BootContext } from "@/lib/boot"
import { getBootstrap, type Bootstrap } from "@/lib/api"
import { CollectPage } from "@/pages/collect-page"
import { DashboardPage } from "@/pages/dashboard-page"
import { SettingsPage } from "@/pages/settings-page"
import { SetupPage } from "@/pages/setup-page"
import { TradePage } from "@/pages/trade-page"
import { TrainPage } from "@/pages/train-page"

export function App() {
  const [boot, setBoot] = useState<Bootstrap | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    const data = await getBootstrap()
    setBoot(data)
    setError(null)
  }, [])

  useEffect(() => {
    refresh().catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load"))
    const id = window.setInterval(() => {
      refresh().catch(() => undefined)
    }, 3000)
    return () => window.clearInterval(id)
  }, [refresh])

  return (
    <TooltipProvider>
      <BootContext.Provider value={{ boot, error, refresh }}>
        <BrowserRouter>
          <AppRoutes error={error} boot={boot} />
        </BrowserRouter>
      </BootContext.Provider>
      <Toaster />
    </TooltipProvider>
  )
}

function AppRoutes({ boot, error }: { boot: Bootstrap | null; error: string | null }) {
  const location = useLocation()
  if (error && !boot) {
    return (
      <div className="flex min-h-svh items-center justify-center p-6">
        <p className="text-sm text-muted-foreground">{error}. Is Django running on port 8000?</p>
      </div>
    )
  }
  if (!boot) {
    return (
      <div className="flex min-h-svh flex-col gap-3 p-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }
  if (!boot.setup_complete && location.pathname !== "/setup") {
    return <Navigate to="/setup" replace />
  }
  if (location.pathname === "/setup") {
    return (
      <div className="min-h-svh px-4">
        <SetupPage />
      </div>
    )
  }
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/collect" element={<CollectPage />} />
        <Route path="/train" element={<TrainPage />} />
        <Route path="/trade" element={<TradePage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  )
}

export default App
