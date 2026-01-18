const requiredKeys = ["EXA_API_KEY"] as const;
const optionalKeys = ["EXA_MCP_URL", "EXA_MCP_TOOLS"] as const;

const missing = requiredKeys.filter((key) =>
  !(process.env[key]?.trim()),
);

if (missing.length > 0) {
  console.error(`Missing required env: ${missing.join(", ")}`);
  console.error("Set EXA_API_KEY before running any tools.");
  process.exitCode = 1;
} else {
  console.log("EXA_API_KEY is set.");
}

for (const key of optionalKeys) {
  const value = process.env[key]?.trim();
  if (value) {
    console.log(`${key}=${value}`);
  }
}
