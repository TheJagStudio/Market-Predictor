import { Checkbox } from "@/components/ui/checkbox"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import type { UniverseAsset, UniverseTimeframe } from "@/lib/api"

export function AssetFields({
  assets,
  selected,
  onChange,
}: {
  assets: UniverseAsset[]
  selected: string[]
  onChange: (next: string[]) => void
}) {
  return (
    <FieldGroup>
      <div className="grid gap-2 sm:grid-cols-2">
        {assets.map((asset) => (
          <Field key={asset.id} orientation="horizontal">
            <Checkbox
              id={`asset-${asset.id}`}
              checked={selected.includes(asset.id)}
              onCheckedChange={(checked) => {
                onChange(
                  checked
                    ? [...new Set([...selected, asset.id])]
                    : selected.filter((id) => id !== asset.id)
                )
              }}
            />
            <FieldLabel htmlFor={`asset-${asset.id}`}>
              {asset.id}
              <FieldDescription>{asset.label}</FieldDescription>
            </FieldLabel>
          </Field>
        ))}
      </div>
    </FieldGroup>
  )
}

export function TimeframeFields({
  timeframes,
  selected,
  onChange,
}: {
  timeframes: UniverseTimeframe[]
  selected: string[]
  onChange: (next: string[]) => void
}) {
  return (
    <FieldGroup>
      <div className="grid gap-2 sm:grid-cols-2">
        {timeframes.map((tf) => (
          <Field key={tf.id} orientation="horizontal">
            <Checkbox
              id={`tf-${tf.id}`}
              checked={selected.includes(tf.id)}
              onCheckedChange={(checked) => {
                onChange(
                  checked ? [...new Set([...selected, tf.id])] : selected.filter((id) => id !== tf.id)
                )
              }}
            />
            <FieldLabel htmlFor={`tf-${tf.id}`}>
              {tf.label}
              <FieldDescription>{tf.seconds}s bars</FieldDescription>
            </FieldLabel>
          </Field>
        ))}
      </div>
    </FieldGroup>
  )
}
