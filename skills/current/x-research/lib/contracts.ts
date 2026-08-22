import {
  CliError,
  CompleteReason,
  ContractError,
  FeedChoice,
  MediaItem,
  PostAuthor,
  PostData,
  ProfileData,
  RankingChoice,
} from "#models";

const SAFE_HANDLE_RE = /^[A-Za-z0-9_]+$/;
const NUMERIC_ID_RE = /^[0-9]+$/;
const STATUS_PATH_RE = /^\/[A-Za-z0-9_]+\/status\/([0-9]+)\/?$/;
const METRIC_FIELDS = ["replies", "reposts", "likes", "quotes", "bookmarks", "views"] as const;
const MEDIA_COLLECTIONS = ["all", "photos", "videos"] as const;
const MEDIA_OBJECTS = ["external", "mosaic", "broadcast"] as const;

export function actualType(value: unknown): string {
  if (value === null) return "null";
  if (value === undefined) return "undefined";
  if (typeof value === "boolean") return "boolean";
  if (typeof value === "string") return "string";
  if (typeof value === "number") return "number";
  if (Array.isArray(value)) return "array";
  if (typeof value === "object") return "object";
  return typeof value;
}

function makeContractError(
  code: string,
  message: string,
  field: string,
  expected: string,
  value: unknown,
  index?: number
): ContractError {
  const details: Record<string, unknown> = {
    field,
    expected,
    actual_type: actualType(value),
    value,
  };
  if (index !== undefined) {
    details["index"] = index;
  }
  return new ContractError({ code, message, details });
}

export function validateHandle(raw: unknown): string {
  if (typeof raw !== "string" || !raw || !SAFE_HANDLE_RE.test(raw)) {
    throw new CliError({
      code: "invalid_handle",
      message: "handle must contain only letters, digits, and underscores",
      details: { handle: raw },
    });
  }
  return raw;
}

export function validateNumericId(raw: unknown, field: string = "id"): string {
  if (typeof raw !== "string" || !raw || !NUMERIC_ID_RE.test(raw)) {
    throw new CliError({
      code: "invalid_field",
      message: `${field} must be a numeric ID`,
      details: { field, value: raw },
    });
  }
  return raw;
}

export function statusIdFromTarget(raw: unknown): { id: string; targetUrl?: string } {
  if (typeof raw !== "string" || !raw || !raw.trim()) {
    throw new CliError({
      code: "invalid_target",
      message: "target must be a numeric ID or an https x.com/twitter.com status URL",
      details: { target: raw },
    });
  }
  if (NUMERIC_ID_RE.test(raw)) {
    return { id: raw };
  }

  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new CliError({
      code: "invalid_target",
      message: "target must be a numeric ID or an https x.com/twitter.com status URL",
      details: { target: raw },
    });
  }

  if (parsed.protocol !== "https:") {
    throw new CliError({
      code: "invalid_target",
      message: "target must be a numeric ID or an https x.com/twitter.com status URL",
      details: { target: raw },
    });
  }

  const hostname = parsed.hostname;
  if (hostname !== "x.com" && hostname !== "twitter.com") {
    throw new CliError({
      code: "invalid_target",
      message: "target must be a numeric ID or an https x.com/twitter.com status URL",
      details: { target: raw },
    });
  }

  if (parsed.port || parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new CliError({
      code: "invalid_target",
      message: "target must be a numeric ID or an https x.com/twitter.com status URL",
      details: { target: raw },
    });
  }

  const match = STATUS_PATH_RE.exec(parsed.pathname);
  if (!match || !match[1]) {
    throw new CliError({
      code: "invalid_target",
      message: "target must be a numeric ID or an https x.com/twitter.com status URL",
      details: { target: raw },
    });
  }

  return { id: match[1], targetUrl: raw };
}

export function normalizeQuery(raw: unknown): string {
  if (typeof raw !== "string") {
    throw new CliError({
      code: "invalid_query",
      message: "query must contain non-whitespace text",
      details: { query: raw },
    });
  }
  const query = raw.split(/\s+/).filter(Boolean).join(" ");
  if (!query) {
    throw new CliError({
      code: "invalid_query",
      message: "query must contain non-whitespace text",
      details: { query: raw },
    });
  }
  return query;
}

