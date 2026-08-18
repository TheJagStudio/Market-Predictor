import type { ReactNode } from "react"
import { Link, useLocation } from "react-router-dom"
import {
  ActivityIcon,
  CandlestickChartIcon,
  LayoutDashboardIcon,
  Settings2Icon,
  SparklesIcon,
  WalletCardsIcon,
} from "lucide-react"

import { useBoot } from "@/lib/boot"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboardIcon },
  { to: "/collect", label: "Collect", icon: ActivityIcon },
  { to: "/train", label: "Train", icon: SparklesIcon },
  { to: "/trade", label: "Trade", icon: WalletCardsIcon },
  { to: "/settings", label: "Settings", icon: Settings2Icon },
]

export function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation()
  const { boot } = useBoot()
  const collectorOn = Boolean(boot?.collector.running)
  const inferenceOn = Boolean(boot?.inference.running)

  return (
    <SidebarProvider>
      <Sidebar>
        <SidebarHeader>
          <div className="flex items-center gap-2 px-2 py-1">
            <CandlestickChartIcon />
            <div className="flex min-w-0 flex-col">
              <span className="truncate font-medium">BTC 15m Pipeline</span>
              <span className="truncate text-xs text-muted-foreground">
                Collect · Train · Trade
              </span>
            </div>
          </div>
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel>Workspace</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {NAV.map((item) => (
                  <SidebarMenuItem key={item.to}>
                    <SidebarMenuButton
                      isActive={location.pathname === item.to}
                      render={<Link to={item.to} />}
                    >
                      <item.icon />
                      {item.label}
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter>
          <div className="flex flex-col gap-2 px-2 pb-2">
            <div className="flex items-center gap-2">
              <Badge variant={collectorOn ? "default" : "secondary"}>
                {collectorOn ? "Collector live" : "Collector off"}
              </Badge>
              <Badge variant={inferenceOn ? "default" : "outline"}>
                {inferenceOn ? "Inference on" : "Inference off"}
              </Badge>
            </div>
            {boot?.settings.dry_run !== false ? (
              <span className="text-xs text-muted-foreground">Dry-run orders</span>
            ) : (
              <span className="text-xs text-muted-foreground">Live Polymarket orders</span>
            )}
          </div>
        </SidebarFooter>
      </Sidebar>
      <SidebarInset>
        <header className="flex h-12 items-center gap-2 border-b px-4">
          <SidebarTrigger />
          <Separator orientation="vertical" />
          <span className="text-sm text-muted-foreground">
            {boot?.market.slug ?? "btc-updown-15m"}
          </span>
        </header>
        <div className="flex flex-1 flex-col gap-4 p-4">{children}</div>
      </SidebarInset>
    </SidebarProvider>
  )
}
