export interface DiffHunk {
    readonly index: number;
    readonly newStart: number;
    readonly newLines: number;
    readonly content: string;
}

export interface ParsedFile {
    readonly filename: string;
    readonly isBinary: boolean;
    readonly content: string;
    readonly hunks: readonly DiffHunk[];
}

const unquotePath = (value: string): string => {
    if (value.length < 2 || value[0] !== '"' || value[value.length - 1] !== '"') return value;
    let result = "";
    const inner = value.slice(1, -1);
    for (let index = 0; index < inner.length; index += 1) {
        const character = inner[index];
        if (character !== "\\" || index + 1 >= inner.length) {
            result += character;
            continue;
        }
        const next = inner[index + 1];
        if (next === "\\" || next === '"') {
            result += next;
            index += 1;
            continue;
        }
        result += character;
    }
    return result;
};

const parseHunkHeader = (line: string): DiffHunk | undefined => {
    const match = /^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@/.exec(line);
    if (!match) return undefined;
    const newStart = Number(match[1]);
    const newLines = match[2] === undefined ? 1 : Number(match[2]);
    return {
        index: 0,
        newStart: Number.isFinite(newStart) ? newStart : 0,
        newLines: Number.isFinite(newLines) ? newLines : 0,
        content: "",
    };
};

const findDiffHeader = (diffText: string, from: number): number => {
    if (diffText.startsWith("diff --git ", from)) return from;
    const newline = diffText.indexOf("\ndiff --git ", from);
    return newline < 0 ? -1 : newline + 1;
};

export const parseFileDiffs = (diffText: string): readonly ParsedFile[] => {
    const files: ParsedFile[] = [];
    if (!diffText) return files;

    let cursor = 0;
    while (cursor < diffText.length) {
        const headerStart = findDiffHeader(diffText, cursor);
        if (headerStart < 0) break;
        const headerEnd = diffText.indexOf("\n", headerStart);
        if (headerEnd < 0) break;
        const headerLine = diffText.slice(headerStart, headerEnd);
        const pathMatch = /^diff --git a\/(.*?) b\/(.*)$/u.exec(headerLine);
        if (!pathMatch) {
            cursor = headerEnd + 1;
            continue;
        }
        const nextStart = findDiffHeader(diffText, headerEnd + 1);
        const fileEnd = nextStart < 0 ? diffText.length : nextStart;
        const content = diffText.slice(headerStart, fileEnd);

        const body = diffText.slice(headerEnd + 1, fileEnd);
        const hunks: DiffHunk[] = [];
        let search = 0;
        while (search < body.length) {
            const hunkStart = body.indexOf("\n@@", search);
            const hunkHeaderStart = hunkStart < 0 ? -1 : hunkStart + 1;
            if (hunkHeaderStart < 0) break;
            const hunkHeaderEnd = body.indexOf("\n", hunkHeaderStart);
            if (hunkHeaderEnd < 0) break;
            const header = body.slice(hunkHeaderStart, hunkHeaderEnd);
            const parsed = parseHunkHeader(header);
            if (!parsed) {
                search = hunkHeaderEnd + 1;
                continue;
            }
            const nextHunkStart = body.indexOf("\n@@", hunkHeaderEnd);
            const hunkContentEnd = nextHunkStart < 0 ? body.length : nextHunkStart;
            hunks.push({
                ...parsed,
                content: body.slice(hunkHeaderStart, hunkContentEnd),
                index: hunks.length + 1,
            });
            search = nextHunkStart < 0 ? body.length : nextHunkStart;
        }

        const isBinary =
            hunks.length === 0 &&
            (body.includes("Binary files ") || body.includes("GIT binary patch"));
        files.push({
            filename: unquotePath(pathMatch[2] ?? ""),
            isBinary,
            content,
            hunks,
        });
        cursor = fileEnd;
    }
    return files;
};

export const parseFileHunks = (file: ParsedFile): ParsedFile => file;

export const findFileInDiff = (
    parsedFiles: readonly ParsedFile[],
    filename: string,
): ParsedFile | undefined =>
    parsedFiles.find(file => file.filename === filename);
