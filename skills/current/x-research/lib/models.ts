import { Schema } from "effect";

export const SCHEMA_VERSION = 1 as const;
export const PROVIDER_NAME = "fxtwitter" as const;
export const DEFAULT_BASE_URL = "https://api.fxtwitter.com" as const;
export const DEFAULT_TIMEOUT = 10 as const;

export const CommandName = Schema.Literals(["fetch", "user-posts", "search", "conversation"]);
export type CommandName = typeof CommandName.Type;

export const FeedChoice = Schema.Literals(["latest", "top", "media"]);
export type FeedChoice = typeof FeedChoice.Type;

export const RankingChoice = Schema.Literals(["likes", "recency"]);
export type RankingChoice = typeof RankingChoice.Type;

export const CompleteReason = Schema.Literals(["bounded_page", "provider_exhausted", "provider_incomplete"]);
export type CompleteReason = typeof CompleteReason.Type;

export class CliError extends Schema.TaggedError<CliError>()("CliError", {
  code: Schema.String,
  message: Schema.String,
  details: Schema.Record(Schema.String, Schema.Unknown),
}) {}

export class ProviderError extends Schema.TaggedError<ProviderError>()("ProviderError", {
  code: Schema.String,
  message: Schema.String,
  details: Schema.Record(Schema.String, Schema.Unknown),
}) {}

export class ContractError extends Schema.TaggedError<ContractError>()("ContractError", {
  code: Schema.String,
  message: Schema.String,
  details: Schema.Record(Schema.String, Schema.Unknown),
}) {}

export const PostAuthor = Schema.Struct({
  id: Schema.optional(Schema.String),
  handle: Schema.optional(Schema.String),
  name: Schema.optional(Schema.String),
  url: Schema.optional(Schema.String),
  verified: Schema.optional(Schema.Boolean),
});
export type PostAuthor = typeof PostAuthor.Type;

export const ProfileData = Schema.Struct({
  id: Schema.optional(Schema.String),
  handle: Schema.optional(Schema.String),
  name: Schema.optional(Schema.String),
  url: Schema.optional(Schema.String),
  verified: Schema.optional(Schema.Boolean),
});
export type ProfileData = typeof ProfileData.Type;

export const PostMetrics = Schema.Struct({
  replies: Schema.optional(Schema.Number),
  reposts: Schema.optional(Schema.Number),
  likes: Schema.optional(Schema.Number),
  quotes: Schema.optional(Schema.Number),
  bookmarks: Schema.optional(Schema.Number),
  views: Schema.optional(Schema.Number),
});
export type PostMetrics = typeof PostMetrics.Type;

export const MediaItem = Schema.Struct({
  type: Schema.String,
  url: Schema.String,
  width: Schema.optional(Schema.Number),
  height: Schema.optional(Schema.Number),
  altText: Schema.optional(Schema.String),
  duration: Schema.optional(Schema.Number),
  thumbnail_url: Schema.optional(Schema.String),
  format: Schema.optional(Schema.String),
  formats: Schema.optional(Schema.Array(Schema.Record(Schema.String, Schema.Unknown))),
});
export type MediaItem = typeof MediaItem.Type;

export const PostData = Schema.Struct({
  id: Schema.String,
  url: Schema.String,
  text: Schema.String,
  created_at: Schema.String,
  author: PostAuthor,
  metrics: Schema.optional(PostMetrics),
  lang: Schema.optional(Schema.String),
  media: Schema.optional(Schema.Record(Schema.String, Schema.Unknown)),
  quote_id: Schema.optional(Schema.String),
  reply_to_id: Schema.optional(Schema.String),
});
export type PostData = typeof PostData.Type;

export const ProvenanceData = Schema.Struct({
  provider: Schema.Literal("fxtwitter"),
  official: Schema.Literal(false),
  auth_mode: Schema.Literal("none"),
  source_url: Schema.String,
  endpoint: Schema.String,
  fetched_at: Schema.String,
  provider_status: Schema.Number,
});
export type ProvenanceData = typeof ProvenanceData.Type;

