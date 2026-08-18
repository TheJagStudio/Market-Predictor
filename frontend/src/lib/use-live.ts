import { useEffect, useState } from "react"

import { getLive, type LivePayload } from "@/lib/api"

export function useLive(enabled: boolean) {
  const [live, setLive] = useState<LivePayload | null>(null)

  useEffect(() => {
    let cancelled = false
    async function tick() {
      try {
        const data = await getLive()
        if (!cancelled) setLive(data)
      } catch {
        /* keep last */
      }
    }
    tick()
    const id = window.setInterval(tick, enabled ? 2000 : 8000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [enabled])

  return live
}