export function validateCount(requestedCount: unknown): number {
  if (typeof requestedCount !== "number" || !Number.isInteger(requestedCount)) {
    throw makeContractError(
      "invalid_count",
      "requested_count must be an integer from 1 to 100",
      "requested_count",
      "integer 1..100",
      requestedCount
    );
  }
  if (requestedCount < 1 || requestedCount > 100) {
    throw makeContractError(
      "invalid_count",
      "requested_count must be between 1 and 100",
      "requested_count",
      "integer 1..100",
      requestedCount
    );
  }
  return requestedCount;
}

export function validateCursor(raw: unknown): string {
  if (typeof raw !== "string" || !raw.trim()) {
    throw new CliError({
      code: "usage",
      message: "cursor must not be empty",
      details: {},
    });
  }
  return raw;
}

export function validateLang(raw: unknown): string {
  if (typeof raw !== "string" || !raw.trim()) {
    throw new CliError({
      code: "usage",
      message: "lang must not be empty",
      details: {},
    });
  }
  return raw;
}

export function validateFeed(raw: unknown): FeedChoice {
  if (raw === "latest" || raw === "top" || raw === "media") {
    return raw;
  }
  throw new CliError({
    code: "usage",
    message: `invalid feed: ${raw}`,
    details: {},
  });
}

export function validateRankingMode(raw: unknown): RankingChoice {
  if (raw === "likes" || raw === "recency") {
    return raw;
  }
  throw new CliError({
    code: "usage",
    message: `invalid ranking mode: ${raw}`,
    details: {},
  });
}

export function validateProvider(raw: unknown): "fxtwitter" {
  if (raw === "fxtwitter") {
    return raw;
  }
  throw new CliError({
    code: "usage",
    message: `invalid provider: ${raw}`,
    details: {},
  });
}

function getObject(value: unknown, field: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw makeContractError(
      "malformed_payload",
      `${field} must be an object`,
      field,
      "object",
      value
    );
  }
  return value as Record<string, unknown>;
}

function requiredString(
  obj: Record<string, unknown>,
  key: string,
  field?: string,
  allowEmpty: boolean = false
): string {
  const path = field || key;
  if (!(key in obj) || obj[key] === undefined) {
    throw makeContractError("missing_field", `${path} is required`, path, "string", undefined);
  }
  const val = obj[key];
  if (typeof val !== "string") {
    throw makeContractError("invalid_field", `${path} must be a string`, path, "string", val);
  }
  if (!allowEmpty && !val) {
    throw makeContractError("invalid_field", `${path} must not be empty`, path, "non-empty string", val);
  }
  return val;
}

function optionalString(
  obj: Record<string, unknown>,
  key: string,
  allowEmpty: boolean = false
): string | undefined {
  if (!(key in obj) || obj[key] === null || obj[key] === undefined) {
    return undefined;
  }
  const val = obj[key];
  if (typeof val !== "string") {
    return undefined;
  }
  if (!allowEmpty && !val) {
    return undefined;
  }
  return val;
}

function getNumber(value: unknown): number | undefined {
  if (typeof value === "boolean") return undefined;
  if (typeof value === "number" && Number.isFinite(value) && value >= 0) {
    return value;
  }
  return undefined;
}

function normalizeVerification(raw: unknown): boolean | undefined {
  if (typeof raw === "object" && raw !== null && !Array.isArray(raw)) {
    const v = (raw as Record<string, unknown>)["verified"];
    return typeof v === "boolean" ? v : undefined;
  }
  return typeof raw === "boolean" ? raw : undefined;
}

export function normalizeProfile(raw: unknown, fieldName: string = "author"): ProfileData {
  const obj = getObject(raw, fieldName);
  const result: Record<string, unknown> = {};

  const idVal = optionalString(obj, "id");
  if (idVal !== undefined) result["id"] = idVal;

  const handleVal = optionalString(obj, "screen_name");
  if (handleVal !== undefined) result["handle"] = handleVal;

  const nameVal = optionalString(obj, "name");
  if (nameVal !== undefined) result["name"] = nameVal;

  const urlVal = optionalString(obj, "url");
  if (urlVal !== undefined) result["url"] = urlVal;

  let verified = normalizeVerification(obj["verification"]);
  if (verified === undefined && "verified" in obj) {
    verified = normalizeVerification(obj["verified"]);
  }
  if (verified !== undefined) {
    result["verified"] = verified;
  }

  if (!("id" in result) && !("handle" in result)) {
    throw makeContractError(
      "invalid_author",
      "author must include an id or screen_name",
      fieldName,
      "object with id or screen_name",
      raw
    );
  }

  return result as ProfileData;
}

