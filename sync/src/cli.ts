#!/usr/bin/env bun

import { launchMain, main } from "@core/index.ts";

const args = process.argv.slice(2);
const command = args[0];

if (command === "launch") {
  const sourceName = args[1];
  const separator = args[2];
  if (!sourceName || (separator !== "--" && separator !== undefined)) {
    console.error("sync: usage: launch HARNESS -- [ARGS...]");
    process.exit(2);
  }
  process.exit(await launchMain(sourceName, args.slice(separator ? 3 : 2)));
}

if (command === "sync" || command === undefined) {
  process.exit(await main());
}

console.error(`sync: unknown command: ${command}`);
process.exit(2);
