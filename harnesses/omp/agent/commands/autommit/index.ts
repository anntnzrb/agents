import { existsSync } from "node:fs";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import type {
    CustomCommandFactory,
    ModelRegistry,
} from "@oh-my-pi/pi-coding-agent";
import {
    readReceipt,
    removeReceipt,
    withOperationLock,
    writeReceipt,
    type Receipt,
} from "./transaction";
import {
    ATOMICITY_CRITIC_SYSTEM_PROMPT,
    buildAtomicityCriticPrompt,
    normalizeAtomicityDecision,
    shouldReviewAtomicity,
    type AtomicityDecision,
    type AtomicityProposalInput,
} from "./atomicity";

import type {
    CommitAgentState,
    FileChange,
    SplitCommitGroup,
    SplitCommitPlan,
} from "@oh-my-pi/pi-coding-agent/commit/agentic/state";
import type * as AgenticValidation from "@oh-my-pi/pi-coding-agent/commit/agentic/validation";
import type { ConventionalDetail, FileDiff, FileHunks } from "@oh-my-pi/pi-coding-agent/commit/types";
import type { createCommitTools } from "@oh-my-pi/pi-coding-agent/commit/agentic/tools";
import type { parseFileDiffs, parseFileHunks } from "@oh-my-pi/pi-coding-agent/commit/git/diff";
import type { resolveRoleSelection, ScopedModel } from "@oh-my-pi/pi-coding-agent/config/model-resolver";
import type { Settings } from "@oh-my-pi/pi-coding-agent/config/settings";
import type { assignLockFilesToPlan } from "@oh-my-pi/pi-coding-agent/commit/agentic/lock-files";
import type { computeDependencyOrder } from "@oh-my-pi/pi-coding-agent/commit/agentic/topo-sort";
import type * as CommitUtils from "@oh-my-pi/pi-coding-agent/commit/utils";

type CommandAPI = Parameters<CustomCommandFactory>[0];

interface CommitInternals {
    readonly createCommitTools: typeof createCommitTools;
    readonly resolveRoleSelection: typeof resolveRoleSelection;
    readonly assignLockFilesToPlan: typeof assignLockFilesToPlan;
    readonly computeDependencyOrder: typeof computeDependencyOrder;
    readonly capDetails: typeof AgenticValidation.capDetails;
    readonly parseFileDiffs: typeof parseFileDiffs;
    readonly parseFileHunks: typeof parseFileHunks;
    readonly maxDetailItems: number;
    readonly normalizeDetails: typeof CommitUtils.normalizeDetails;
}

const PACKAGE_ROOT_HINTS = [
    process.env.PI_PACKAGE_DIR,
    process.argv[1] ? resolve(dirname(process.argv[1]), "..") : undefined,
    process.argv[1] ? resolve(dirname(process.argv[1]), "..", "@oh-my-pi", "pi-coding-agent") : undefined,
].filter((path): path is string => Boolean(path));

const locatePackageRoot = (): string => {
    const packageRoot = PACKAGE_ROOT_HINTS.find(path => existsSync(resolve(path, "src", "index.ts")));
    if (!packageRoot) {
        throw new Error("Cannot locate OMP package sources; set PI_PACKAGE_DIR to the pi-coding-agent package root.");
    }
    return packageRoot;
};

// OMP loads custom commands outside package module resolution, so hidden commit modules must be loaded by source path.
const loadInternal = async <T>(relativePath: string): Promise<T> =>
    (await import(pathToFileURL(resolve(locatePackageRoot(), "src", relativePath)).href)) as T;

const loadCommitInternals = async (): Promise<CommitInternals> => {
    const [tools, resolver, lockFiles, topoSort, validation, utils, diffParser] = await Promise.all([
        loadInternal<Pick<CommitInternals, "createCommitTools">>("commit/agentic/tools/index.ts"),
        loadInternal<Pick<CommitInternals, "resolveRoleSelection">>("config/model-resolver.ts"),
        loadInternal<Pick<CommitInternals, "assignLockFilesToPlan">>("commit/agentic/lock-files.ts"),
        loadInternal<Pick<CommitInternals, "computeDependencyOrder">>("commit/agentic/topo-sort.ts"),
        loadInternal<
            Pick<CommitInternals, "capDetails"> & { readonly MAX_DETAIL_ITEMS: number }
        >("commit/agentic/validation.ts"),
        loadInternal<Pick<CommitInternals, "normalizeDetails">>("commit/utils.ts"),
        loadInternal<Pick<CommitInternals, "parseFileDiffs" | "parseFileHunks">>("commit/git/diff.ts"),
    ]);
    return {
        createCommitTools: tools.createCommitTools,
        resolveRoleSelection: resolver.resolveRoleSelection,
        assignLockFilesToPlan: lockFiles.assignLockFilesToPlan,
        computeDependencyOrder: topoSort.computeDependencyOrder,
        capDetails: validation.capDetails,
        normalizeDetails: utils.normalizeDetails,
        maxDetailItems: validation.MAX_DETAIL_ITEMS,
        parseFileDiffs: diffParser.parseFileDiffs,
        parseFileHunks: diffParser.parseFileHunks,
    };
};
const COMMIT_AGENT_SYSTEM_PROMPT = [
    "You are an unattended repository commit agent.",
    "Use only supplied commit tools. Never ask questions or wait for input.",
    "Always call git_overview first. Do not use read.",
    "Use git_file_diff for key files; use git_hunk only for large diffs.",
    "Treat discovered repository context files as authoritative commit policy.",
    "Use recent_commits only as fallback style evidence where repository guidance is silent.",
    "Partition staged work aggressively into atomic concerns, including independent changes within the same file.",
    "Keep independently reversible changes in separate commits, including distinct configuration keys or roles and feature implementation versus enabling or configuring that feature.",
    "When independent concerns share one Git hunk, split them with disjoint new-file `lines` ranges; never collapse them because Git presented one hunk.",
    "Whenever one file contains both formatting-only and semantic edits, you MUST use separate commit groups with disjoint new-file `lines` ranges, even when Git presents them as one hunk.",
    "Choose propose_commit only for one indivisible concern; otherwise choose split_commit.",
    "Cover every staged file and selected hunk exactly once in split plans.",
    "Finish immediately after exactly one valid propose_commit or split_commit call.",
    "Never call propose_changelog; changelog generation is disabled.",
    "The summary field is the exact complete commit subject that will be committed.",
    "Do not synthesize a conventional type or scope in the subject unless repository policy requires it.",
    "The type and scope fields are internal compatibility metadata and are not rendered.",
    "Use details for durable rationale, behavior, or constraints when the diff provides them.",
    "Every non-empty body is rendered as a bullet list; supply one concise item per distinct fact.",
    "Do not omit a useful body merely because recent commits were subject-only.",
    "Do not manufacture generic details, file inventories, diff statistics, or test claims.",
    "Include issue references or trailers as exact details lines only when factual and required by repository policy.",
    "If a final response is emitted, keep it to one concise sentence with no proposal recap.",
].join("\n");