function normalizeMediaItem(raw: unknown): MediaItem | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return undefined;
  }
  const obj = raw as Record<string, unknown>;
  const itemType = obj["type"];
  const itemUrl = obj["url"];
  if (typeof itemType !== "string" || typeof itemUrl !== "string") {
    return undefined;
  }
  const item: Record<string, unknown> = { type: itemType, url: itemUrl };

  for (const key of ["format", "thumbnail_url", "transcode_url", "altText"] as const) {
    const val = obj[key];
    if (typeof val === "string" && val) {
      item[key] = val;
    }
  }

  for (const key of ["width", "height", "duration", "filesize"] as const) {
    const num = getNumber(obj[key]);
    if (num !== undefined) {
      item[key] = num;
    }
  }

  if (itemType === "video" || itemType === "gif") {
    const formats = obj["formats"];
    if (Array.isArray(formats)) {
      const normalizedFormats: Record<string, unknown>[] = [];
      for (const candidate of formats) {
        if (typeof candidate === "object" && candidate !== null && !Array.isArray(candidate)) {
          const cObj = candidate as Record<string, unknown>;
          const normalized: Record<string, unknown> = {};
          for (const key of ["container", "codec", "url"] as const) {
            const val = cObj[key];
            if (typeof val === "string" && val) {
              normalized[key] = val;
            }
          }
          for (const key of ["bitrate", "size", "height", "width"] as const) {
            const num = getNumber(cObj[key]);
            if (num !== undefined) {
              normalized[key] = num;
            }
          }
          if (typeof normalized["url"] === "string") {
            normalizedFormats.push(normalized);
          }
        }
      }
      if (normalizedFormats.length > 0) {
        item["formats"] = normalizedFormats;
      }
    } else if (typeof formats === "object" && formats !== null) {
      const fObj = formats as Record<string, unknown>;
      const normalizedFormatsObj: Record<string, string> = {};
      for (const key of ["webp", "jpeg"] as const) {
        const val = fObj[key];
        if (typeof val === "string" && val) {
          normalizedFormatsObj[key] = val;
        }
      }
      if (Object.keys(normalizedFormatsObj).length > 0) {
        item["formats"] = [normalizedFormatsObj];
      }
    }
  }

  return item as MediaItem;
}

function normalizeMediaObject(raw: unknown): Record<string, unknown> | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return undefined;
  }
  const obj = raw as Record<string, unknown>;
  const normalized = normalizeMediaItem(raw);
  if (normalized) {
    if (typeof obj["state"] === "string" && obj["state"]) {
      (normalized as Record<string, unknown>)["state"] = obj["state"];
    }
    if (typeof obj["title"] === "string" && obj["title"]) {
      (normalized as Record<string, unknown>)["title"] = obj["title"];
    }
    return normalized as Record<string, unknown>;
  }
  return undefined;
}

function normalizeMedia(raw: unknown): Record<string, unknown> | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return undefined;
  }
  const obj = raw as Record<string, unknown>;
  const media: Record<string, unknown> = {};

  for (const key of MEDIA_COLLECTIONS) {
    const candidates = obj[key];
    if (Array.isArray(candidates)) {
      const items: MediaItem[] = [];
      for (const v of candidates) {
        const item = normalizeMediaItem(v);
        if (item) items.push(item);
      }
      if (items.length > 0) {
        media[key] = items;
      }
    }
  }

  for (const key of MEDIA_OBJECTS) {
    const normalized = normalizeMediaObject(obj[key]);
    if (normalized) {
      media[key] = normalized;
    }
  }

  return Object.keys(media).length > 0 ? media : undefined;
}

