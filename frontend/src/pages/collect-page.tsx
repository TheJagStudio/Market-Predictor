import { useState } from "react"
import { toast } from "sonner"
import { DatabaseIcon, PlayIcon, SquareIcon } from "lucide-react"

import { postBackfill, startCollector, stopCollector } from "@/lib/api"
import { useBoot } from "@/lib/boot"
import { useLive } from "@/lib/use-live"
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
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

export function CollectPage() {
  const { boot, refresh } = useBoot()
  const live = useLive(true)
  const [days, setDays] = useState("7")
  const [busy, setBusy] = useState(false)

  async function toggle() {
    try {
      if (boot?.collector.running) await stopCollector()
      else await startCollector()
      await refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed")
    }
  }

  async function backfill() {
    setBusy(true)
    try {
      const result = await postBackfill(Number(days), {
        assets: (boot?.settings.enabled_assets as string[] | undefined) ?? boot?.universe?.enabled_assets,
        intervals: (boot?.settings.bar_timeframes as string[] | undefined) ?? boot?.universe?.enabled_timeframes,
      })
      toast.success(`Backfilled ${result.fetched} klines (${result.created} new bars)`)
      await refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Backfill failed")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-col gap-1">
          <h1 className="text-lg font-medium">Data collection</h1>
          <p className="text-sm text-muted-foreground">
            24/7 multi-venue WebSockets for every selected coin, plus a free Binance kline backfill across 1m/5m/15m/1h.
          </p>
        </div>
        <Button onClick={toggle}>
          {boot?.collector.running ? <SquareIcon data-icon="inline-start" /> : <PlayIcon data-icon="inline-start" />}
          {boot?.collector.running ? "Stop collector" : "Start collector"}
        </Button>
      </div>
      <Alert>
        <AlertTitle>Two layers of data</AlertTitle>
        <AlertDescription>
          Live streams build microstructure features (TFI, VPIN, order-book imbalance) for BTC, ETH, XRP, and the rest of your universe. Backfill adds OHLC history on every selected timeframe so you can train a 1-minute starter model today.
        </AlertDescription>
      </Alert>
      <Card>
        <CardHeader>
          <CardTitle>Historical backfill</CardTitle>
          <CardDescription>Public Binance klines. No API key.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="days">Days of history for every selected coin and timeframe</FieldLabel>
              <Input id="days" value={days} onChange={(e) => setDays(e.target.value)} />
            </Field>
          </FieldGroup>
          <Button variant="secondary" onClick={backfill} disabled={busy}>
            <DatabaseIcon data-icon="inline-start" />
            Run backfill
          </Button>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Bars by coin and timeframe</CardTitle>
          <CardDescription>
            Next-bar labels appear one interval later. 15-minute labels need a 15-minute future price.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Coin</TableHead>
                <TableHead>Timeframe</TableHead>
                <TableHead>Bars</TableHead>
                <TableHead>Next-bar labels</TableHead>
                <TableHead>15m labels</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(boot?.counts.by_asset_interval ?? []).map((row) => (
                <TableRow key={`${row.asset}-${row.interval_seconds}`}>
                  <TableCell>{row.asset}</TableCell>
                  <TableCell>{secondsToTf(row.interval_seconds)}</TableCell>
                  <TableCell>{row.bars}</TableCell>
                  <TableCell>{row.labeled_next}</TableCell>
                  <TableCell>{row.labeled_15m}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Source status</CardTitle>
          <CardDescription>
            Queue {String(boot?.collector.stats?.queue ?? "—")} · messages {String(boot?.collector.stats?.messages ?? "—")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Source</TableHead>
                <TableHead>Kind</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Messages</TableHead>
                <TableHead>Error</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(boot?.sources ?? []).map((source) => (
                <TableRow key={source.id}>
                  <TableCell>{source.label}</TableCell>
                  <TableCell>{source.kind}</TableCell>
                  <TableCell>
                    <Badge variant={source.status === "live" ? "default" : "secondary"}>{source.status}</Badge>
                  </TableCell>
                  <TableCell>{source.message_count}</TableCell>
                  <TableCell className="max-w-56 truncate text-muted-foreground">{source.error || "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Recent tape</CardTitle>
          <CardDescription>Last trades retained in SQLite.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Venue</TableHead>
                <TableHead>Coin</TableHead>
                <TableHead>Price</TableHead>
                <TableHead>Size</TableHead>
                <TableHead>Side</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(live?.ticks ?? []).slice(0, 12).map((tick) => (
                <TableRow key={`${tick.venue}-${tick.ts_ms}-${tick.price}`}>
                  <TableCell>{tick.venue}</TableCell>
                  <TableCell>{tick.asset ?? "—"}</TableCell>
                  <TableCell>{tick.price?.toFixed(2)}</TableCell>
                  <TableCell>{tick.size?.toFixed(4)}</TableCell>
                  <TableCell>{tick.is_buyer_maker ? "sell" : "buy"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}

function secondsToTf(seconds: number) {
  const map: Record<number, string> = { 60: "1m", 300: "5m", 900: "15m", 3600: "1h" }
  return map[seconds] ?? `${seconds}s`
}
