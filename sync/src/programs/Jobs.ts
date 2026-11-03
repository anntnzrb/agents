import { Effect } from "effect"

import { cleanNpmCache } from "#packages/NpmCacheClean"
import { refreshPackages } from "#packages/RefreshPackages"

export const job = Effect.fn("Jobs.job")(function* (name: "refresh-packages" | "npm-cache-clean") {
  return yield* name === "refresh-packages" ? refreshPackages() : cleanNpmCache()
})
