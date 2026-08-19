import { useEffect, useState } from "react"
import { toast } from "sonner"

import {
  getEnsemble,
  getJob,
  getJobs,
  postTrain,
  saveEnsemble,
  type Artifact,
  type Ensemble,
  type TrainJob,
} from "@/lib/api"
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
import { Checkbox } from "@/components/ui/checkbox"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Switch } from "@/components/ui/switch"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"

export function TrainPage() {
  const { boot, refresh } = useBoot()
  const arches = boot?.architectures ?? []
  const [selected, setSelected] = useState<string[]>(arches.map((a) => a.id))
  const [jobs, setJobs] = useState<TrainJob[]>([])
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [ensemble, setEnsemble] = useState<Ensemble | null>(null)
  const [mode, setMode] = useState("auc_weighted")
  const [busy, setBusy] = useState(false)
  const [timeframe, setTimeframe] = useState("1m")
  const [label, setLabel] = useState("next")
  const [pool, setPool] = useState(true)

  useEffect(() => {
    if (arches.length && selected.length === 0) setSelected(arches.map((a) => a.id))
  }, [arches, selected.length])

  useEffect(() => {
    let cancelled = false
    async function load() {
      const [jobRes, ens] = await Promise.all([getJobs(), getEnsemble()])
      if (cancelled) return
      setJobs(jobRes.jobs)
      setEnsemble(ens)
      setMode(ens.mode)
      const running = jobRes.jobs.find((j) => j.status === "running" || j.status === "pending")
      const latest = running || jobRes.jobs[0]
      if (latest) {
        const detail = await getJob(latest.id)
        if (!cancelled) setArtifacts(detail.artifacts)
      }
    }
    load().catch(() => undefined)
    const id = window.setInterval(() => load().catch(() => undefined), 4000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [])

  async function train() {
    setBusy(true)
    try {
      await postTrain({
        architectures: selected,
        min_rows: 200,
        folds: 5,
        timeframe,
        label,
        pool_assets: pool,
        assets: pool ? boot?.settings.enabled_assets ?? boot?.universe?.enabled_assets : ["BTC"],
      })
      toast.success("Training started in a background process")
      await refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Training failed")
    } finally {
      setBusy(false)
    }
  }

  async function persistEnsemble(nextIds?: number[]) {
    const ids = nextIds ?? artifacts.filter((a) => a.selected).map((a) => a.id)
    const ens = await saveEnsemble({ mode, selected_ids: ids })
    setEnsemble(ens)
    toast.success("Ensemble updated")
  }

  const models = (jobs[0]?.summary?.models as Array<Record<string, unknown>> | undefined) ?? []

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-col gap-1">
          <h1 className="text-lg font-medium">Train 20 architectures</h1>
          <p className="text-sm text-muted-foreground">
            Walk-forward on pooled coins. Start with 1-minute next-bar labels so you can test a model in minutes, then switch to the 15-minute horizon.
          </p>
        </div>
        <Button onClick={train} disabled={busy || selected.length === 0}>
          Train selected
        </Button>
      </div>
      <Alert>
        <AlertTitle>Need labeled bars</AlertTitle>
        <AlertDescription>
          You currently have {boot?.counts.labeled_next ?? 0} next-bar labels and {boot?.counts.labeled ?? 0} 15-minute labels
          ({boot?.counts.bars ?? 0} total bars). Pooling BTC/ETH/XRP on 1m is the fastest way to reach 200 rows.
        </AlertDescription>
      </Alert>
      <Card>
        <CardHeader>
          <CardTitle>Dataset</CardTitle>
          <CardDescription>Same features for every coin; asset identity is not an input, so the model can generalize.</CardDescription>
        </CardHeader>
        <CardContent>
          <FieldGroup>
            <Field>
              <FieldLabel>Timeframe</FieldLabel>
              <ToggleGroup value={[timeframe]} onValueChange={(v) => v[0] && setTimeframe(v[0])}>
                {(boot?.universe?.timeframes ?? [{ id: "1m" }, { id: "5m" }, { id: "15m" }, { id: "1h" }]).map((tf) => (
                  <ToggleGroupItem key={tf.id} value={tf.id}>
                    {tf.id}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </Field>
            <Field>
              <FieldLabel>Label</FieldLabel>
              <ToggleGroup value={[label]} onValueChange={(v) => v[0] && setLabel(v[0])}>
                <ToggleGroupItem value="next">Next bar</ToggleGroupItem>
                <ToggleGroupItem value="horizon_15m">15m horizon</ToggleGroupItem>
              </ToggleGroup>
              <FieldDescription>
                {label === "next"
                  ? "1m bars become trainable after one minute. Best for a starter model."
                  : "Matches Polymarket BTC Up/Down. Needs 15 minutes of future price."}
              </FieldDescription>
            </Field>
            <Field orientation="horizontal">
              <Switch id="pool" checked={pool} onCheckedChange={setPool} />
              <FieldLabel htmlFor="pool">Pool all collected coins into one dataset</FieldLabel>
            </Field>
          </FieldGroup>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Architectures</CardTitle>
          <CardDescription>All run locally with scikit-learn / XGBoost. No cloud GPU required.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {arches.map((arch) => (
              <label key={arch.id} className="flex items-start gap-2 rounded-lg border p-2 text-sm">
                <Checkbox
                  checked={selected.includes(arch.id)}
                  onCheckedChange={(checked) =>
                    setSelected((cur) =>
                      checked ? [...cur, arch.id] : cur.filter((id) => id !== arch.id)
                    )
                  }
                />
                <span>
                  {arch.label}
                  <span className="block text-xs text-muted-foreground">{arch.family}</span>
                </span>
              </label>
            ))}
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Latest comparison</CardTitle>
          <CardDescription>
            {jobs[0] ? `Job #${jobs[0].id} · ${jobs[0].status}` : "No training jobs yet"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Model</TableHead>
                <TableHead>Accuracy</TableHead>
                <TableHead>ROC-AUC</TableHead>
                <TableHead>F1</TableHead>
                <TableHead>Ensemble</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(artifacts.length ? artifacts : models.map((m, i) => ({
                id: i,
                name: String(m.name),
                metrics: m,
                selected: Boolean(m.selected),
                weight: Number(m.weight || 0),
              }))).map((row) => (
                <TableRow key={row.id}>
                  <TableCell>{row.name}</TableCell>
                  <TableCell>{fmtM(row.metrics.accuracy)}</TableCell>
                  <TableCell>{fmtM(row.metrics.roc_auc)}</TableCell>
                  <TableCell>{fmtM(row.metrics.f1)}</TableCell>
                  <TableCell>
                    {"selected" in row ? (
                      <Checkbox
                        checked={row.selected}
                        onCheckedChange={(checked) => {
                          const next = artifacts.map((a) =>
                            a.id === row.id ? { ...a, selected: Boolean(checked) } : a
                          )
                          setArtifacts(next)
                        }}
                      />
                    ) : (
                      <Badge variant="outline">n/a</Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Ensemble</CardTitle>
          <CardDescription>How live inference combines selected models.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <FieldGroup>
            <Field>
              <FieldLabel>Combination</FieldLabel>
              <ToggleGroup value={[mode]} onValueChange={(v) => v[0] && setMode(v[0])}>
                <ToggleGroupItem value="auc_weighted">AUC weighted</ToggleGroupItem>
                <ToggleGroupItem value="equal">Equal vote</ToggleGroupItem>
                <ToggleGroupItem value="best">Best only</ToggleGroupItem>
              </ToggleGroup>
            </Field>
          </FieldGroup>
          <Button variant="secondary" onClick={() => persistEnsemble()}>
            Save ensemble
          </Button>
          <p className="text-xs text-muted-foreground">
            Active job {ensemble?.active_job_id ?? "—"} · {ensemble?.members.length ?? 0} members
          </p>
        </CardContent>
      </Card>
    </div>
  )
}

function fmtM(value: unknown) {
  const n = Number(value)
  if (!Number.isFinite(n)) return "—"
  return n.toFixed(3)
}
