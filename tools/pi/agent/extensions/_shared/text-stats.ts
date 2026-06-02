export type ContentStats = {
  bytes: number;
  lines: number;
};

export const countLogicalLines = (content: string): number => {
  if (content.length === 0) return 0;

  let end = content.length;
  if (content.endsWith("\r\n")) {
    end -= 2;
  } else if (content.endsWith("\n")) {
    end -= 1;
  }
  if (end <= 0) return 0;

  let lines = 1;
  for (let index = 0; index < end; index++) {
    if (content.charCodeAt(index) === 10) lines++;
  }
  return lines;
};

export const getUtf8ContentStats = (content: string): ContentStats => ({
  bytes: Buffer.byteLength(content, "utf-8"),
  lines: countLogicalLines(content),
});
