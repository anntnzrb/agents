import { describe, expect, it } from "bun:test";
import { htmlToMarkdown } from "@/markdown";

describe("htmlToMarkdown", () => {
  it("converts and cleans markdown", () => {
    const html = "<h1>Title</h1><p>Hello  world , test .</p><a></a>";
    const markdown = htmlToMarkdown(html);
    expect(markdown).toContain("# Title");
    expect(markdown).toContain("Hello world, test.");
    expect(markdown).not.toContain("[](");
  });

  it("collapses extra newlines", () => {
    const html = "<p>Line 1</p><p>Line 2</p><p>Line 3</p>";
    const markdown = htmlToMarkdown(html);
    expect(markdown.split("\n\n").length).toBeGreaterThan(1);
  });
});