const AGENT_USER_PROMPT = [
    "Generate the commit proposal for the current staged snapshot.",
    "If no changes are staged, stage all worktree changes first.",
    "If changes are staged, inspect only the cached snapshot and leave unstaged changes untouched.",
    "Use the commit tools, then submit exactly one valid proposal.",
].join("\n");

const MAX_RETRIES = 3;

interface CommitOptions {
    readonly context: readonly string[];
}

interface ParseState {
    readonly options: CommitOptions;
    readonly awaitingContext: boolean;
    readonly passthrough: boolean;
    readonly error?: string;
}

type ParseResult = CommitOptions | { readonly error: string };

interface Notification {
    readonly message: string;
    readonly type: "info" | "error";
}

interface AppliedCommitResult {
    readonly messages: readonly string[];
}

const initialParseState: ParseState = {
    options: { context: [] },
    awaitingContext: false,
    passthrough: false,
};

const appendContext = (state: ParseState, value: string): ParseState => {
    return {
        ...state,
        options: {
            ...state.options,
            context: [...state.options.context, value],
        },
        awaitingContext: false,
    };
};

const reduceArgument = (state: ParseState, argument: string): ParseState => {
    if (state.error) return state;
    if (state.awaitingContext) {
        return argument
            ? appendContext(state, argument)
            : { ...state, error: "--context requires a value" };
    }
    if (state.passthrough) return appendContext(state, argument);
    if (argument === "--") {
        return { ...state, passthrough: true };
    }
    if (argument === "--context") return { ...state, awaitingContext: true };
    if (argument.startsWith("--context=")) {
        const value = argument.slice("--context=".length);
        return value
            ? appendContext(state, value)
            : { ...state, error: "--context requires a value" };
    }
    if (argument.startsWith("-")) return { ...state, error: `Unsupported option: ${argument}` };
    return appendContext(state, argument);
};

const parseArgs = (args: readonly string[]): ParseResult => {
    const state = args.reduce<ParseState>(reduceArgument, initialParseState);
    if (state.error) return { error: state.error };
    if (state.awaitingContext) return { error: "--context requires a value" };
    return state.options;
};

const composeContext = (options: CommitOptions): string =>
    [...options.context].filter(Boolean).join("\n\n");

const proposalExists = (state: CommitAgentState): boolean =>
    Boolean(state.proposal || state.splitProposal);
type CommitPhase = "propose" | "forced-split" | "finalized";
type ProposalSlot = "proposal" | "splitProposal";

interface CommitPhaseState {
    value: CommitPhase;
    proposalSlot?: ProposalSlot;
}

const proposalAlreadyRecorded = (internals: CommitInternals) => responseResult({
    valid: false,
    errors: ["A commit proposal has already been recorded; proposal tools are mutually exclusive."],
    warnings: [],
}, internals.maxDetailItems);

const reserveProposalSlot = (
    state: CommitAgentState,
    phase: CommitPhaseState,
    slot: ProposalSlot,
): boolean => {
    if (
        phase.value === "finalized" ||
        phase.proposalSlot !== undefined ||
        state.proposal !== undefined ||
        state.splitProposal !== undefined
    ) {
        return false;
    }
    phase.proposalSlot = slot;
    return true;
};

const releaseProposalSlot = (
    state: CommitAgentState,
    phase: CommitPhaseState,
    slot: ProposalSlot,
): void => {
    if (
        phase.proposalSlot === slot &&
        state.proposal === undefined &&
        state.splitProposal === undefined
    ) {
        phase.proposalSlot = undefined;
    }
};

const formatCommitMessage = (
    summary: string,
    details: readonly ConventionalDetail[],
): string => {
    const body = details
        .map(detail => detail.text.trim())
        .filter(Boolean)
        .map(item => item.startsWith("- ") ? item : `- ${item}`);
    return body.length > 0 ? `${summary.trim()}\n\n${body.join("\n")}` : summary.trim();
};

export const unquoteGitPath = (path: string): string => {
    if (!path.startsWith('"') || !path.endsWith('"') || path.length < 2) {
        return path;
    }
    const raw = path.slice(1, -1);
    const bytes: number[] = [];
    let i = 0;
    while (i < raw.length) {
        const c = raw[i];
        if (c === "\\") {
            i += 1;
            if (i >= raw.length) {
                bytes.push(0x5c);
                break;
            }
            const next = raw[i];
            if (next !== undefined && next >= "0" && next <= "7") {
                let octal = next;
                if (i + 1 < raw.length && raw[i + 1] !== undefined && raw[i + 1]! >= "0" && raw[i + 1]! <= "7") {
                    octal += raw[i + 1];
                    i += 1;
                    if (i + 1 < raw.length && raw[i + 1] !== undefined && raw[i + 1]! >= "0" && raw[i + 1]! <= "7") {
                        octal += raw[i + 1];
                        i += 1;
                    }
                }
                bytes.push(Number.parseInt(octal, 8));
                i += 1;
            } else if (next === "n") {
                bytes.push(0x0a);
                i += 1;
            } else if (next === "t") {
                bytes.push(0x09);
                i += 1;
            } else if (next === "r") {
                bytes.push(0x0d);
                i += 1;
            } else if (next === "b") {
                bytes.push(0x08);
                i += 1;
            } else if (next === "f") {
                bytes.push(0x0c);
                i += 1;
            } else if (next === "v") {
                bytes.push(0x0b);
                i += 1;
            } else if (next === "a") {
                bytes.push(0x07);
                i += 1;
            } else if (next === '"') {
                bytes.push(0x22);
                i += 1;
            } else if (next === "\\") {
                bytes.push(0x5c);
                i += 1;
            } else {
                bytes.push(raw.charCodeAt(i));
                i += 1;
            }
        } else {
            bytes.push(raw.charCodeAt(i));
            i += 1;
        }
    }
    return Buffer.from(bytes).toString("utf8");
};

const getStagedFiles = async (api: CommandAPI, cwd: string): Promise<string[]> => {
    const output = (await api.exec("git", ["-c", "core.quotepath=false", "diff", "--name-only", "--cached"], { cwd })).stdout;
    return output.split("\n").map(line => line.trim()).filter(Boolean).map(unquoteGitPath);
};

