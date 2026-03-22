#!/usr/bin/env bun

import { Effect } from "effect";

import { main } from "./core/index.ts";

process.exit(await Effect.runPromise(main()));
