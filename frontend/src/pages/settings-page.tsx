import { useState } from "react"
import { toast } from "sonner"

import { saveSettings } from "@/lib/api"
import { useBoot } from "@/lib/boot"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { AssetFields, TimeframeFields } from "@/components/universe-fields"

export function SettingsPage() {
  const { boot, refresh } = useBoot()
  const s = boot?.settings ?? {}
  const [dryRun, setDryRun] = useState(s.dry_run !== false)
  const [minEdge, setMinEdge] = useState(String(s.min_edge ?? 0.04))
  const [minConf, setMinConf] = useState(String(s.min_confidence ?? 0.55))
  const [orderSize, setOrderSize] = useState(String(s.order_size ?? 10))
  const universe = boot?.universe
  const [coins, setCoins] = useState<string[]>(
    (s.enabled_assets as string[] | undefined) ?? universe?.enabled_assets ?? universe?.default_assets ?? []
  )
  const [timeframes, setTimeframes] = useState<string[]>(
    (s.bar_timeframes as string[] | undefined) ?? universe?.enabled_timeframes ?? universe?.default_timeframes ?? []
  )
  const [barSec, setBarSec] = useState(String(s.bar_interval_seconds ?? 0))
  const [maxOrders, setMaxOrders] = useState(String(s.max_orders_per_window ?? 1))
  const [pk, setPk] = useState("")
  const [funder, setFunder] = useState(String(s.polymarket_funder ?? ""))
  const [sigType, setSigType] = useState(String(s.polymarket_signature_type ?? 0))
  const [apiKey, setApiKey] = useState("")
  const [apiSecret, setApiSecret] = useState("")
  const [apiPass, setApiPass] = useState("")
  const [builder, setBuilder] = useState(String(s.polymarket_builder_code ?? ""))

  async function save() {
    const payload: Record<string, unknown> = {
      dry_run: dryRun,
      min_edge: Number(minEdge),
      min_confidence: Number(minConf),
      order_size: Number(orderSize),
      bar_interval_seconds: Number(barSec),
      enabled_assets: coins,
      bar_timeframes: timeframes,
      max_orders_per_window: Number(maxOrders),
      polymarket_funder: funder,
      polymarket_signature_type: Number(sigType),
      polymarket_builder_code: builder,
    }
    if (pk.trim()) payload.polymarket_private_key = pk.trim()
    if (apiKey.trim()) payload.polymarket_api_key = apiKey.trim()
    if (apiSecret.trim()) payload.polymarket_api_secret = apiSecret.trim()
    if (apiPass.trim()) payload.polymarket_api_passphrase = apiPass.trim()
    try {
      await saveSettings(payload)
      await refresh()
      toast.success("Settings saved")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Save failed")
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-lg font-medium">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Stored in local SQLite. Secrets are encrypted with the Django secret key.
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Trading</CardTitle>
          <CardDescription>Safety limits for the 15-minute Up/Down market.</CardDescription>
        </CardHeader>
        <CardContent>
          <FieldGroup>
            <Field orientation="horizontal">
              <Switch id="dry" checked={dryRun} onCheckedChange={setDryRun} />
              <FieldLabel htmlFor="dry">Dry-run (do not send CLOB orders)</FieldLabel>
            </Field>
            <Field>
              <FieldLabel htmlFor="edge">Min edge</FieldLabel>
              <Input id="edge" value={minEdge} onChange={(e) => setMinEdge(e.target.value)} />
            </Field>
            <Field>
              <FieldLabel htmlFor="conf">Min confidence</FieldLabel>
              <Input id="conf" value={minConf} onChange={(e) => setMinConf(e.target.value)} />
            </Field>
            <Field>
              <FieldLabel htmlFor="size">Order size</FieldLabel>
              <Input id="size" value={orderSize} onChange={(e) => setOrderSize(e.target.value)} />
            </Field>
            <Field>
              <FieldLabel htmlFor="maxo">Max orders per 15m window</FieldLabel>
              <Input id="maxo" value={maxOrders} onChange={(e) => setMaxOrders(e.target.value)} />
            </Field>
            <Field>
              <FieldLabel htmlFor="bar">Optional micro snapshot seconds</FieldLabel>
              <Input id="bar" value={barSec} onChange={(e) => setBarSec(e.target.value)} />
              <FieldDescription>0 = off. Restart the collector after changing coins or timeframes.</FieldDescription>
            </Field>
          </FieldGroup>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Collection universe</CardTitle>
          <CardDescription>Live streams subscribe to every selected coin and write every selected timeframe at once.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <AssetFields assets={universe?.assets ?? []} selected={coins} onChange={setCoins} />
          <TimeframeFields timeframes={universe?.timeframes ?? []} selected={timeframes} onChange={setTimeframes} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Polymarket CLOB</CardTitle>
          <CardDescription>
            Optional. Derive API creds from the private key, or paste existing L2 credentials.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="pk">Private key</FieldLabel>
              <Input
                id="pk"
                type="password"
                value={pk}
                placeholder={s.polymarket_private_key_set ? "Saved — paste to replace" : "0x…"}
                onChange={(e) => setPk(e.target.value)}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="funder">Funder</FieldLabel>
              <Input id="funder" value={funder} onChange={(e) => setFunder(e.target.value)} />
            </Field>
            <Field>
              <FieldLabel htmlFor="sig">Signature type</FieldLabel>
              <Input id="sig" value={sigType} onChange={(e) => setSigType(e.target.value)} />
            </Field>
            <Field>
              <FieldLabel htmlFor="akey">CLOB API key</FieldLabel>
              <Input id="akey" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
            </Field>
            <Field>
              <FieldLabel htmlFor="asec">CLOB API secret</FieldLabel>
              <Input id="asec" type="password" value={apiSecret} onChange={(e) => setApiSecret(e.target.value)} />
            </Field>
            <Field>
              <FieldLabel htmlFor="apass">CLOB passphrase</FieldLabel>
              <Input id="apass" type="password" value={apiPass} onChange={(e) => setApiPass(e.target.value)} />
            </Field>
            <Field>
              <FieldLabel htmlFor="builder">Builder code</FieldLabel>
              <Input id="builder" value={builder} onChange={(e) => setBuilder(e.target.value)} />
            </Field>
          </FieldGroup>
        </CardContent>
        <CardFooter>
          <Button onClick={save}>Save settings</Button>
        </CardFooter>
      </Card>
    </div>
  )
}
