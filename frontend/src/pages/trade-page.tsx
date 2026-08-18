import { toast } from "sonner"
import { PlayIcon, SquareIcon } from "lucide-react"

import { postPredict, startInference, stopInference } from "@/lib/api"
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { getOrders, getPredictions, type Order, type Prediction } from "@/lib/api"
import { useEffect, useState } from "react"

export function TradePage() {
  const { boot, refresh } = useBoot()
  useLive(Boolean(boot?.inference.running))
  const [preds, setPreds] = useState<Prediction[]>([])
  const [orders, setOrders] = useState<Order[]>([])
  const pred = boot?.latest_prediction
  const market = boot?.market
  const dry = boot?.settings.dry_run !== false

  useEffect(() => {
    let cancelled = false
    async function load() {
      const [p, o] = await Promise.all([getPredictions(), getOrders()])
      if (cancelled) return
      setPreds(p.predictions)
      setOrders(o.orders)
    }
    load().catch(() => undefined)
    const id = window.setInterval(() => load().catch(() => undefined), 4000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [])

  async function toggle() {
    try {
      if (boot?.inference.running) await stopInference()
      else await startInference()
      await refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed")
    }
  }

  async function once(place: boolean) {
    try {
      const result = await postPredict(place)
      toast.success(`P(up)=${(result.prediction.p_up * 100).toFixed(1)}% → ${result.prediction.action}`)
      await refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Predict failed")
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-col gap-1">
          <h1 className="text-lg font-medium">Inference &amp; Polymarket 15m</h1>
          <p className="text-sm text-muted-foreground">
            Ensemble P(up) versus the live Up contract. Orders stay dry-run until you disable it.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => once(false)}>
            Score once
          </Button>
          <Button onClick={toggle}>
            {boot?.inference.running ? <SquareIcon data-icon="inline-start" /> : <PlayIcon data-icon="inline-start" />}
            {boot?.inference.running ? "Stop loop" : "Start loop"}
          </Button>
        </div>
      </div>
      <Alert variant={dry ? "default" : "destructive"}>
        <AlertTitle>{dry ? "Dry-run is enabled" : "Live CLOB orders"}</AlertTitle>
        <AlertDescription>
          {dry
            ? "Signals are recorded locally. No Polymarket order is submitted."
            : "The loop can buy Up or Down on the current btc-updown-15m market."}
        </AlertDescription>
      </Alert>
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardDescription>Ensemble P(up)</CardDescription>
            <CardTitle>{pred ? `${(pred.p_up * 100).toFixed(1)}%` : "—"}</CardTitle>
          </CardHeader>
          <CardContent>
            <Badge>{pred?.action ?? "hold"}</Badge>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Market yes mid</CardDescription>
            <CardTitle>
              {market?.yes_mid != null ? `${(market.yes_mid * 100).toFixed(1)}%` : "—"}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">{market?.slug}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Edge</CardDescription>
            <CardTitle>{pred?.edge != null ? pred.edge.toFixed(3) : "—"}</CardTitle>
          </CardHeader>
          <CardContent>
            <Button size="sm" variant="secondary" onClick={() => once(true)}>
              Place now (respects dry-run)
            </Button>
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Per-model probabilities</CardTitle>
          <CardDescription>Latest inference breakdown.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {pred
            ? Object.entries(pred.per_model).map(([name, value]) => (
                <Badge key={name} variant="outline">
                  {name} {(value * 100).toFixed(1)}%
                </Badge>
              ))
            : <span className="text-sm text-muted-foreground">Train models, then score.</span>}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Recent signals</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>P(up)</TableHead>
                <TableHead>Implied</TableHead>
                <TableHead>Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {preds.slice(0, 12).map((row) => (
                <TableRow key={row.id}>
                  <TableCell>{new Date(row.ts * 1000).toLocaleTimeString()}</TableCell>
                  <TableCell>{(row.p_up * 100).toFixed(1)}%</TableCell>
                  <TableCell>{row.implied_yes != null ? `${(row.implied_yes * 100).toFixed(1)}%` : "—"}</TableCell>
                  <TableCell>{row.action}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Orders</CardTitle>
          <CardDescription>Dry-run and live CLOB submissions.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>When</TableHead>
                <TableHead>Outcome</TableHead>
                <TableHead>Price</TableHead>
                <TableHead>Size</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {orders.map((row) => (
                <TableRow key={row.id}>
                  <TableCell>{new Date(row.created_at).toLocaleTimeString()}</TableCell>
                  <TableCell>{row.outcome}</TableCell>
                  <TableCell>{row.price}</TableCell>
                  <TableCell>{row.size}</TableCell>
                  <TableCell>
                    <Badge variant={row.dry_run ? "secondary" : "default"}>{row.status}</Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
