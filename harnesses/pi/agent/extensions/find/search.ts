/**
 * Pure helpers for `find`: query keywords, the lexical prior, line windows,
 * and file eligibility. Adapted from oh-my-pi's `find` (MIT, see LICENSE).
 */

const STOPWORDS = new Set(
  (
    "the a an or and to is are be when where how that this of in on at for with by its it as from into like " +
    "get gets up which what does do code file files over all user using then than there their they them you your " +
    "we our has have had was were been being will would should can could not but if so such via per any some each " +
    "every also just only more most other out off about after before between through during without within one two " +
    "new used use make makes made run runs way thing things something actually really still yet find implement " +
    "implements implementation handle handles logic"
  ).split(" "),
);

/** Cheap stem so substring matches cover inflections: spawned→spawn. */
function stem(token: string): string {
  for (const suffix of ["ing", "ed", "es", "s"]) {
    if (token.endsWith(suffix) && token.length - suffix.length >= 4) return token.slice(0, -suffix.length);
  }
  return token;
}

/** Lowercased lexical keywords: quoted phrases whole, then stemmed tokens minus stopwords. */
export function keywords(query: string): string[] {
  const out: string[] = [];
  const add = (word: string) => {
    if (word.length > 0 && !out.includes(word)) out.push(word);
  };
  const rest = query.replace(/(["'`])(.+?)\1/g, (_, _quote, phrase: string) => {
    if (phrase.trim().length >= 3) add(phrase.trim().toLowerCase());
    return " ";
  });
  for (const token of rest.split(/[^\p{L}\p{N}_]+/u)) {
    const lower = token.toLowerCase();
    if (lower.length < 3 || STOPWORDS.has(lower) || /^\d+$/.test(lower)) continue;
    add(stem(lower));
  }
  return out;
}

/** IDF per keyword, clamped so one rare fixture hit cannot beat a dense implementation. */
export function idf(counts: ReadonlyMap<string, readonly number[]>, keywordCount: number, files: number): number[] {
  return Array.from({ length: keywordCount }, (_, k) => {
    let df = 0;
    for (const row of counts.values()) if ((row[k] ?? 0) > 0) df++;
    return Math.min(6, Math.max(0.5, Math.log((files + 1) / (df + 1))));
  });
}

/** Lexical file rank: weighted log term frequency plus a bonus for keywords in the path. */
export function fileScore(
  counts: readonly number[] | undefined,
  weights: readonly number[],
  rel: string,
  words: readonly string[],
): number {
  const lower = rel.toLowerCase();
  let score = 0;
  words.forEach((word, k) => {
    score += weights[k]! * ((lower.includes(word) ? 2 : 0) + Math.log1p(counts?.[k] ?? 0));
  });
  return score;
}

function occurrences(haystack: string, needle: string): number {
  let count = 0;
  for (let at = haystack.indexOf(needle); at !== -1; at = haystack.indexOf(needle, at + needle.length)) count++;
  return count;
}

/** A run of whole source lines, 1-based inclusive. */
export interface Passage {
  start: number;
  end: number;
  text: string;
  score: number;
}

/** Cut `text` into contiguous whole-line windows of at most `bytes` (one long line is clipped). */
export function windows(text: string, bytes: number, words: readonly string[], weights: readonly number[]): Passage[] {
  const lines = text.split("\n");
  if (lines.at(-1) === "") lines.pop();
  const out: Passage[] = [];
  let start = 0;
  while (start < lines.length) {
    let end = start;
    let body = "";
    while (end < lines.length) {
      const line = lines[end]!.replace(/\r$/, "");
      if (end > start && Buffer.byteLength(body) + Buffer.byteLength(line) + 1 > bytes) break;
      body += `${end === start ? line.slice(0, bytes) : line}\n`;
      end++;
    }
    const lower = body.toLowerCase();
    let score = 0;
    words.forEach((word, k) => {
      score += weights[k]! * Math.log1p(occurrences(lower, word));
    });
    out.push({ start: start + 1, end, text: body, score });
    start = end;
  }
  return out;
}

/** The lexically strongest windows (evenly spread when none match), in file order. */
export function selectWindows(passages: readonly Passage[], limit: number): Passage[] {
  if (passages.length <= limit) return [...passages];
  let kept: Passage[];
  if (passages.every((passage) => passage.score === 0)) {
    const step = (passages.length - 1) / Math.max(limit - 1, 1);
    kept = [...new Set(Array.from({ length: limit }, (_, k) => Math.round(k * step)))].map((i) => passages[i]!);
  } else {
    kept = [...passages].sort((a, b) => b.score - a.score || a.start - b.start).slice(0, limit);
  }
  return kept.sort((a, b) => a.start - b.start);
}

const SKIP_NAMES = new Set([
  "Cargo.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock", "bun.lockb", "poetry.lock",
  "uv.lock", "Pipfile.lock", "composer.lock", "Gemfile.lock", "go.sum", "flake.lock",
  "credentials", "credentials.json", "id_rsa", "id_ed25519",
]);
const SKIP_DIRS = /(^|\/)(node_modules|dist|build|target|coverage|__pycache__|\.venv|venv)\//;
const SKIP_EXT =
  /\.(png|jpe?g|gif|webp|avif|ico|bmp|svg|woff2?|ttf|otf|eot|zip|gz|tgz|tar|bz2|xz|zst|7z|pdf|mp[34]|mov|wav|ogg|wasm|so|dylib|dll|exe|o|a|class|jar|pyc|bin|dat|db|sqlite3?|lock|map|min\.js|min\.css|snap|ipynb|pem|key|p12|pfx|kdbx|gpg|tfstate|tfvars)$/i;

/** Whether a root-relative path from `rg --files` is worth judging: no build output, lockfiles, binaries, or secrets. */
export function eligible(rel: string): boolean {
  const name = rel.slice(rel.lastIndexOf("/") + 1);
  if (SKIP_NAMES.has(name) || name.startsWith(".env") || SKIP_DIRS.test(rel) || SKIP_EXT.test(name)) return false;
  return true;
}