export function normalizePost(raw: unknown, fieldName: string = "post"): PostData {
  const obj = getObject(raw, fieldName);
  const id = requiredString(obj, "id", `${fieldName}.id`, false);
  const url = requiredString(obj, "url", `${fieldName}.url`, false);
  const text = requiredString(obj, "text", `${fieldName}.text`, true);
  const createdAt = requiredString(obj, "created_at", `${fieldName}.created_at`, false);

  if (!("author" in obj) || obj["author"] === undefined) {
    throw makeContractError(
      "missing_field",
      `${fieldName}.author is required`,
      `${fieldName}.author`,
      "object",
      undefined
    );
  }
  const author = normalizeProfile(obj["author"], `${fieldName}.author`) as PostAuthor;

  const result: Record<string, unknown> = {
    id,
    url,
    text,
    created_at: createdAt,
    author,
  };

  const metricsObj = obj["metrics"];
  if (typeof metricsObj === "object" && metricsObj !== null && !Array.isArray(metricsObj)) {
    const mObj = metricsObj as Record<string, unknown>;
    const metrics: Record<string, number> = {};
    for (const key of METRIC_FIELDS) {
      const num = getNumber(mObj[key]);
      if (num !== undefined) {
        metrics[key] = num;
      }
    }
    if (Object.keys(metrics).length > 0) {
      result["metrics"] = metrics;
    }
  }

  const lang = optionalString(obj, "lang");
  if (lang !== undefined) {
    result["lang"] = lang;
  }

  const media = normalizeMedia(obj["media"]);
  if (media !== undefined) {
    result["media"] = media;
  }

  let quoteId: string | undefined;
  const quoteObj = obj["quote"];
  if (typeof quoteObj === "object" && quoteObj !== null && !Array.isArray(quoteObj)) {
    quoteId = optionalString(quoteObj as Record<string, unknown>, "id");
  }
  if (quoteId === undefined) {
    quoteId = optionalString(obj, "quote_id");
  }
  if (quoteId !== undefined) {
    result["quote_id"] = quoteId;
  }

  let replyToId: string | undefined;
  const replyingToObj = obj["replying_to"];
  if (typeof replyingToObj === "object" && replyingToObj !== null && !Array.isArray(replyingToObj)) {
    replyToId = optionalString(replyingToObj as Record<string, unknown>, "status");
  }
  if (replyToId === undefined) {
    replyToId = optionalString(obj, "reply_to_id");
  }
  if (replyToId !== undefined) {
    result["reply_to_id"] = replyToId;
  }

  return result as PostData;
}

export function normalizeStatusPayload(payload: unknown): { post: PostData } {
  const root = getObject(payload, "payload");
  if (!("status" in root) || root["status"] === undefined) {
    throw makeContractError("missing_field", "status payload must include status", "status", "object", undefined);
  }
  const status = root["status"];
  if (typeof status !== "object" || status === null || Array.isArray(status)) {
    throw makeContractError("invalid_status", "status payload status must be an object", "status", "object", status);
  }
  return { post: normalizePost(status) };
}

function bottomCursor(root: Record<string, unknown>): [string | undefined, "usable" | "exhausted" | "missing" | "invalid"] {
  if (!("cursor" in root) || root["cursor"] === undefined) {
    return [undefined, "missing"];
  }
  const cursor = root["cursor"];
  if (cursor === null) {
    return [undefined, "exhausted"];
  }
  if (typeof cursor === "object" && !Array.isArray(cursor)) {
    const cObj = cursor as Record<string, unknown>;
    if (!("bottom" in cObj)) {
      return [undefined, "invalid"];
    }
    const bottom = cObj["bottom"];
    if (bottom === null) {
      return [undefined, "exhausted"];
    }
    if (typeof bottom === "string" && bottom.length > 0) {
      return [bottom, "usable"];
    }
    return [undefined, "invalid"];
  }
  return [undefined, "invalid"];
}