const stagedFilesOrStageAll = async (api: CommandAPI, cwd: string): Promise<string[]> => {
    const stagedFiles = await getStagedFiles(api, cwd);
    if (stagedFiles.length > 0) return stagedFiles;
    // Former api.pi.stage.files(cwd) was `git add -A` in cwd; run it directly so
    // staging no longer depends on vendor API surface.
    const staged = await api.exec("git", ["add", "-A"], { cwd });
    if (staged.code !== 0) throw new Error(staged.stderr || "Unable to stage local changes.");
    return getStagedFiles(api, cwd);
};

type CommitTool = ReturnType<CommitInternals["createCommitTools"]>[number];

interface DetailInput {
    readonly text: string;
    readonly changelog_category?: ConventionalDetail["changelogCategory"];
    readonly user_visible?: boolean;
}

interface ProposeCommitParams {
    readonly type: CommitType;
    readonly scope: string | null;
    readonly summary: string;
    readonly details?: DetailInput[];
    readonly issue_refs?: string[];
}

interface SplitCommitParams {
    readonly commits: Array<{
        readonly changes: FileChange[];
        readonly type: CommitType;
        readonly scope: string | null;
        readonly summary: string;
        readonly details?: DetailInput[];
        readonly issue_refs?: string[];
        readonly rationale?: string;
        readonly dependencies?: number[];
    }>;
}

const validateSubject = (subject: string): string[] => {
    const errors: string[] = [];
    if (!subject.trim()) errors.push("Commit subject is empty");
    if (/[\r\n]/.test(subject)) errors.push("Commit subject must be a single line");
    return errors;
};

const responseResult = (response: object, maxDetailItems: number) => ({
    content: [{
        type: "text" as const,
        text: JSON.stringify({
            ...response,
            constraints: { maxDetailItems },
        }, null, 2),
    }],
    details: response,
});

const execRepoProposal = async (
    state: CommitAgentState,
    internals: CommitInternals,
    params: ProposeCommitParams,
) => {
    const scope = params.scope?.trim() || null;
    const summary = params.summary.trim();
    const details = internals.normalizeDetails(params.details ?? []);
    const { details: cappedDetails, warnings } = internals.capDetails(details);
    const analysis: ConventionalAnalysis = {
        type: params.type,
        scope,
        details: cappedDetails,
        issueRefs: params.issue_refs ?? [],
    };
    const errors = validateSubject(summary);
    const response: {
        valid: boolean;
        errors: string[];
        warnings: string[];
        proposal?: {
            type: CommitType;
            scope: string | null;
            summary: string;
            details: ConventionalDetail[];
            issue_refs: string[];
        };
    } = { valid: errors.length === 0, errors, warnings };
    if (response.valid) {
        response.proposal = {
            type: analysis.type,
            scope: analysis.scope,
            summary,
            details: analysis.details,
            issue_refs: analysis.issueRefs,
        };
        state.proposal = { analysis, summary, warnings };
    }
    return responseResult(response, internals.maxDetailItems);
};

const validateHunkSelectors = (
    commitIndex: number,
    changes: SplitCommitGroup["changes"],
    files: string[],
): { readonly errors: string[]; readonly warnings: string[] } => {
    const errors: string[] = [];
    const warnings: string[] = [];
    const prefix = `Commit ${commitIndex + 1}`;
    if (files.length === 0) {
        errors.push(`${prefix}: no files specified`);
        return { errors, warnings };
    }
    for (const change of changes) {
        if (change.kind === "indices") {
            const invalid = (change.indices ?? []).filter(
                value => !Number.isFinite(value) || Math.floor(value) !== value || value < 1,
            );
            if (invalid.length > 0) errors.push(`${prefix}: invalid hunk indices for ${change.path}`);
            continue;
        }
        if (change.kind === "lines") {
            const { start, end } = change;
            if (start === undefined || end === undefined || !Number.isFinite(start) || !Number.isFinite(end)) {
                errors.push(`${prefix}: invalid line range for ${change.path}`);
                continue;
            }
            if (Math.floor(start) !== start || Math.floor(end) !== end || start < 1 || end < start) {
                errors.push(`${prefix}: invalid line range for ${change.path}`);
            }
        }
    }
    return { errors, warnings };
};

const validateDependencies = (commitIndex: number, dependencies: number[], totalCommits: number): string[] => {
    const errors: string[] = [];
    const prefix = `Commit ${commitIndex + 1}`;
    for (const dependency of dependencies) {
        if (!Number.isFinite(dependency) || Math.floor(dependency) !== dependency) {
            errors.push(`${prefix}: dependency index must be an integer`);
            continue;
        }
        if (dependency === commitIndex) {
            errors.push(`${prefix}: cannot depend on itself`);
            continue;
        }
        if (dependency < 0 || dependency >= totalCommits) {
            errors.push(`${prefix}: dependency index out of range (${dependency})`);
        }
    }
    return errors;
};

const execRepoSplit = async (
    state: CommitAgentState,
    internals: CommitInternals,
    stagedFiles: readonly string[],
    parsedFiles: ReadonlyMap<string, FileHunks>,
    params: SplitCommitParams,
) => {
    const stagedSet = new Set(stagedFiles);
    const errors: string[] = [];
    const warnings: string[] = [];
    if (!params.commits || params.commits.length < 2) {
        errors.push("Split plan must contain at least two commits");
    }
    const commits: SplitCommitGroup[] = (params.commits ?? []).map((commit, index) => {
        const scope = commit.scope?.trim() || null;
        const summary = commit.summary.trim();
        const details = internals.normalizeDetails(commit.details ?? []);
        const detailResult = internals.capDetails(details);
        warnings.push(...detailResult.warnings.map(warning => `Commit ${index + 1}: ${warning}`));
        const issueRefs = commit.issue_refs ?? [];
        const dependencies = (commit.dependencies ?? []).map(dep => Math.floor(dep));
        const changes = commit.changes.map(change => ({
            path: change.path,
            kind: change.kind,
            indices: change.indices,
            start: change.start,
            end: change.end,
        }));
        const files = changes.map(change => change.path);
        errors.push(...validateSubject(summary).map(error => `Commit ${index + 1}: ${error}`));
        const hunkValidation = validateHunkSelectors(index, changes, files);
        warnings.push(...hunkValidation.warnings);
        errors.push(...hunkValidation.errors);
        errors.push(...validateDependencies(index, dependencies, (params.commits ?? []).length));
        return {
            changes,
            type: commit.type,
            scope,
            summary,
            details: detailResult.details,
            issueRefs,
            rationale: commit.rationale?.trim() || undefined,
            dependencies,
        };
    });
    for (const commit of commits) {
        const seen = new Set<string>();
        for (const change of commit.changes) {
            const file = change.path;
            if (!stagedSet.has(file)) {
                errors.push(`File not staged: ${file}`);
                continue;
            }
            if (seen.has(file)) {
                errors.push(`File listed multiple times in commit ${commit.summary}: ${file}`);
                continue;
            }
            seen.add(file);
        }
    }
    const plannedFiles = new Set(commits.flatMap(commit => commit.changes.map(change => change.path)));
    for (const file of stagedFiles) {
        if (!plannedFiles.has(file)) errors.push(`Staged file missing from split plan: ${file}`);
    }
    errors.push(...validateHunkCoverage(stagedFiles, commits, parsedFiles));
    const dependencyCheck = internals.computeDependencyOrder(commits);
    if ("error" in dependencyCheck) errors.push(dependencyCheck.error);
    const response: {
        valid: boolean;
        errors: string[];
        warnings: string[];
        proposal?: SplitCommitPlan;
    } = { valid: errors.length === 0, errors, warnings };
    if (response.valid) {
        response.proposal = { commits, warnings };
        state.splitProposal = response.proposal;
    }
    return responseResult(response, internals.maxDetailItems);
};

