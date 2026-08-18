import { createContext, useContext } from "react"

import type { Bootstrap } from "@/lib/api"

type BootState = {
  boot: Bootstrap | null
  error: string | null
  refresh: () => Promise<void>
}

export const BootContext = createContext<BootState>({
  boot: null,
  error: null,
  refresh: async () => {},
})

export function useBoot() {
  return useContext(BootContext)
}
