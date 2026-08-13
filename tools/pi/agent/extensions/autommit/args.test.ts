import { describe, expect, test } from "bun:test";
import { composeContext, parseArgs, splitArgs } from "./args.js";

describe("autommit arguments", () => {
    test("accepts positional context and repeated --context values", () => {
        const parsed = parseArgs(["refactor", "--context", "keep", "--context=tests"]);
        expect(parsed).toEqual({ context: ["refactor", "keep", "tests"] });
        if ("context" in parsed) expect(composeContext(parsed)).toBe("refactor\n\nkeep\n\ntests");
    });

    test("supports quoted command arguments", () => {
        expect(splitArgs('--context "preserve unstaged work" \'split docs\'')).toEqual([
            "--context",
            "preserve unstaged work",
            "split docs",
        ]);
    });

    test("rejects unsupported options and missing values", () => {
        expect(parseArgs(["--bogus"])).toEqual({ error: "Unsupported option: --bogus" });
        expect(parseArgs(["--context"])).toEqual({ error: "--context requires a value" });
        expect(parseArgs(["--context="])).toEqual({ error: "--context requires a value" });
    });
});