const mkRepoProposalTool = (
    nativeTool: CommitTool,
    state: CommitAgentState,
    internals: CommitInternals,
    phase: CommitPhaseState,
    onResult?: (result: unknown) => void,
): CommitTool => ({
    ...nativeTool,
    execute: async (_toolCallId, params, _onUpdate, ctx) => {
        if (phase.value === "forced-split") {
            const result = responseResult({
                valid: false,
                errors: ["Atomicity review requires a split_commit proposal; propose_commit is not allowed."],
                warnings: [],
            }, internals.maxDetailItems);
            onResult?.(result);
            return result;
        }
        if (!reserveProposalSlot(state, phase, "proposal")) {
            const result = proposalAlreadyRecorded(internals);
            onResult?.(result);
            return result;
        }
        try {
            const result = await execRepoProposal(state, internals, params as ProposeCommitParams);
            if (state.proposal) {
                phase.value = "finalized";
                queueMicrotask(() => ctx?.abort?.());
            } else {
                releaseProposalSlot(state, phase, "proposal");
            }
            onResult?.(result);
            return result;
        } catch (error) {
            releaseProposalSlot(state, phase, "proposal");
            throw error;
        }
    },
});

const mkRepoSplitTool = (
    nativeTool: CommitTool,
    state: CommitAgentState,
    internals: CommitInternals,
    stagedFiles: readonly string[],
    parsedFiles: ReadonlyMap<string, FileHunks>,
    phase: CommitPhaseState,
    onResult?: (result: unknown) => void,
): CommitTool => ({
    ...nativeTool,
    execute: async (_toolCallId, params, _onUpdate, ctx) => {
        const splitParams = params as SplitCommitParams;
        if (phase.value === "finalized") {
            const result = proposalAlreadyRecorded(internals);
            onResult?.(result);
            return result;
        }
        if (phase.value === "forced-split" && (!Array.isArray(splitParams?.commits) || splitParams.commits.length < 2)) {
            const result = responseResult({
                valid: false,
                errors: ["Atomicity review requires a split plan with at least two commits."],
                warnings: [],
            }, internals.maxDetailItems);
            onResult?.(result);
            return result;
        }
        if (!reserveProposalSlot(state, phase, "splitProposal")) {
            const result = proposalAlreadyRecorded(internals);
            onResult?.(result);
            return result;
        }
        try {
            const result = await execRepoSplit(state, internals, stagedFiles, parsedFiles, splitParams);
            if (state.splitProposal) {
                phase.value = "finalized";
                queueMicrotask(() => ctx?.abort?.());
            } else {
                releaseProposalSlot(state, phase, "splitProposal");
            }
            onResult?.(result);
            return result;
        } catch (error) {
            releaseProposalSlot(state, phase, "splitProposal");
            throw error;
        }
    },
});

type HunkSelector = FileChange;

const selectionsOverlap = (left: HunkSelector, right: HunkSelector): boolean => {
    if (left.kind === "all" || right.kind === "all") return true;
    if (left.kind === "indices" && right.kind === "indices") {
        const selected = new Set(left.indices ?? []);
        return (right.indices ?? []).some(index => selected.has(index));
    }
    if (left.kind === "lines" && right.kind === "lines") {
        const leftStart = left.start ?? 0;
        const leftEnd = left.end ?? 0;
        const rightStart = right.start ?? 0;
        const rightEnd = right.end ?? 0;
        return leftStart <= rightEnd && rightStart <= leftEnd;
    }
    return true;
};

