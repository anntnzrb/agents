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
import type { CommitType, ConventionalAnalysis, ConventionalDetail, FileDiff, FileHunks } from "@oh-my-pi/pi-coding-agent/commit/types";
import type * as CommitUtils from "@oh-my-pi/pi-coding-agent/commit/utils";
import type { createCommitTools } from "@oh-my-pi/pi-coding-agent/commit/agentic/tools";
import type { parseFileDiffs, parseFileHunks } from "@oh-my-pi/pi-coding-agent/commit/git/diff";
import type { resolveRoleSelection, ScopedModel } from "@oh-my-pi/pi-coding-agent/config/model-resolver";
import type { Settings } from "@oh-my-pi/pi-coding-agent/config/settings";
import type { assignLockFilesToPlan } from "@oh-my-pi/pi-coding-agent/commit/agentic/lock-files";
import type { computeDependencyOrder } from "@oh-my-pi/pi-coding-agent/commit/agentic/topo-sort";
import type * as Git from "@oh-my-pi/pi-coding-agent/utils/git";

type CommandAPI = Parameters<CustomCommandFactory>[0];
type PiAPI = CommandAPI["pi"];

interface CommitInternals {
    readonly createCommitTools: typeof createCommitTools;
    readonly resolveRoleSelection: typeof resolveRoleSelection;
    readonly assignLockFilesToPlan: typeof assignLockFilesToPlan;
    readonly computeDependencyOrder: typeof computeDependencyOrder;
    readonly capDetails: typeof AgenticValidation.capDetails;
    readonly parseFileDiffs: typeof parseFileDiffs;
    readonly parseFileHunks: typeof parseFileHunks;
    readonly normalizeDetails: typeof CommitUtils.normalizeDetails;
    readonly maxDetailItems: number;
    readonly git: Pick<
        typeof Git,
        "repo" | "head" | "writeTree" | "worktree" | "log" | "commitDetails" | "diff" | "createHunkSelectionValidator"
    >;
}
type RuntimeInternals = Pick<CommitInternals, "git">;

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
const loadCommitInternals = async (git: CommitInternals["git"]): Promise<CommitInternals> => {
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
        git,
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

const stagedFilesOrStageAll = async (pi: PiAPI, cwd: string): Promise<string[]> => {
    const stagedFiles = await pi.diff.changedFiles(cwd, { cached: true });
    if (stagedFiles.length > 0) return stagedFiles;
    await pi.stage.files(cwd);
    return pi.diff.changedFiles(cwd, { cached: true });
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
    readonly details: DetailInput[];
    readonly issue_refs: string[];
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
    cwd: string,
    state: CommitAgentState,
    internals: CommitInternals,
    params: ProposeCommitParams,
) => {
    const scope = params.scope?.trim() || null;
    const summary = params.summary.trim();
    const details = internals.normalizeDetails(params.details);
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
    validateHunksForDiff: (changes: readonly FileChange[]) => Array<{ readonly message: string }>,
): { readonly errors: string[]; readonly warnings: string[] } => {
    const errors: string[] = [];
    const warnings: string[] = [];
    const prefix = `Commit ${commitIndex + 1}`;
    if (files.length === 0) {
        errors.push(`${prefix}: no files specified`);
        return { errors, warnings };
    }
    for (const change of changes) {
        if (change.hunks.type === "indices") {
            const invalid = change.hunks.indices.filter(
                value => !Number.isFinite(value) || Math.floor(value) !== value || value < 1,
            );
            if (invalid.length > 0) errors.push(`${prefix}: invalid hunk indices for ${change.path}`);
            continue;
        }
        if (change.hunks.type === "lines") {
            const { start, end } = change.hunks;
            if (!Number.isFinite(start) || !Number.isFinite(end)) {
                errors.push(`${prefix}: invalid line range for ${change.path}`);
                continue;
            }
            if (Math.floor(start) !== start || Math.floor(end) !== end || start < 1 || end < start) {
                errors.push(`${prefix}: invalid line range for ${change.path}`);
            }
        }
    }
    if (errors.length === 0) {
        for (const error of validateHunksForDiff(changes)) {
            errors.push(`${prefix}: ${error.message}`);
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

type HunkSelector = FileChange["hunks"];

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
    if (selector.type === "all") return true;
    if (selector.type === "indices") return selector.indices.includes(hunk.index + 1);
    const hunkEnd = hunk.newLines === 0 ? hunk.newStart : hunk.newStart + hunk.newLines - 1;
    return hunk.newStart <= selector.end && selector.start <= hunkEnd;
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
            selectionsByFile.set(change.path, [...prior, change.hunks]);
        }
    }

    const errors: string[] = [];
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
                selection.type === "lines"
                    ? selection.start <= line && line <= selection.end
                    : selectorIntersectsHunk(selection, hunk),
            ));
            if (!covered) {
                errors.push(`Staged hunk missing from split plan: ${file} (hunk ${hunk.index + 1})`);
            }
        }
    }
    return errors;
};

