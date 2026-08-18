import { useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"
import { CandlestickChartIcon } from "lucide-react"

import { saveSetup } from "@/lib/api"
import { useBoot } from "@/lib/boot"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"

export function SetupPage() {
  const { boot, refresh } = useBoot()
  const navigate = useNavigate()
  const catalog = boot?.sources ?? []
  const [enabled, setEnabled] = useState<string[]>(
    boot?.settings.enabled_sources ?? catalog.map((s) => s.id)
  )
  const [dryRun, setDryRun] = useState(boot?.settings.dry_run !== false)
  const [minEdge, setMinEdge] = useState(String(boot?.settings.min_edge ?? 0.04))
  const [minConf, setMinConf] = useState(String(boot?.settings.min_confidence ?? 0.55))
  const [orderSize, setOrderSize] = useState(String(boot?.settings.order_size ?? 10))
  const [barSec, setBarSec] = useState(String(boot?.settings.bar_interval_seconds ?? 5))
  const [pk, setPk] = useState("")
  const [funder, setFunder] = useState(String(boot?.settings.polymarket_funder ?? ""))
  const [sigType, setSigType] = useState(String(boot?.settings.polymarket_signature_type ?? 0))
  const [busy, setBusy] = useState(false)

  const allIds = useMemo(() => catalog.map((s) => s.id), [catalog])

  async function onSubmit() {
    setBusy(true)
    try {
      const payload: Record<string, unknown> = {
        enabled_sources: enabled,
        dry_run: dryRun,
        min_edge: Number(minEdge),
        min_confidence: Number(minConf),
        order_size: Number(orderSize),
        bar_interval_seconds: Number(barSec),
        polymarket_funder: funder,
        polymarket_signature_type: Number(sigType),
      }
      if (pk.trim()) payload.polymarket_private_key = pk.trim()
      await saveSetup(payload)
      await refresh()
      toast.success("Setup saved. You can start collecting data.")
      navigate("/")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Setup failed")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 py-8">
      <div className="flex items-center gap-2">
        <CandlestickChartIcon />
        <div className="flex flex-col">
          <h1 className="text-lg font-medium">Setup BTC 15-minute pipeline</h1>
          <p className="text-sm text-muted-foreground">
            Free public WebSockets only. Polymarket keys are optional until you place live orders.
          </p>
        </div>
      </div>
      <Alert>
        <AlertTitle>Accuracy vs fees</AlertTitle>
        <AlertDescription>
          55–60% directional accuracy is ambitious on a 15-minute horizon. Keep dry-run on until
          live edge after fees is positive.
        </AlertDescription>
      </Alert>
      <Card>
        <CardHeader>
          <CardTitle>Free data sources</CardTitle>
          <CardDescription>
            Enable every venue you want in the 24/7 collector. No paid API keys.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FieldGroup>
            {catalog.map((source) => (
              <Field key={source.id} orientation="horizontal">
                <Checkbox
                  id={source.id}
                  checked={enabled.includes(source.id)}
                  onCheckedChange={(checked) => {
                    setEnabled((current) =>
                      checked ? [...new Set([...current, source.id])] : current.filter((id) => id !== source.id)
                    )
                  }}
                />
                <FieldLabel htmlFor={source.id}>
                  {source.label}
                  <FieldDescription>{source.detail}</FieldDescription>
                </FieldLabel>
              </Field>
            ))}
          </FieldGroup>
          <div className="mt-3 flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setEnabled(allIds)}>
              Enable all
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setEnabled(["binance_spot", "polymarket_gamma"])}>
              Minimal
            </Button>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Feature bars &amp; risk</CardTitle>
          <CardDescription>How often to snapshot features and when an order is allowed.</CardDescription>
        </CardHeader>
        <CardContent>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="bar">Bar interval (seconds)</FieldLabel>
              <Input id="bar" value={barSec} onChange={(e) => setBarSec(e.target.value)} />
            </Field>
            <Field>
              <FieldLabel htmlFor="edge">Minimum edge vs Polymarket yes-price</FieldLabel>
              <Input id="edge" value={minEdge} onChange={(e) => setMinEdge(e.target.value)} />
            </Field>
            <Field>
              <FieldLabel htmlFor="conf">Minimum confidence P(up) or P(down)</FieldLabel>
              <Input id="conf" value={minConf} onChange={(e) => setMinConf(e.target.value)} />
            </Field>
            <Field>
              <FieldLabel htmlFor="size">Order size (shares)</FieldLabel>
              <Input id="size" value={orderSize} onChange={(e) => setOrderSize(e.target.value)} />
            </Field>
            <Field orientation="horizontal">
              <Switch checked={dryRun} onCheckedChange={setDryRun} id="dry" />
              <FieldLabel htmlFor="dry">Dry-run orders (recommended)</FieldLabel>
            </Field>
          </FieldGroup>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Polymarket trading (optional)</CardTitle>
          <CardDescription>
            Leave blank to collect and train only. Private keys stay encrypted in local SQLite.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="pk">Polygon wallet private key</FieldLabel>
              <Input
                id="pk"
                type="password"
                placeholder={boot?.settings.polymarket_private_key_set ? "Saved — paste to replace" : "0x…"}
                value={pk}
                onChange={(e) => setPk(e.target.value)}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="funder">Funder / proxy address</FieldLabel>
              <Input id="funder" value={funder} onChange={(e) => setFunder(e.target.value)} placeholder="Required for email/Magic/Safe wallets" />
            </Field>
            <Field>
              <FieldLabel htmlFor="sig">Signature type (0 EOA, 1 proxy, 2 Safe, 3 deposit)</FieldLabel>
              <Input id="sig" value={sigType} onChange={(e) => setSigType(e.target.value)} />
            </Field>
          </FieldGroup>
        </CardContent>
        <CardFooter>
          <Button onClick={onSubmit} disabled={busy}>
            Save and open dashboard
          </Button>
        </CardFooter>
      </Card>
    </div>
  )
}