const changedNewLines = (hunk: FileHunks["hunks"][number]): number[] => {
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

const selectorIntersectsHunk = (
    selector: HunkSelector,
    hunk: FileHunks["hunks"][number],
): boolean => {
    if (selector.kind === "all") return true;
    if (selector.kind === "indices") return (selector.indices ?? []).includes(hunk.index + 1);
    const hunkEnd = hunk.newLines === 0 ? hunk.newStart : hunk.newStart + hunk.newLines - 1;
    const start = selector.start ?? 0;
    const end = selector.end ?? 0;
    return hunk.newStart <= end && start <= hunkEnd;
};

const validateHunkCoverage = (
    stagedFiles: readonly string[],
    commits: readonly SplitCommitGroup[],
    parsedFiles: ReadonlyMap<string, FileHunks>,
): string[] => {
    const stagedSet = new Set(stagedFiles);
    const selectionsByFile = new Map<string, HunkSelector[]>();
    for (const commit of commits) {
        for (const change of commit.changes) {
            if (!stagedSet.has(change.path)) continue;
            const prior = selectionsByFile.get(change.path) ?? [];
            selectionsByFile.set(change.path, [...prior, change]);
        }
    }

    const errors: string[] = [];
    const filesByCommit = new Map<string, number>();
    for (let cIdx = 0; cIdx < commits.length; cIdx += 1) {
        for (const change of commits[cIdx].changes) {
            const prev = filesByCommit.get(change.path);
            if (prev !== undefined && prev !== cIdx) {
                errors.push(`File ${change.path} is split across multiple commits (commit ${prev + 1} and ${cIdx + 1}); all changes to a file must be grouped in the same commit.`);
            }
            filesByCommit.set(change.path, cIdx);
        }
    }
    for (const [file, selections] of selectionsByFile) {
        for (let leftIndex = 0; leftIndex < selections.length; leftIndex += 1) {
            const left = selections[leftIndex];
            if (!left) continue;
            for (const right of selections.slice(leftIndex + 1)) {
                if (selectionsOverlap(left, right)) {
                    errors.push(`Overlapping hunk selections across commits: ${file}`);
                    break;
                }
            }
        }
    }
    for (const file of stagedFiles) {
        const parsed = parsedFiles.get(file);
        if (!parsed || parsed.isBinary) continue;
        const selections = selectionsByFile.get(file) ?? [];
        for (const hunk of parsed.hunks) {
            const changedLines = changedNewLines(hunk);
            const covered = changedLines.every(line => selections.some(selection =>
                selection.kind === "lines"
                    ? (selection.start ?? 0) <= line && line <= (selection.end ?? 0)
                    : selectorIntersectsHunk(selection, hunk),
            ));
            if (!covered) {
                errors.push(`Staged hunk missing from split plan: ${file} (hunk ${hunk.index + 1})`);
            }
        }
    }
    return errors;
};

const buildAtomicityProposalInput = (
    proposal: NonNullable<CommitAgentState["proposal"]>,
    stagedFileCount: number,
    diffText: string,
    internals: CommitInternals,
): AtomicityProposalInput => ({
    summary: proposal.summary,
    details: proposal.analysis.details.map(detail => detail.text),
    stagedFileCount,
    changedHunkCount: internals
        .parseFileDiffs(diffText)
        .reduce((count, file) => count + internals.parseFileHunks(file).hunks.length, 0),
});

const runAtomicityCritic = async (
    api: CommandAPI,
    cwd: string,
    modelRegistry: ModelRegistry,
    settings: Settings,
    selected: Pick<ScopedModel, "model" | "thinkingLevel">,
    proposalInput: AtomicityProposalInput,
    diffText: string,
): Promise<AtomicityDecision> => {
    let decision: AtomicityDecision | undefined;
    const verdictParameterSchema = api.arktype.type({
        decision: "'accept' | 'split'",
        concerns: api.arktype.type("string").atMostLength(512).matching(/\S/).array().atMostLength(8),
        rationale: api.arktype.type("string").atMostLength(2_000).matching(/\S/),
    }).onUndeclaredKey("reject").narrow((value, ctx) => {
        if (value.decision === "accept" && value.concerns.length === 0) return true;
        if (
            value.decision === "split" &&
            value.concerns.length >= 2 &&
            new Set(value.concerns.map(concern => concern.trim())).size === value.concerns.length
        ) {
            return true;
        }
        return ctx.mustBe("a valid atomicity critic decision; 'accept' requires empty concerns; 'split' requires >=2 unique non-empty concerns");
    });
    const verdictTool = {
        name: "atomicity_verdict",
        label: "Atomicity verdict",
        description: "Record exactly one normalized atomicity verdict for the provisional commit proposal.",
        strict: true,
        parameters: verdictParameterSchema,
        execute: async (_toolCallId: string, params: unknown, _onUpdate: unknown, ctx: { abort(): void }) => {
            if (decision) {
                return {
                    content: [{ type: "text" as const, text: "A verdict has already been recorded." }],
                    details: { valid: false },
                };
            }
            let normalized: AtomicityDecision;
            try {
                normalized = normalizeAtomicityDecision(params);
            } catch (error) {
                return {
                    content: [{
                        type: "text" as const,
                        text: `Invalid atomicity verdict: ${error instanceof Error ? error.message : String(error)}`,
                    }],
                    details: { valid: false },
                };
            }
            decision = normalized;
            queueMicrotask(() => ctx.abort());
            return {
                content: [{ type: "text" as const, text: JSON.stringify(normalized) }],
                details: normalized,
            };
        },
    } as unknown as CommitTool;
    const { session } = await api.pi.createAgentSession({
        cwd,
        authStorage: modelRegistry.authStorage,
        modelRegistry,
        settings,
        model: selected.model,
        thinkingLevel: selected.thinkingLevel,
        systemPrompt: defaultPrompt => [...defaultPrompt, ATOMICITY_CRITIC_SYSTEM_PROMPT],
        customTools: [verdictTool],
        toolNames: [verdictTool.name],
        restrictToolNames: true,
        allowRestrictedCustomTools: true,
        enableLsp: false,
        enableMCP: false,
        hasUI: false,
        autoApprove: true,
        spawns: "sonic",
        contextFiles: [],
        skills: [],
        promptTemplates: [],
        slashCommands: [],
        extensions: [],
        disableExtensionDiscovery: true,
    });
    const criticPrompt = buildAtomicityCriticPrompt(proposalInput, diffText);
    try {
        for (let attempt = 0; attempt < 2 && !decision; attempt += 1) {
            await session.prompt(
                attempt === 0
                    ? criticPrompt
                    : "Return exactly one valid atomicity_verdict tool call now. Prose is not a verdict; ambiguity must be reported as split.",
                {
                    attribution: "agent",
                    expandPromptTemplates: false,
                    ...(attempt === 0 ? {} : { synthetic: true }),
                },
            );
        }
    } catch (error) {
        if (!decision) throw error;
    } finally {
        await session.dispose();
    }
    if (!decision) throw new Error("Atomicity critic did not provide a valid verdict.");
    return decision;
};

const runCommitAgent = async (
    api: CommandAPI,
    cwd: string,
    modelRegistry: ModelRegistry,
    options: CommitOptions,
    internals: CommitInternals,
) => {
    const settings = await api.pi.Settings.init({ cwd });
    await modelRegistry.refresh();
    const selected = internals.resolveRoleSelection(["commit"], settings, modelRegistry.getAvailable());
    if (!selected) throw new Error("No configured commit model is available.");
    if (!(await modelRegistry.getApiKey(selected.model))) {
        throw new Error(`No API key available for commit model ${selected.model.provider}/${selected.model.id}.`);
    }

    const stagedFiles = await stagedFilesOrStageAll(api, cwd);
    if (stagedFiles.length === 0) throw new Error("No local changes to commit.");
    const diffText = (await api.exec("git", ["-c", "core.quotepath=false", "-c", "diff.mnemonicprefix=false", "-c", "diff.noprefix=false", "diff", "--src-prefix=a/", "--dst-prefix=b/", "--cached", "--no-textconv"], { cwd })).stdout;
    const contextFiles = await api.pi.discoverContextFiles(cwd);
    const phase: CommitPhaseState = { value: "propose" };
    const state: CommitAgentState = { diffText };
    let lastValidationError: string | undefined;
    const captureValidationResult = (result: unknown) => {
        if (phase.value !== "forced-split") return;
        const text = typeof (result as { content?: Array<{ text?: string }> })?.content?.[0]?.text === "string"
            ? (result as { content?: Array<{ text?: string }> }).content![0]!.text!
            : undefined;
        if (text) {
            lastValidationError = text;
        }
    };

    const nativeTools = internals.createCommitTools({
        cwd,
        authStorage: modelRegistry.authStorage,
        modelRegistry,
        settings,
        spawns: "sonic",
        state,
        changelogTargets: [],
        enableAnalyzeFiles: true,
    });
    const nativeProposalTool = nativeTools.find(tool => tool.name === "propose_commit");
    const nativeSplitTool = nativeTools.find(tool => tool.name === "split_commit");
    if (!nativeProposalTool || !nativeSplitTool) {
        throw new Error("Native commit proposal tools are unavailable.");
    }
    const parsedFiles = new Map(
        internals.parseFileDiffs(diffText).map(file => [file.filename, internals.parseFileHunks(file)] as const),
    );
    const tools = nativeTools
        .filter(tool => !["propose_changelog", "propose_commit", "split_commit"].includes(tool.name))
        .concat([
            mkRepoProposalTool(nativeProposalTool, state, internals, phase, captureValidationResult),
            mkRepoSplitTool(nativeSplitTool, state, internals, stagedFiles, parsedFiles, phase, captureValidationResult),
        ]);

    const { session } = await api.pi.createAgentSession({
        cwd,
        authStorage: modelRegistry.authStorage,
        modelRegistry,
        settings,
        model: selected.model,
        thinkingLevel: selected.thinkingLevel,
        systemPrompt: defaultPrompt => [...defaultPrompt, COMMIT_AGENT_SYSTEM_PROMPT],
        customTools: tools,
        toolNames: tools.map(tool => tool.name),
        restrictToolNames: true,
        allowRestrictedCustomTools: true,
        enableLsp: false,
        enableMCP: false,
        hasUI: false,
        autoApprove: true,
        spawns: "sonic",
        contextFiles,
        slashCommands: [],
    });
    const promptAgent = async (attempt: number): Promise<void> => {
        if (proposalExists(state) || attempt >= MAX_RETRIES) return;
        try {
            await session.prompt(
                attempt === 0
                    ? [AGENT_USER_PROMPT, composeContext(options)].filter(Boolean).join("\n\n")
                    : `Submit a valid ${state.splitProposal ? "split_commit" : "propose_commit"} proposal now. Attempt ${attempt} of ${MAX_RETRIES}.`,
                {
                    attribution: "agent",
                    expandPromptTemplates: false,
                    ...(attempt === 0 ? {} : { synthetic: true }),
                },
            );
        } catch (error) {
            if (!proposalExists(state)) throw error;
        }
        await promptAgent(attempt + 1);
    };
    try {
        await promptAgent(0);
        if (!state.proposal) return state;

        const proposalInput = buildAtomicityProposalInput(state.proposal, stagedFiles.length, diffText, internals);
        if (!shouldReviewAtomicity(proposalInput)) return state;

        const decision = await runAtomicityCritic(
            api,
            cwd,
            modelRegistry,
            settings,
            selected,
            proposalInput,
            diffText,
        );
        if (decision.decision === "accept") return state;

        const hadStaleSplitProposal = state.splitProposal !== undefined;
        state.proposal = undefined;
        state.splitProposal = undefined;
        phase.proposalSlot = undefined;
        if (hadStaleSplitProposal) {
            throw new Error("Atomicity critic retry started with a stale split proposal.");
        }
        phase.value = "forced-split";
        lastValidationError = undefined;
        const concerns = decision.concerns.map((concern, index) => `${index + 1}. ${concern}`).join("\n");
        const splitPrompt = [
            "The independent atomicity critic rejected the provisional single-commit proposal.",
            "Concrete critic concerns:",
            concerns,
            `Critic rationale: ${decision.rationale}`,
            "Re-evaluate the full cached snapshot and submit exactly one valid split_commit proposal with at least two commits addressing these concerns.",
        ].join("\n");
        try {
            await session.prompt(splitPrompt, {
                attribution: "agent",
                expandPromptTemplates: false,
                synthetic: true,
            });
        } catch (error) {
            if (!state.splitProposal) throw error;
        }
        if (!state.splitProposal || state.splitProposal.commits.length < 2) {
            state.splitProposal = undefined;
            const baseMessage = "Atomicity critic required a split_commit proposal with at least two commits.";
            const message = lastValidationError ? `${baseMessage} ${lastValidationError}` : baseMessage;
            throw new Error(message);
        }
        return state;

    } finally {
        await session.dispose();
    }
};

const validateSplitPlan = async (
    api: CommandAPI,
    cwd: string,
    plan: SplitCommitPlan,
    internals: CommitInternals,
): Promise<{ readonly order: readonly number[]; readonly stagedDiff: string; readonly zeroDiff: string }> => {
    const stagedFiles = await getStagedFiles(api, cwd);
    internals.assignLockFilesToPlan(plan, stagedFiles);
    const plannedFiles = new Set(plan.commits.flatMap(commit => commit.changes.map(change => change.path)));
    const missingFiles = stagedFiles.filter(file => !plannedFiles.has(file));
    if (missingFiles.length > 0) {
        throw new Error(`Split plan missing staged files: ${missingFiles.join(", ")}`);
    }
    const stagedDiff = (await api.exec("git", ["-c", "core.quotepath=false", "-c", "diff.mnemonicprefix=false", "-c", "diff.noprefix=false", "diff", "--src-prefix=a/", "--dst-prefix=b/", "--cached", "--binary", "--no-textconv"], { cwd })).stdout;
    const parsedFiles = new Map(
        internals.parseFileDiffs(stagedDiff).map(file => [file.filename, internals.parseFileHunks(file)] as const),
    );
    const coverageErrors = validateHunkCoverage(stagedFiles, plan.commits, parsedFiles);
    if (coverageErrors.length > 0) {
        throw new Error(`Invalid split plan: ${coverageErrors.join("; ")}`);
    }
    const order = internals.computeDependencyOrder(plan.commits);
    if ("error" in order) throw new Error(order.error);
    const zeroDiff = await api.exec("git", ["-c", "core.quotepath=false", "-c", "diff.mnemonicprefix=false", "-c", "diff.noprefix=false", "diff", "--src-prefix=a/", "--dst-prefix=b/", "--cached", "--binary", "--unified=0", "--no-textconv"], { cwd });
    if (zeroDiff.code !== 0) throw new Error(zeroDiff.stderr || "Unable to read zero-context staged diff.");
    return {
        order,
        stagedDiff,
        zeroDiff: zeroDiff.stdout,
    };
};

export const selectPatch = (
    file: FileDiff,
    selector: FileChange,
    internals: Pick<CommitInternals, "parseFileHunks">,
): string => {
    if (file.isBinary && selector.kind !== "all") {
        throw new Error(`Cannot partially select binary file ${file.filename}.`);
    }
    const isRename = file.content.includes("\nrename " + "from ") || file.content.startsWith("rename " + "from ");
    if (isRename && selector.kind !== "all") {
        throw new Error(`Cannot partially select renamed file ${file.filename}; entire file change must be committed together.`);
    }
    if (selector.kind === "all") return file.content;
    const parsed: FileHunks = internals.parseFileHunks(file);
    const hunks = selector.kind === "indices"
        ? parsed.hunks.filter(hunk => (selector.indices ?? []).includes(hunk.index + 1))
        : parsed.hunks.filter(hunk => {
            const start = hunk.newStart;
            const end = hunk.newLines === 0 ? start : start + hunk.newLines - 1;
            const selStart = selector.start ?? 0;
            const selEnd = selector.end ?? 0;
            return start <= selEnd && selStart <= end;
        });
    if (hunks.length === 0) {
        throw new Error(`No changes selected for ${file.filename}.`);
    }
    const firstHunk = file.content.indexOf("\n@@");
    const header = firstHunk < 0 ? file.content : file.content.slice(0, firstHunk);
    return [header, ...hunks.map(hunk => hunk.content)].join("\n");
};

const buildCommitPatch = (
    changes: readonly FileChange[],
    stagedDiff: string,
    zeroDiff: string,
    internals: CommitInternals,
): string => {
    const regularFiles = new Map(internals.parseFileDiffs(stagedDiff).map(file => [file.filename, file]));
    const zeroFiles = new Map(internals.parseFileDiffs(zeroDiff).map(file => [file.filename, file]));
    const parts = changes.map(change => {
        const files = change.kind === "lines" ? zeroFiles : regularFiles;
        const file = files.get(change.path);
        if (!file) throw new Error(`No staged diff found for ${change.path}.`);
        return selectPatch(file, change, internals);
    });
    return `${parts.join("\n")}\n`;
};

interface PublicationEvidence {
    readonly ref: string;
    readonly before: string;
    readonly indexTree: string;
}

const currentEvidence = async (api: CommandAPI, cwd: string): Promise<PublicationEvidence> => {
    const symRef = await api.exec("git", ["symbolic-ref", "-q", "HEAD"], { cwd });
    if (symRef.code !== 0 || !symRef.stdout.trim()) {
        throw new Error("Autommit requires a branch checkout with an existing HEAD.");
    }
    const ref = symRef.stdout.trim();
    const headCommit = await api.exec("git", ["rev-parse", "HEAD"], { cwd });
    if (headCommit.code !== 0 || !headCommit.stdout.trim()) {
        throw new Error("Autommit requires a branch checkout with an existing HEAD.");
    }
    const writeTree = await api.exec("git", ["write-tree"], { cwd });
    if (writeTree.code !== 0 || !writeTree.stdout.trim()) {
        throw new Error(writeTree.stderr || "Unable to write git index tree.");
    }
    return {
        ref,
        before: headCommit.stdout.trim(),
        indexTree: writeTree.stdout.trim(),
    };
};

const assertEvidence = async (
    api: CommandAPI,
    cwd: string,
    expected: PublicationEvidence,
): Promise<PublicationEvidence> => {
    const actual = await currentEvidence(api, cwd);
    if (actual.ref !== expected.ref) throw new Error("Autommit branch changed during transaction.");
    if (actual.before !== expected.before) throw new Error("Autommit HEAD changed during transaction.");
    if (actual.indexTree !== expected.indexTree) throw new Error("Autommit index changed during transaction.");
    return actual;
};

const casRef = async (
    api: CommandAPI,
    cwd: string,
    ref: string,
    after: string,
    before: string,
): Promise<void> => {
    const updated = await api.exec("git", ["update-ref", ref, after, before], { cwd });
    if (updated.code !== 0) {
        throw new Error(updated.stderr || "Autommit branch changed during transaction.");
    }
};

const assertReceiptEvidence = async (
    api: CommandAPI,
    cwd: string,
    receipt: Receipt,
    expectedHead: string,
): Promise<void> => {
    const actual = await currentEvidence(api, cwd);
    if (actual.ref !== receipt.ref) throw new Error("Prepared autommit receipt has an unexpected branch.");
    if (actual.before !== expectedHead) throw new Error("Autommit HEAD changed during receipt recovery.");
    if (actual.indexTree !== receipt.indexTree) throw new Error("Autommit index changed during receipt recovery.");
};

export const preparedCommitTreeMatchesIndex = (
    preparedCommitTree: string,
    expectedIndexTree: string,
): boolean => preparedCommitTree === expectedIndexTree;

export const consumeCompletedReceipt = async (
    commonDir: string,
    receipt: Receipt | null,
): Promise<Receipt | null> => {
    if (receipt?.state !== "committed") return receipt;
    await removeReceipt(commonDir);
    return null;
};

export const recoverPreparedReceipt = async (
    api: CommandAPI,
    cwd: string,
    commonDir: string,
    receipt: Receipt,
): Promise<AppliedCommitResult> => {
    if (receipt.state === "committed") return { messages: [] };
    const actual = await currentEvidence(api, cwd);
    if (actual.ref !== receipt.ref) throw new Error("Prepared autommit receipt has an unexpected branch.");
    if (actual.indexTree !== receipt.indexTree) throw new Error("Prepared autommit receipt has an unexpected index.");
    if (actual.before === receipt.before) {
        await casRef(api, cwd, receipt.ref, receipt.after, receipt.before);
        await assertReceiptEvidence(api, cwd, receipt, receipt.after);
    } else if (actual.before !== receipt.after) {
        throw new Error("Prepared autommit receipt does not match the current HEAD.");
    }
    await removeReceipt(commonDir);
    return { messages: ["Recovered prepared autommit transaction."] };
};

const applySplitProposal = async (
    api: CommandAPI,
    cwd: string,
    commonDir: string,
    plan: SplitCommitPlan,
    internals: CommitInternals,
): Promise<AppliedCommitResult> => {
    const expected = await currentEvidence(api, cwd);
    const { order, stagedDiff, zeroDiff } = await validateSplitPlan(api, cwd, plan, internals);
    const worktree = await mkdtemp(join(tmpdir(), "autommit-worktree-"));
    let added = false;
    let patchDir: string | undefined;
    let primaryError: unknown;
    try {
        patchDir = await mkdtemp(join(tmpdir(), "autommit-patch-"));
        const patchPath = join(patchDir, ".autommit.patch");
        const addWorktree = await api.exec("git", ["worktree", "add", "--detach", worktree, expected.before], { cwd });
        if (addWorktree.code !== 0) {
            throw new Error(addWorktree.stderr || `Unable to add worktree at ${worktree}`);
        }
        added = true;
        for (const commitIndex of order) {
            const commit = plan.commits[commitIndex];
            if (!commit) throw new Error(`Split plan references missing commit ${commitIndex}.`);
            await writeFile(patchPath, buildCommitPatch(commit.changes, stagedDiff, zeroDiff, internals), "utf8");
            const applied = await api.exec("git", ["-c", "core.quotepath=false", "apply", "--index", "--unidiff-zero", patchPath], { cwd: worktree });
            if (applied.code !== 0) throw new Error(applied.stderr || "Unable to apply split commit patch.");
            const msgPath = join(patchDir, ".autommit.msg");
            await writeFile(msgPath, formatCommitMessage(commit.summary, commit.details), "utf8");
            const committed = await api.exec(
                "git",
                ["-c", "core.hooksPath=", "commit", "--no-verify", "-F", msgPath],
                { cwd: worktree },
            );
            if (committed.code !== 0) {
                throw new Error(committed.stderr || "Unable to commit split patch in worktree.");
            }
        }
        const currentDiff = (await api.exec("git", ["-c", "core.quotepath=false", "-c", "diff.mnemonicprefix=false", "-c", "diff.noprefix=false", "diff", "--src-prefix=a/", "--dst-prefix=b/", "--cached", "--binary", "--no-textconv"], { cwd })).stdout;
        if (currentDiff !== stagedDiff) throw new Error("Staged snapshot changed during atomic commit preparation.");
        const headShaResult = await api.exec("git", ["-C", worktree, "rev-parse", "HEAD"], { cwd });
        const finalHead = headShaResult.code === 0 ? headShaResult.stdout.trim() : "";
        if (!finalHead) throw new Error("Atomic split preparation did not create a commit.");
        const preparedTree = await api.exec("git", ["rev-parse", `${finalHead}^{tree}`], { cwd: worktree });
        if (preparedTree.code !== 0) {
            throw new Error(preparedTree.stderr || "Unable to inspect prepared commit tree.");
        }
        if (!preparedCommitTreeMatchesIndex(preparedTree.stdout.trim(), expected.indexTree)) {
            throw new Error("Prepared commit tree does not match the staged index.");
        }
        await assertEvidence(api, cwd, expected);
        const prepared: Receipt = {
            version: 1,
            state: "prepared",
            ref: expected.ref,
            before: expected.before,
            after: finalHead,
            indexTree: expected.indexTree,
        };
        await writeReceipt(commonDir, prepared);
        await assertEvidence(api, cwd, expected);
        await casRef(api, cwd, expected.ref, finalHead, expected.before);
        await assertReceiptEvidence(api, cwd, prepared, finalHead);
        await removeReceipt(commonDir);
        return { messages: [`Created ${order.length} commit${order.length === 1 ? "" : "s"} atomically.`] };
    } catch (error) {
        primaryError = error;
        throw error;
    } finally {
        const cleanupFailures: Array<{ readonly path: string; readonly error: unknown }> = [];
        if (added) {
            try {
                const removed = await api.exec("git", ["worktree", "remove", "--force", worktree], { cwd });
                if (removed.code !== 0) {
                    await rm(worktree, { recursive: true, force: true });
                }
            } catch (error) {
                try {
                    await rm(worktree, { recursive: true, force: true });
                } catch (rmError) {
                    cleanupFailures.push({ path: worktree, error: rmError });
                }
            }
        } else {
            try {
                await rm(worktree, { recursive: true, force: true });
            } catch (error) {
                cleanupFailures.push({ path: worktree, error });
            }
        }
        if (patchDir) {
            try {
                await rm(patchDir, { recursive: true, force: true });
            } catch (error) {
                cleanupFailures.push({ path: patchDir, error });
            }
        }
        if (cleanupFailures.length > 0) {
            const cleanupMessage = cleanupFailures
                .map(failure => {
                    const detail = failure.error instanceof Error ? failure.error.message : String(failure.error);
                    return `Cleanup failed for ${failure.path}: ${detail}`;
                })
                .join("; ");
            if (primaryError instanceof Error) {
                primaryError.message = `${primaryError.message}; ${cleanupMessage}`;
            } else if (primaryError !== undefined) {
                throw new Error(`${String(primaryError)}; ${cleanupMessage}`);
            } else {
                throw new Error(cleanupMessage);
            }
        }
    }
};

const applyState = async (
    api: CommandAPI,
    cwd: string,
    commonDir: string,
    state: CommitAgentState,
    internals: CommitInternals,
): Promise<AppliedCommitResult> => {
    if (state.proposal && state.splitProposal) {
        throw new Error("Commit agent produced both single and split proposals; refusing to publish either.");
    }
    if (state.proposal) {
        const stagedFiles = await getStagedFiles(api, cwd);
        if (stagedFiles.length === 0) throw new Error("No staged changes to commit.");
        const proposal = state.proposal;
        const plan: SplitCommitPlan = {
            commits: [{
                changes: stagedFiles.map(path => ({ path, kind: "all" as const })),
                type: proposal.analysis.type,
                scope: proposal.analysis.scope,
                summary: proposal.summary,
                details: proposal.analysis.details,
                issueRefs: proposal.analysis.issueRefs,
                dependencies: [],
            }],
            warnings: proposal.warnings,
        };
        return applySplitProposal(api, cwd, commonDir, plan, internals);
    }
    if (state.splitProposal) return applySplitProposal(api, cwd, commonDir, state.splitProposal, internals);
    throw new Error("Commit agent did not provide a valid proposal.");
};

const report = (ctx: { readonly hasUI: boolean; readonly ui: { notify(message: string, type?: "info" | "error"): void } }, notification: Notification): void => {
    if (ctx.hasUI) ctx.ui.notify(notification.message, notification.type);
    else process.stdout.write(`${notification.message}\n`);
};

const factory: CustomCommandFactory = api => ({
    name: "autommit",
    description: "Run the direct unattended local commit workflow",
    async execute(args, ctx) {
        const parsed = parseArgs(args);
        if ("error" in parsed) {
            report(ctx, { message: parsed.error, type: "error" });
            return;
        }

        await ctx.waitForIdle();
        ctx.ui.setStatus("autommit", "Running direct local commit agent…");
        try {
            const commonDirResult = await api.exec("git", ["rev-parse", "--git-common-dir"], { cwd: ctx.cwd });
            if (commonDirResult.code !== 0) {
                throw new Error("No Git repository found for the current directory.");
            }
            const commonDir = resolve(ctx.cwd, commonDirResult.stdout.trim());
            const result = await withOperationLock(commonDir, async () => {
                const receipt = await consumeCompletedReceipt(
                    commonDir,
                    await readReceipt(commonDir),
                );
                if (receipt?.state === "prepared") {
                    return recoverPreparedReceipt(api, ctx.cwd, commonDir, receipt);
                }
                const internals = await loadCommitInternals();
                const state = await runCommitAgent(api, ctx.cwd, ctx.modelRegistry, parsed, internals);
                return applyState(api, ctx.cwd, commonDir, state, internals);
            });
            report(ctx, { message: result.messages.join("\n"), type: "info" });
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            report(ctx, { message: `Commit workflow failed: ${message}`, type: "error" });
        } finally {
            ctx.ui.setStatus("autommit", undefined);
        }
    },
});

export default factory;
