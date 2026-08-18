import { Line, LineChart, XAxis, YAxis } from "recharts"
import { toast } from "sonner"
import { PlayIcon, SquareIcon } from "lucide-react"

import { startCollector, startInference, stopCollector, stopInference } from "@/lib/api"
import { useBoot } from "@/lib/boot"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart"
import { useLive } from "@/lib/use-live"

const chartConfig = {
  mid: { label: "BTC mid", color: "var(--chart-1)" },
} satisfies ChartConfig

export function DashboardPage() {
  const { boot, refresh } = useBoot()
  const live = useLive(boot?.collector.running ?? false)

  const bars = (live?.bars ?? []).slice().reverse()
  const pred = boot?.latest_prediction
  const market = boot?.market
  const mid = boot?.latest_bar?.mid_price

  async function toggleCollector() {
    try {
      if (boot?.collector.running) await stopCollector()
      else await startCollector()
      await refresh()
      toast.success(boot?.collector.running ? "Collector stopped" : "Collector started")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Collector error")
    }
  }

  async function toggleInference() {
    try {
      if (boot?.inference.running) await stopInference()
      else await startInference()
      await refresh()
      toast.success(boot?.inference.running ? "Inference stopped" : "Inference started")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Inference error")
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-col gap-1">
          <h1 className="text-lg font-medium">Dashboard</h1>
          <p className="text-sm text-muted-foreground">
            Live free-data snapshot for the current Polymarket 15-minute BTC window.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant={boot?.collector.running ? "outline" : "default"} onClick={toggleCollector}>
            {boot?.collector.running ? <SquareIcon data-icon="inline-start" /> : <PlayIcon data-icon="inline-start" />}
            {boot?.collector.running ? "Stop collector" : "Start collector"}
          </Button>
          <Button variant="secondary" onClick={toggleInference}>
            {boot?.inference.running ? "Stop inference" : "Start inference"}
          </Button>
        </div>
      </div>
      <div className="grid gap-4 md:grid-cols-4">
        <Stat title="BTC mid" value={fmt(mid)} hint="Reference across venues" />
        <Stat
          title="P(up) ensemble"
          value={pred ? `${(pred.p_up * 100).toFixed(1)}%` : "—"}
          hint={pred?.action ?? "train a model first"}
        />
        <Stat
          title="Polymarket yes"
          value={fmtPct(market?.yes_mid)}
          hint={market?.slug ?? ""}
        />
        <Stat
          title="Labeled bars"
          value={String(boot?.counts.labeled ?? 0)}
          hint={`${boot?.counts.bars ?? 0} total bars`}
        />
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Recent mid price</CardTitle>
          <CardDescription>Feature bars written by the collector.</CardDescription>
        </CardHeader>
        <CardContent>
          {bars.length ? (
            <ChartContainer config={chartConfig} className="h-56 w-full">
              <LineChart data={bars.map((b) => ({ t: new Date(b.ts * 1000).toLocaleTimeString(), mid: b.mid_price }))}>
                <XAxis dataKey="t" hide />
                <YAxis domain={["auto", "auto"]} width={70} />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Line type="monotone" dataKey="mid" stroke="var(--color-mid)" dot={false} />
              </LineChart>
            </ChartContainer>
          ) : (
            <p className="text-sm text-muted-foreground">Start the collector to see live bars.</p>
          )}
        </CardContent>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Sources</CardTitle>
            <CardDescription>Public WebSocket / REST feeds.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col gap-2">
              {(boot?.sources ?? []).map((source) => (
                <div key={source.id} className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm">{source.label}</span>
                  <Badge variant={source.status === "live" ? "default" : source.status === "error" ? "destructive" : "secondary"}>
                    {source.enabled ? source.status : "off"}
                  </Badge>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Current 15m market</CardTitle>
            <CardDescription>
              {market?.seconds_left != null ? `${market.seconds_left}s remaining` : "Waiting for Gamma"}
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 text-sm">
            <div>Up bid/ask: {fmt(market?.yes_bid)} / {fmt(market?.yes_ask)}</div>
            <div>Down bid/ask: {fmt(market?.no_bid)} / {fmt(market?.no_ask)}</div>
            <div>Window open BTC: {fmt(market?.btc_open)}</div>
            {pred?.edge != null ? <div>Model edge: {(pred.edge * 100).toFixed(2)}¢</div> : null}
          </CardContent>
        </Card>
      </div>
      {boot?.settings.dry_run === false ? (
        <Alert variant="destructive">
          <AlertTitle>Live ordering is on</AlertTitle>
          <AlertDescription>The inference loop can send real Polymarket CLOB orders.</AlertDescription>
        </Alert>
      ) : null}
    </div>
  )
}

function Stat({ title, value, hint }: { title: string; value: string; hint: string }) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardDescription>{title}</CardDescription>
        <CardTitle>{value}</CardTitle>
      </CardHeader>
      <CardContent className="text-xs text-muted-foreground">{hint}</CardContent>
    </Card>
  )
}

function fmt(value?: number | null) {
  if (value == null || Number.isNaN(value)) return "—"
  return value >= 100 ? value.toFixed(2) : value.toFixed(4)
}

function fmtPct(value?: number | null) {
  if (value == null || Number.isNaN(value)) return "—"
  return `${(value * 100).toFixed(1)}%`
}