const execRepoSplit = async (
    cwd: string,
    state: CommitAgentState,
    internals: CommitInternals,
    params: SplitCommitParams,
    changelogTargets: readonly string[],
) => {
    const stagedFiles = state.overview?.files ?? (await internals.git.diff.changedFiles(cwd, { cached: true }));
    const stagedSet = new Set(stagedFiles);
    const changelogSet = new Set(changelogTargets);
    const errors: string[] = [];
    const warnings: string[] = [];
    const diffText = state.diffText ?? "";
    const parsedFiles = new Map(
        internals.parseFileDiffs(diffText).map(file => [file.filename, internals.parseFileHunks(file)] as const),
    );
    const validateHunksForDiff = internals.git.createHunkSelectionValidator(diffText);

    const commits: SplitCommitGroup[] = params.commits.map((commit, index) => {
        const scope = commit.scope?.trim() || null;
        const summary = commit.summary.trim();
        const detailInput = internals.normalizeDetails(commit.details ?? []);
        const detailResult = internals.capDetails(detailInput);
        warnings.push(...detailResult.warnings.map(warning => `Commit ${index + 1}: ${warning}`));
        const issueRefs = commit.issue_refs ?? [];
        const dependencies = commit.dependencies ?? [];
        const changes = commit.changes.map(change => ({
            path: change.path,
            hunks: change.hunks,
        }));
        const files = changes.map(change => change.path);
        errors.push(...validateSubject(summary).map(error => `Commit ${index + 1}: ${error}`));
        const hunkValidation = validateHunkSelectors(index, changes, files, validateHunksForDiff);
        warnings.push(...hunkValidation.warnings);
        errors.push(...hunkValidation.errors);
        errors.push(...validateDependencies(index, dependencies, params.commits.length));
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
            if (!stagedSet.has(file) && !changelogSet.has(file)) {
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
    cwd: string,
    state: CommitAgentState,
    internals: CommitInternals,
    phase: CommitPhaseState,
): CommitTool => ({
    ...nativeTool,
    execute: async (_toolCallId, params, _onUpdate, ctx) => {
        if (phase.value === "forced-split") {
            return responseResult({
                valid: false,
                errors: ["Atomicity review requires a split_commit proposal; propose_commit is not allowed."],
                warnings: [],
            }, internals.maxDetailItems);
        }
        if (!reserveProposalSlot(state, phase, "proposal")) {
            return proposalAlreadyRecorded(internals);
        }
        try {
            const result = await execRepoProposal(cwd, state, internals, params as ProposeCommitParams);
            if (state.proposal) {
                phase.value = "finalized";
                queueMicrotask(() => ctx.abort());
            } else {
                releaseProposalSlot(state, phase, "proposal");
            }
            return result;
        } catch (error) {
            releaseProposalSlot(state, phase, "proposal");
            throw error;
        }
    },
});

const mkRepoSplitTool = (
    nativeTool: CommitTool,
    cwd: string,
    state: CommitAgentState,
    internals: CommitInternals,
    changelogTargets: readonly string[],
    phase: CommitPhaseState,
): CommitTool => ({
    ...nativeTool,
    execute: async (_toolCallId, params, _onUpdate, ctx) => {
        const splitParams = params as SplitCommitParams;
        if (phase.value === "finalized") {
            return proposalAlreadyRecorded(internals);
        }
        if (phase.value === "forced-split" && splitParams.commits.length < 2) {
            return responseResult({
                valid: false,
                errors: ["Atomicity review requires a split plan with at least two commits."],
                warnings: [],
            }, internals.maxDetailItems);
        }
        if (!reserveProposalSlot(state, phase, "splitProposal")) {
            return proposalAlreadyRecorded(internals);
        }
        try {
            const result = await execRepoSplit(cwd, state, internals, splitParams, changelogTargets);
            if (state.splitProposal) {
                phase.value = "finalized";
                queueMicrotask(() => ctx.abort());
            } else {
                releaseProposalSlot(state, phase, "splitProposal");
            }
            return result;
        } catch (error) {
            releaseProposalSlot(state, phase, "splitProposal");
            throw error;
        }
    },
});

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
    const verdictParameterSchema = api.arktype
        .type({
            decision: "'accept' | 'split'",
            concerns: api.arktype.type("string").atMostLength(512).matching(/\S/).array().atMostLength(8),
            rationale: api.arktype.type("string").atMostLength(2_000).matching(/\S/),
        })
        .onUndeclaredKey("reject")
        .narrow(value =>
            (value.decision === "accept" && value.concerns.length === 0) ||
            (value.decision === "split" &&
                value.concerns.length >= 2 &&
                new Set(value.concerns.map(concern => concern.trim())).size === value.concerns.length),
        );
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
            try {
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
            } catch (error) {
                if (decision) break;
                throw error;
            }
        }
        if (!decision) throw new Error("Atomicity critic did not provide a valid verdict.");
        return decision;
    } finally {
        await session.dispose();
    }
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

    const stagedFiles = await stagedFilesOrStageAll(api.pi, cwd);
    if (stagedFiles.length === 0) throw new Error("No local changes to commit.");
    const diffText = (await api.exec("git", ["-c", "diff.mnemonicprefix=false", "diff", "--cached"], { cwd })).stdout;
    const contextFiles = await api.pi.discoverContextFiles(cwd);
    const phase: CommitPhaseState = { value: "propose" };
    const state: CommitAgentState = { diffText };
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
    const tools = nativeTools
        .filter(tool => !["propose_changelog", "propose_commit", "split_commit"].includes(tool.name))
        .concat([
            mkRepoProposalTool(nativeProposalTool, cwd, state, internals, phase),
            mkRepoSplitTool(nativeSplitTool, cwd, state, internals, [], phase),
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
        disableExtensionDiscovery: true,
        skills: [],
        promptTemplates: [],
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
            throw new Error("Atomicity critic required a split_commit proposal with at least two commits.");
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
    const stagedFiles = await api.pi.diff.changedFiles(cwd, { cached: true });
    internals.assignLockFilesToPlan(plan, stagedFiles);
    const plannedFiles = new Set(plan.commits.flatMap(commit => commit.changes.map(change => change.path)));
    const missingFiles = stagedFiles.filter(file => !plannedFiles.has(file));
    if (missingFiles.length > 0) {
        throw new Error(`Split plan missing staged files: ${missingFiles.join(", ")}`);
    }
    const stagedDiff = (await api.exec("git", ["-c", "diff.mnemonicprefix=false", "diff", "--cached", "--binary"], { cwd })).stdout;
    const parsedFiles = new Map(
        internals.parseFileDiffs(stagedDiff).map(file => [file.filename, internals.parseFileHunks(file)] as const),
    );
    const coverageErrors = validateHunkCoverage(stagedFiles, plan.commits, parsedFiles);
    if (coverageErrors.length > 0) {
        throw new Error(`Invalid split plan: ${coverageErrors.join("; ")}`);
    }
    const order = internals.computeDependencyOrder(plan.commits);
    if ("error" in order) throw new Error(order.error);
    const zeroDiff = await api.exec("git", ["-c", "diff.mnemonicprefix=false", "diff", "--cached", "--binary", "--unified=0"], { cwd });
    if (zeroDiff.code !== 0) throw new Error(zeroDiff.stderr || "Unable to read zero-context staged diff.");
    return {
        order,
        stagedDiff,
        zeroDiff: zeroDiff.stdout,
    };
};

export const selectPatch = (
    file: FileDiff,
    selector: HunkSelector,
    internals: CommitInternals,
): string => {
    if (file.isBinary && selector.type !== "all") {
        throw new Error(`Cannot partially select binary file ${file.filename}.`);
    }
    if (selector.type === "all") return file.content;
    const parsed: FileHunks = internals.parseFileHunks(file);
    const hunks = selector.type === "indices"
        ? parsed.hunks.filter(hunk => selector.indices.includes(hunk.index + 1))
        : parsed.hunks.filter(hunk => {
            const start = hunk.newStart;
            const end = hunk.newLines === 0 ? start : start + hunk.newLines - 1;
            return start <= selector.end && selector.start <= end;
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
        const files = change.hunks.type === "lines" ? zeroFiles : regularFiles;
        const file = files.get(change.path);
        if (!file) throw new Error(`No staged diff found for ${change.path}.`);
        return selectPatch(file, change.hunks, internals);
    });
    return `${parts.join("\n")}\n`;
};

interface PublicationEvidence {
    readonly ref: string;
    readonly before: string;
    readonly indexTree: string;
}

const currentEvidence = async (
    cwd: string,
    internals: RuntimeInternals,
): Promise<PublicationEvidence> => {
    const head = await internals.git.head.resolve(cwd);
    if (!head || head.kind !== "ref" || !head.ref || !head.commit) {
        throw new Error("Autommit requires a branch checkout with an existing HEAD.");
    }
    return {
        ref: head.ref,
        before: head.commit,
        indexTree: await internals.git.writeTree(cwd),
    };
};

const assertEvidence = async (
    cwd: string,
    internals: RuntimeInternals,
    expected: PublicationEvidence,
): Promise<PublicationEvidence> => {
    const actual = await currentEvidence(cwd, internals);
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
    cwd: string,
    internals: RuntimeInternals,
    receipt: Receipt,
    expectedHead: string,
): Promise<void> => {
    const actual = await currentEvidence(cwd, internals);
    if (actual.ref !== receipt.ref) throw new Error("Autommit branch changed during receipt recovery.");
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

const recoverPreparedReceipt = async (
    api: CommandAPI,
    cwd: string,
    commonDir: string,
    internals: RuntimeInternals,
    receipt: Receipt,
): Promise<AppliedCommitResult> => {
    const actual = await currentEvidence(cwd, internals);
    if (actual.ref !== receipt.ref) throw new Error("Prepared autommit receipt has an unexpected branch.");
    if (actual.indexTree !== receipt.indexTree) throw new Error("Prepared autommit receipt has an unexpected index.");
    if (actual.before === receipt.before) {
        await casRef(api, cwd, receipt.ref, receipt.after, receipt.before);
        await assertReceiptEvidence(cwd, internals, receipt, receipt.after);
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
    const expected = await currentEvidence(cwd, internals);
    const { order, stagedDiff, zeroDiff } = await validateSplitPlan(api, cwd, plan, internals);
    const worktree = await mkdtemp(join(tmpdir(), "autommit-worktree-"));
    let added = false;
    let patchDir: string | undefined;
    let primaryError: unknown;
    try {
        patchDir = await mkdtemp(join(tmpdir(), "autommit-patch-"));
        const patchPath = join(patchDir, ".autommit.patch");
        await internals.git.worktree.add(cwd, worktree, expected.before, { detach: true });
        added = true;
        for (const commitIndex of order) {
            const commit = plan.commits[commitIndex];
            if (!commit) throw new Error(`Split plan references missing commit ${commitIndex}.`);
            await writeFile(patchPath, buildCommitPatch(commit.changes, stagedDiff, zeroDiff, internals), "utf8");
            const applied = await api.exec("git", ["apply", "--index", "--unidiff-zero", patchPath], { cwd: worktree });
            if (applied.code !== 0) throw new Error(applied.stderr || "Unable to apply split commit patch.");
            await api.pi.commit(worktree, formatCommitMessage(commit.summary, commit.details));
        }
        const currentDiff = (await api.exec("git", ["-c", "diff.mnemonicprefix=false", "diff", "--cached", "--binary"], { cwd })).stdout;
        if (currentDiff !== stagedDiff) throw new Error("Staged snapshot changed during atomic commit preparation.");
        const finalHead = await internals.git.head.sha(worktree);
        if (!finalHead) throw new Error("Atomic split preparation did not create a commit.");
        const preparedTree = await api.exec("git", ["rev-parse", `${finalHead}^{tree}`], { cwd: worktree });
        if (preparedTree.code !== 0) {
            throw new Error(preparedTree.stderr || "Unable to inspect prepared commit tree.");
        }
        if (!preparedCommitTreeMatchesIndex(preparedTree.stdout.trim(), expected.indexTree)) {
            throw new Error("Prepared commit tree does not match the staged index.");
        }
        await assertEvidence(cwd, internals, expected);
        const prepared: Receipt = {
            version: 1,
            state: "prepared",
            ref: expected.ref,
            before: expected.before,
            after: finalHead,
            indexTree: expected.indexTree,
        };
        await writeReceipt(commonDir, prepared);
        await assertEvidence(cwd, internals, expected);
        await casRef(api, cwd, expected.ref, finalHead, expected.before);
        await assertReceiptEvidence(cwd, internals, prepared, finalHead);
        await removeReceipt(commonDir);
        return { messages: [`Created ${order.length} commit${order.length === 1 ? "" : "s"} atomically.`] };
    } catch (error) {
        primaryError = error;
        throw error;
    } finally {
        const cleanupFailures: Array<{ readonly path: string; readonly error: unknown }> = [];
        if (added) {
            try {
                const removed = await internals.git.worktree.tryRemove(cwd, worktree, { force: true });
                if (!removed) {
                    cleanupFailures.push({
                        path: worktree,
                        error: new Error(`Git worktree removal returned false for ${worktree}.`),
                    });
                }
            } catch (error) {
                cleanupFailures.push({ path: worktree, error });
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
        const stagedFiles = await api.pi.diff.changedFiles(cwd, { cached: true });
        if (stagedFiles.length === 0) throw new Error("No staged changes to commit.");
        const proposal = state.proposal;
        const plan: SplitCommitPlan = {
            commits: [{
                changes: stagedFiles.map(path => ({ path, hunks: { type: "all" as const } })),
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
            const git = await loadInternal<CommitInternals["git"]>("utils/git.ts");
            const repository = await git.repo.resolve(ctx.cwd);
            if (!repository) {
                throw new Error("No Git repository found for the current directory.");
            }
            const result = await withOperationLock(repository.commonDir, async () => {
                const receipt = await consumeCompletedReceipt(
                    repository.commonDir,
                    await readReceipt(repository.commonDir),
                );
                const runtimeInternals: RuntimeInternals = { git };
                if (receipt?.state === "prepared") {
                    return recoverPreparedReceipt(api, ctx.cwd, repository.commonDir, runtimeInternals, receipt);
                }
                const internals = await loadCommitInternals(git);
                const state = await runCommitAgent(api, ctx.cwd, ctx.modelRegistry, parsed, internals);
                return applyState(api, ctx.cwd, repository.commonDir, state, internals);
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
