import { type as arkType } from "arktype";
import { findFileInDiff, parseFileDiffs, type DiffHunk, type ParsedFile } from "./diff.js";
import { normalizedProposalSchema, type NormalizedProposal } from "./schema.js";

export type HunkSelector =
    | { readonly type: "all" }
    | { readonly type: "indices"; readonly indices: readonly number[] }
    | { readonly type: "lines"; readonly start: number; readonly end: number };

export interface CommitChange {
    readonly path: string;
    readonly hunks: HunkSelector;
}

export interface CommitGroup {
    readonly summary: string;
    readonly details: readonly string[];
    readonly changes: readonly CommitChange[];
}

export interface CommitProposal {
    readonly commits: readonly CommitGroup[];
}

const MAX_COMMITS = 16;
const MAX_CHANGES_PER_COMMIT = 128;
const MAX_DETAILS = 32;
const MAX_SUMMARY_LENGTH = 512;
const MAX_DETAIL_LENGTH = 2_000;
const MAX_PATH_LENGTH = 4_096;

const invalid = (message: string): never => {
    throw new TypeError(`Invalid autommit proposal: ${message}`);
};

const boundedText = (value: unknown, field: string, maximum: number): string => {
    const text = typeof value === "string" ? value.trim() : invalid(`${field} must be a string`);
    if (!text || text.length > maximum || /[\u0000-\u001f\u007f]/u.test(text)) {
        invalid(`${field} must be non-empty, bounded text`);
    }
    return text;
};

const normalizePath = (value: unknown): string => {
    const path = boundedText(value, "change.path", MAX_PATH_LENGTH);
    if (
        path.startsWith("/") ||
        path.startsWith("\\") ||
        path.includes("\\") ||
        path === "." ||
        path === ".." ||
        path.split("/").some(component => component === "..")
    ) {
        invalid(`unsupported change path: ${path}`);
    }
    return path;
};

type NormalizedSelector = NormalizedProposal["commits"][number]["changes"][number]["hunks"];
type NormalizedCommit = NormalizedProposal["commits"][number];

const normalizeSelector = (value: NormalizedSelector): HunkSelector => {
    if (value === "all") return { type: "all" };
    if (value.type === "indices") {
        if (value.indices.length === 0) invalid("indices selector must contain a non-empty array");
        if (value.indices.some(index => index < 1)) invalid("hunk indices must be positive integers");
        if (new Set(value.indices).size !== value.indices.length) invalid("hunk indices must be unique");
        return { type: "indices", indices: [...value.indices].sort((left, right) => left - right) };
    }
    if (value.end < value.start) invalid("line selectors require a positive integer start <= end");
    return { type: "lines", start: value.start, end: value.end };
};

const normalizeGroup = (value: NormalizedCommit, index: number): CommitGroup => {
    const details = value.details ?? [];
    if (value.changes.length === 0 || value.changes.length > MAX_CHANGES_PER_COMMIT) {
        invalid(`commit ${index + 1} must contain between 1 and ${MAX_CHANGES_PER_COMMIT} changes`);
    }
    if (details.length > MAX_DETAILS) {
        invalid(`commit ${index + 1} details must be an array of at most ${MAX_DETAILS} items`);
    }
    const changes = value.changes.map(change => ({
        path: normalizePath(change.path),
        hunks: normalizeSelector(change.hunks),
    }));
    const paths = new Set<string>();
    for (const change of changes) {
        if (paths.has(change.path)) invalid(`commit ${index + 1} lists ${change.path} more than once`);
        paths.add(change.path);
    }
    return {
        summary: boundedText(value.summary, `commit ${index + 1} summary`, MAX_SUMMARY_LENGTH),
        details: details.map((detail, detailIndex) =>
            boundedText(detail, `commit ${index + 1} detail ${detailIndex + 1}`, MAX_DETAIL_LENGTH)),
        changes,
    };
};

export const normalizeProposal = (value: unknown): CommitProposal => {
    const result = normalizedProposalSchema(value);
    if (!(result instanceof arkType.errors) && "commits" in result) {
        if (result.commits.length === 0 || result.commits.length > MAX_COMMITS) {
            invalid(`commits must contain between 1 and ${MAX_COMMITS} entries`);
        }
        return { commits: result.commits.map((commit, index) => normalizeGroup(commit, index)) };
    }
    if (result instanceof arkType.errors) invalid(result.summary);
    return invalid("expected exactly a commits array");
};

const extractJsonCandidate = (text: string): string => {
    const trimmed = text.trim();
    const fenced = /```(?:json)?\s*([\s\S]*?)\s*```/iu.exec(trimmed);
    if (fenced?.[1]) return fenced[1].trim();
    const start = trimmed.indexOf("{");
    const end = trimmed.lastIndexOf("}");
    if (start >= 0 && end > start) return trimmed.slice(start, end + 1);
    return trimmed;
};

export const parseJsonText = (text: string): unknown => {
    try {
        return JSON.parse(extractJsonCandidate(text)) as unknown;
    } catch (error) {
        throw new TypeError(
            `Invalid autommit JSON: ${error instanceof Error ? error.message : String(error)}`,
        );
    }
};

export const parseProposalText = (text: string): CommitProposal => {
    return normalizeProposal(parseJsonText(text));
};

