import { Schema } from "effect"

export const StaticReleaseAsset = Schema.Struct({
  url: Schema.String,
  sha256: Schema.String.check(Schema.isPattern(/^[a-f0-9]{64}$/u)),
})
export type StaticReleaseAsset = typeof StaticReleaseAsset.Type

export const StaticReleaseManifest = Schema.Struct({
  version: Schema.String.check(Schema.isPattern(/^[A-Za-z0-9._-]+$/u)),
  platforms: Schema.Record(Schema.String, StaticReleaseAsset),
})
export type StaticReleaseManifest = typeof StaticReleaseManifest.Type
