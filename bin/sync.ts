#!/usr/bin/env bun

import { Effect } from "effect";

import { main } from "./lib.ts";

process.exit(await Effect.runPromise(main()));