export function normalizePagePayload(payload: unknown, requestedCount: number): {
  posts: PostData[];
  requested_count: number;
  returned_count: number;
  profile?: ProfileData;
  cursor?: string;
  has_more?: boolean;
  complete: boolean;
  complete_reason: CompleteReason;
} {
  const count = validateCount(requestedCount);
  const root = getObject(payload, "payload");

  if (!("results" in root) || root["results"] === undefined) {
    throw makeContractError("missing_field", "page payload must include results", "results", "array", undefined);
  }
  const rawResults = root["results"];
  if (!Array.isArray(rawResults)) {
    throw makeContractError("invalid_results", "results must be an array", "results", "array", rawResults);
  }

  const posts: PostData[] = [];
  for (let i = 0; i < rawResults.length; i++) {
    try {
      posts.push(normalizePost(rawResults[i]));
    } catch (err) {
      if (err instanceof ContractError) {
        const details = { ...err.details };
        if (!("index" in details)) {
          details["index"] = i;
        }
        throw new ContractError({
          code: err.code,
          message: err.message,
          details,
        });
      }
      throw err;
    }
  }

  const limitedPosts = posts.length > count ? posts.slice(0, count) : posts;
  const result: {
    posts: PostData[];
    requested_count: number;
    returned_count: number;
    profile?: ProfileData;
    cursor?: string;
    has_more?: boolean;
    complete: boolean;
    complete_reason: CompleteReason;
  } = {
    posts: limitedPosts,
    requested_count: count,
    returned_count: limitedPosts.length,
    complete: false,
    complete_reason: "provider_incomplete",
  };

  if ("profile" in root && root["profile"] != null) {
    result.profile = normalizeProfile(root["profile"], "profile");
  }

  const [bottom, cursorState] = bottomCursor(root);
  if (cursorState === "usable" && bottom) {
    result.cursor = bottom;
    result.has_more = true;
    result.complete = false;
    result.complete_reason = "bounded_page";
  } else if (cursorState === "exhausted") {
    result.complete = true;
    result.complete_reason = "provider_exhausted";
  } else {
    result.complete = false;
    result.complete_reason = "provider_incomplete";
  }

  return result;
}

function normalizeStatusList(raw: unknown, fieldName: string): PostData[] {
  if (!Array.isArray(raw)) {
    throw makeContractError("invalid_results", `conversation ${fieldName} must be an array`, fieldName, "array", raw);
  }
  const normalized: PostData[] = [];
  for (let i = 0; i < raw.length; i++) {
    try {
      normalized.push(normalizePost(raw[i]));
    } catch (err) {
      if (err instanceof ContractError) {
        const details = { ...err.details };
        if (!("index" in details)) {
          details["index"] = i;
        }
        throw new ContractError({
          code: err.code,
          message: err.message,
          details,
        });
      }
      throw err;
    }
  }
  return normalized;
}

export function normalizeConversationPayload(payload: unknown): {
  target: PostData;
  thread: PostData[];
  replies: PostData[];
  returned_count: number;
  cursor?: string;
  has_more?: boolean;
  complete: boolean;
  complete_reason: CompleteReason;
} {
  const root = getObject(payload, "payload");

  if (!("status" in root) || root["status"] === undefined) {
    throw makeContractError("missing_field", "conversation payload must include status", "status", "object", undefined);
  }
  const status = root["status"];
  if (typeof status !== "object" || status === null || Array.isArray(status)) {
    throw makeContractError("invalid_status", "conversation status must be an object", "status", "object", status);
  }
  const target = normalizePost(status);

  if (!("thread" in root) || root["thread"] === undefined) {
    throw makeContractError("missing_field", "conversation payload must include thread", "thread", "array", undefined);
  }
  const thread = normalizeStatusList(root["thread"], "thread");

  if (!("replies" in root) || root["replies"] === undefined) {
    throw makeContractError("missing_field", "conversation payload must include replies", "replies", "array", undefined);
  }
  const replies = normalizeStatusList(root["replies"], "replies");

  const result: {
    target: PostData;
    thread: PostData[];
    replies: PostData[];
    returned_count: number;
    cursor?: string;
    has_more?: boolean;
    complete: boolean;
    complete_reason: CompleteReason;
  } = {
    target,
    thread,
    replies,
    returned_count: 1 + thread.length + replies.length,
    complete: false,
    complete_reason: "provider_incomplete",
  };

  const [bottom, cursorState] = bottomCursor(root);
  if (cursorState === "usable" && bottom) {
    result.cursor = bottom;
    result.has_more = true;
    result.complete = false;
    result.complete_reason = "bounded_page";
  } else if (cursorState === "exhausted") {
    result.complete = true;
    result.complete_reason = "provider_exhausted";
  } else {
    result.complete = false;
    result.complete_reason = "provider_incomplete";
  }

  return result;
}
