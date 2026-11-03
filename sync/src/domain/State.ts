import { Array as Arr, Effect, Record as Rec, Schema, String as Str } from "effect"

import { isSafeManagedEntryName } from "#domain/EntryNames"
import { compareCodePoints } from "#domain/Fingerprint"

const { sort: sortArray } = Arr

export const ManagedEntries = Schema.Array(Schema.String)
export type ManagedEntries = typeof ManagedEntries.Type

export const HookState = Schema.Struct({
  fingerprint: Schema.String,
  generatedEntries: Schema.Array(Schema.String),
})
export type HookState = typeof HookState.Type

const defaultEntries = Schema.Array(Schema.String).pipe(Schema.withDecodingDefaultKey(Effect.succeed([])))
export const WrapperState = Schema.Struct({
  version: Schema.Literal(1),
  entries: defaultEntries,
})
export type WrapperState = typeof WrapperState.Type

export const SyncedState = Schema.Struct({ commit: Schema.String })
export type SyncedState = typeof SyncedState.Type

export const uniqueSorted = (entries: Iterable<string>): string[] =>
  sortArray(compareCodePoints)([...new Set(entries)])

export const normalizeManagedEntries = (entries: readonly string[]): string[] =>
  uniqueSorted(Arr.filter<string>((entry) => isSafeManagedEntryName(entry))(entries))

const generatedNames: Record<string, true> = {
  "package.json": true,
  node_modules: true,
  "bun.lock": true,
  "bun.lockb": true,
}

export const normalizeHookState = (
  state: HookState,
): HookState & { readonly shouldRefreshState: boolean } => {
  const normalized = uniqueSorted(state.generatedEntries)
  const generatedEntries = Arr.filter<string>((entry) => {
    const parts = Str.split(entry, "/")
    return Rec.has(generatedNames, parts.at(-1) ?? "")
  })(normalized)
  return {
    fingerprint: state.fingerprint,
    generatedEntries,
    shouldRefreshState: generatedEntries.length !== normalized.length,
  }
}

export const normalizeWrapperState = (state: WrapperState): WrapperState => ({
  version: 1,
  entries: uniqueSorted(Arr.filter<string>((entry) => Str.startsWith("/")(entry))(state.entries)),
})

export interface PreparedHookState {
  readonly fingerprint: string
  readonly generatedEntries: readonly string[]
  readonly preservePaths: readonly string[]
  readonly shouldSkip: boolean
  readonly shouldRefreshState: boolean
}

export const prepareHookState = (
  fingerprint: string,
  previous: (HookState & { readonly shouldRefreshState: boolean }) | null,
  relativeRoot: string,
  exists: (entry: string) => boolean,
): PreparedHookState => {
  if (previous === null || previous.fingerprint !== fingerprint) {
    return {
      fingerprint,
      generatedEntries: [],
      preservePaths: [],
      shouldSkip: false,
      shouldRefreshState: false,
    }
  }
  const generatedEntries = Arr.filter<string>((entry) => exists(entry))(previous.generatedEntries)
  const shouldSkip = generatedEntries.length === previous.generatedEntries.length
  return {
    fingerprint,
    generatedEntries,
    preservePaths: shouldSkip
      ? Arr.map((entry: string) => (relativeRoot === "" ? entry : `${relativeRoot}/${entry}`))(
          generatedEntries,
        )
      : [],
    shouldSkip,
    shouldRefreshState: previous.shouldRefreshState,
  }
}