const selectionsOverlap = (left: HunkSelector, right: HunkSelector): boolean => {
    if (left.type === "all" || right.type === "all") return true;
    if (left.type === "indices" && right.type === "indices") {
        const selected = new Set(left.indices);
        return right.indices.some(index => selected.has(index));
    }
    if (left.type === "lines" && right.type === "lines") {
        return left.start <= right.end && right.start <= left.end;
    }
    return true;
};

const describeSelector = (selector: HunkSelector): string => {
    if (selector.type === "all") return "all";
    if (selector.type === "indices") return `hunks ${selector.indices.join(",")}`;
    return `new-file lines ${selector.start}-${selector.end}`;
};

const changedNewLines = (hunk: DiffHunk): number[] => {
    const changed: number[] = [];
    let newLine = hunk.newStart;
    for (const line of hunk.content.split("\n").slice(1)) {
        const marker = line[0];
        if (marker === "+") {
            changed.push(newLine);
            newLine += 1;
        } else if (marker === " ") {
            newLine += 1;
        }
    }
    return changed.length > 0 ? changed : [hunk.newStart];
};

const selectorIntersectsHunk = (selector: HunkSelector, hunk: DiffHunk): boolean => {
    if (selector.type === "all") return true;
    if (selector.type === "indices") return selector.indices.includes(hunk.index);
    const hunkEnd = hunk.newLines === 0 ? hunk.newStart : hunk.newStart + hunk.newLines - 1;
    return hunk.newStart <= selector.end && selector.start <= hunkEnd;
};

export const validateProposalCoverage = (
    proposal: CommitProposal,
    stagedFiles: readonly string[],
    parsedFiles: readonly ParsedFile[],
): string[] => {
    const stagedSet = new Set(stagedFiles);
    const selectionsByFile = new Map<string, HunkSelector[]>();
    const errors: string[] = [];

    for (const [commitIndex, commit] of proposal.commits.entries()) {
        for (const change of commit.changes) {
            if (!stagedSet.has(change.path)) {
                errors.push(`Commit ${commitIndex + 1}: file is not staged: ${change.path}`);
                continue;
            }
            const selections = selectionsByFile.get(change.path) ?? [];
            selectionsByFile.set(change.path, [...selections, change.hunks]);
        }
    }

    for (const file of stagedFiles) {
        if (!selectionsByFile.has(file)) errors.push(`Staged file missing from split plan: ${file}`);
    }

    for (const [file, selections] of selectionsByFile) {
        for (let leftIndex = 0; leftIndex < selections.length; leftIndex += 1) {
            const left = selections[leftIndex];
            if (!left) continue;
            for (const right of selections.slice(leftIndex + 1)) {
                if (selectionsOverlap(left, right)) {
                    errors.push(
                        `Overlapping hunk selections across commits: ${file} (${describeSelector(left)} overlaps ${describeSelector(right)}); line ranges are inclusive new-file ranges and must be disjoint`,
                    );
                    break;
                }
            }
        }

        const parsed = findFileInDiff(parsedFiles, file);
        if (!parsed) {
            errors.push(`No staged diff found for ${file}`);
            continue;
        }
        if (parsed.isBinary && selections.some(selection => selection.type !== "all")) {
            errors.push(`Binary file cannot be partially selected: ${file}`);
        }
        if (parsed.hunks.length === 0 && selections.some(selection => selection.type !== "all")) {
            errors.push(`Metadata-only file cannot be partially selected: ${file}`);
        }
        for (const hunk of parsed.hunks) {
            const covered = changedNewLines(hunk).every(line =>
                selections.some(selection =>
                    selection.type === "lines"
                        ? selection.start <= line && line <= selection.end
                        : selectorIntersectsHunk(selection, hunk),
                ),
            );
            if (!covered) errors.push(`Staged hunk missing from split plan: ${file} (hunk ${hunk.index})`);
        }
    }

    return [...new Set(errors)];
};

export const selectPatch = (file: ParsedFile, selector: HunkSelector): string => {
    if (file.isBinary && selector.type !== "all") {
        throw new Error(`Cannot partially select binary file ${file.filename}.`);
    }
    const hunks = selector.type === "all"
        ? file.hunks
        : selector.type === "indices"
            ? file.hunks.filter(hunk => selector.indices.includes(hunk.index))
            : file.hunks.filter(hunk => {
                const end = hunk.newLines === 0 ? hunk.newStart : hunk.newStart + hunk.newLines - 1;
                return hunk.newStart <= selector.end && selector.start <= end;
            });
    if (hunks.length === 0) {
        if (selector.type === "all") return file.content;
        throw new Error(`No changes selected for ${file.filename}.`);
    }
    if (selector.type === "all") return file.content;
    const firstHunk = file.content.indexOf("\n@@");
    const header = firstHunk < 0 ? file.content : file.content.slice(0, firstHunk);
    return [header, ...hunks.map(hunk => hunk.content)].join("\n");
};

export const buildCommitPatch = (
    changes: readonly CommitChange[],
    stagedDiff: string,
    zeroContextDiff: string,
): string => {
    const regularFiles = new Map(parseFileDiffs(stagedDiff).map(file => [file.filename, file] as const));
    const zeroFiles = new Map(parseFileDiffs(zeroContextDiff).map(file => [file.filename, file] as const));
    const parts = changes.map(change => {
        const files = change.hunks.type === "lines" ? zeroFiles : regularFiles;
        const file = files.get(change.path);
        if (!file) throw new Error(`No staged diff found for ${change.path}.`);
        return selectPatch(file, change.hunks);
    });
    return `${parts.join("\n")}\n`;
};
