const SUMMARY_ROOT_FIELDS = [
  "requested_id",
  "requested_url",
  "handle",
  "query",
  "feed",
  "ranking_mode",
  "requested_count",
  "returned_count",
  "cursor",
  "has_more",
  "complete",
  "complete_reason",
  "provider",
  "official",
  "auth_mode",
  "source_url",
  "endpoint",
  "fetched_at",
  "provider_status",
] as const;

export function summaryAuthor(author: Record<string, unknown>): Record<string, unknown> {
  const summary: Record<string, unknown> = {};
  for (const key of ["id", "handle", "name", "url", "verified"] as const) {
    if (key in author && author[key] !== undefined) {
      summary[key] = author[key];
    }
  }
  return summary;
}

export function summaryPost(post: Record<string, unknown>): Record<string, unknown> {
  const summary: Record<string, unknown> = {};
  for (const key of ["id", "url", "text", "created_at", "lang", "quote_id", "reply_to_id"] as const) {
    if (key in post && post[key] !== undefined) {
      summary[key] = post[key];
    }
  }
  if ("author" in post && typeof post["author"] === "object" && post["author"] !== null) {
    summary["author"] = summaryAuthor(post["author"] as Record<string, unknown>);
  }
  return summary;
}

export function summaryPostValue(value: unknown): unknown {
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    return summaryPost(value as Record<string, unknown>);
  }
  if (Array.isArray(value)) {
    return value
      .filter((item) => typeof item === "object" && item !== null && !Array.isArray(item))
      .map((item) => summaryPost(item as Record<string, unknown>));
  }
  return undefined;
}

export function summaryData(_command: string, data: Record<string, unknown>): Record<string, unknown> {
  const summary: Record<string, unknown> = {};
  for (const key of SUMMARY_ROOT_FIELDS) {
    if (key in data && data[key] !== undefined) {
      summary[key] = data[key];
    }
  }
  for (const key of ["post", "posts", "target", "thread", "replies"] as const) {
    if (!(key in data) || data[key] === undefined) {
      continue;
    }
    const projected = summaryPostValue(data[key]);
    if (projected !== undefined) {
      summary[key] = projected;
    }
  }
  if ("profile" in data && typeof data["profile"] === "object" && data["profile"] !== null) {
    summary["profile"] = summaryAuthor(data["profile"] as Record<string, unknown>);
  }
  return summary;
}