export const FetchData = Schema.Struct({
  requested_id: Schema.optional(Schema.String),
  requested_url: Schema.optional(Schema.String),
  post: PostData,
  provider: Schema.Literal("fxtwitter"),
  official: Schema.Literal(false),
  auth_mode: Schema.Literal("none"),
  source_url: Schema.String,
  endpoint: Schema.String,
  fetched_at: Schema.String,
  provider_status: Schema.Number,
});
export type FetchData = typeof FetchData.Type;

export const UserPostsData = Schema.Struct({
  handle: Schema.String,
  profile: Schema.optional(ProfileData),
  requested_count: Schema.Number,
  returned_count: Schema.Number,
  cursor: Schema.optional(Schema.String),
  has_more: Schema.optional(Schema.Boolean),
  complete: Schema.Boolean,
  complete_reason: CompleteReason,
  posts: Schema.Array(PostData),
  provider: Schema.Literal("fxtwitter"),
  official: Schema.Literal(false),
  auth_mode: Schema.Literal("none"),
  source_url: Schema.String,
  endpoint: Schema.String,
  fetched_at: Schema.String,
  provider_status: Schema.Number,
});
export type UserPostsData = typeof UserPostsData.Type;

export const SearchData = Schema.Struct({
  query: Schema.String,
  feed: FeedChoice,
  requested_count: Schema.Number,
  returned_count: Schema.Number,
  cursor: Schema.optional(Schema.String),
  has_more: Schema.optional(Schema.Boolean),
  complete: Schema.Boolean,
  complete_reason: CompleteReason,
  posts: Schema.Array(PostData),
  provider: Schema.Literal("fxtwitter"),
  official: Schema.Literal(false),
  auth_mode: Schema.Literal("none"),
  source_url: Schema.String,
  endpoint: Schema.String,
  fetched_at: Schema.String,
  provider_status: Schema.Number,
});
export type SearchData = typeof SearchData.Type;

export const ConversationData = Schema.Struct({
  requested_id: Schema.String,
  ranking_mode: RankingChoice,
  returned_count: Schema.Number,
  cursor: Schema.optional(Schema.String),
  has_more: Schema.optional(Schema.Boolean),
  complete: Schema.Boolean,
  complete_reason: CompleteReason,
  target: PostData,
  thread: Schema.Array(PostData),
  replies: Schema.Array(PostData),
  provider: Schema.Literal("fxtwitter"),
  official: Schema.Literal(false),
  auth_mode: Schema.Literal("none"),
  source_url: Schema.String,
  endpoint: Schema.String,
  fetched_at: Schema.String,
  provider_status: Schema.Number,
});
export type ConversationData = typeof ConversationData.Type;

export const CommandData = Schema.Union([FetchData, UserPostsData, SearchData, ConversationData, Schema.Record(Schema.String, Schema.Unknown)]);
export type CommandData = typeof CommandData.Type;

export const SuccessEnvelope = Schema.Struct({
  ok: Schema.Literal(true),
  schema_version: Schema.Literal(1),
  command: Schema.String,
  data: Schema.Record(Schema.String, Schema.Unknown),
});
export type SuccessEnvelope = typeof SuccessEnvelope.Type;

export const FailureErrorObject = Schema.Struct({
  code: Schema.String,
  message: Schema.String,
  details: Schema.Record(Schema.String, Schema.Unknown),
});
export type FailureErrorObject = typeof FailureErrorObject.Type;

export const FailureEnvelope = Schema.Struct({
  ok: Schema.Literal(false),
  schema_version: Schema.Literal(1),
  command: Schema.String,
  error: FailureErrorObject,
});
export type FailureEnvelope = typeof FailureEnvelope.Type;

export const ResponseEnvelope = Schema.Union([SuccessEnvelope, FailureEnvelope]);
export type ResponseEnvelope = typeof ResponseEnvelope.Type;
