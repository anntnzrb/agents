#!/usr/bin/env bun

import { launchMain, main } from "@core/index.ts";

const args = Bun.argv.slice(2);
const command = args[0];

if (command === "launch") {
  const sourceName = args[1];
  const separator = args[2];
  if (!sourceName || (separator !== "--" && separator !== undefined)) {
    console.error("sync: usage: launch NAME -- [ARGS...]");
    process.exit(2);
  }
  process.exit(await launchMain(sourceName, args.slice(separator ? 3 : 2)));
}

if (command === "sync" || command === undefined) {
  const syncArgs = command === "sync" ? args.slice(1) : args;
  if (syncArgs.some((arg) => arg !== "--refresh-models")) {
    console.error("sync: usage: sync [--refresh-models]");
    process.exit(2);
  }
  process.exit(await main({ forceModelRefresh: syncArgs.includes("--refresh-models") }));
}

console.error(`sync: unknown command: ${command}`);
process.exit(2);
