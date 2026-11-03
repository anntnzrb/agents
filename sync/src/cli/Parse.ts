import { Array as Arr, String as Str } from "effect"

export type CliCommand =
  | { readonly _tag: "Sync" }
  | { readonly _tag: "Update" }
  | { readonly _tag: "Launch"; readonly name: string; readonly args: readonly string[] }
  | { readonly _tag: "Job"; readonly name: "npm-cache-clean" | "refresh-packages" }
  | { readonly _tag: "Help"; readonly text: string }
  | { readonly _tag: "Usage"; readonly text: string }

export const HELP_TEXT = `sync — Reconcile AI agent configurations, skills, and harness environments from SSOT.

Usage:
  sync [sync]
  sync launch <name> [-- <args...>]
  sync update
  sync job <npm-cache-clean|refresh-packages>
  sync -h | --help | help

Commands:
  sync (default)
    Reconciles harness configurations, instruction files (HARNESS.md),
    skills, tools, secrets, and generated launch wrappers (~/.local/bin).

  launch <name> [-- <args...>]
    Executes the cached harness or tool immediately; without a cache,
    runs best-effort reconciliation and installs the package first.

  update
    Fast-forwards a clean main checkout of the SSOT from origin and
    reconciles it when the commit is new. Scheduled in the background by
    the machine configuration.

  job <npm-cache-clean|refresh-packages>
    Runs scheduled maintenance jobs driven by the machine configuration.

Options:
  -h, --help, help    Show this help message.
`

export const LAUNCH_HELP_TEXT = `Usage: sync launch <name> [-- <args...>]

Launch a managed harness or tool by name with optional forwarded arguments.
`

export const JOB_HELP_TEXT = `usage: sync job [-h] {npm-cache-clean,refresh-packages} ...

Run scheduled maintenance jobs driven by the machine configuration.

positional arguments:
  {npm-cache-clean,refresh-packages}
    npm-cache-clean     Empty npm cache while respecting npm-tools locks.
    refresh-packages    Refresh cached harness and tool packages without
                        waiting on busy locks.

options:
  -h, --help            show this help message and exit
`

const SYNC_USAGE = "sync: usage: sync\nRun 'sync --help' for available commands.\n"
const LAUNCH_USAGE = "sync: usage: launch NAME -- [ARGS...]\n"
const JOB_USAGE = "sync: usage: job <npm-cache-clean|refresh-packages>\n"
const JOB_ARGPARSE_USAGE = "usage: sync job [-h] {npm-cache-clean,refresh-packages} ...\n"
const isHelp = (value: string | undefined) => value === "help" || value === "-h" || value === "--help"
const help = (text: string): CliCommand => ({ _tag: "Help", text })
const usage = (text: string): CliCommand => ({ _tag: "Usage", text })

const isNonEmpty = (value: string | undefined): value is string => value !== undefined && value !== ""

const parseSync = (rest: readonly string[]): CliCommand => {
  if (rest.length === 0) {
    return { _tag: "Sync" }
  }
  return rest.length === 1 && isHelp(rest[0]) ? help(HELP_TEXT) : usage(SYNC_USAGE)
}

const parseLaunch = (rest: readonly string[]): CliCommand => {
  const [name, separator, ...forwarded] = rest
  if (isHelp(name)) {
    return help(LAUNCH_HELP_TEXT)
  }
  if (isNonEmpty(name) && rest.length === 1) {
    return { _tag: "Launch", name, args: [] }
  }
  if (isNonEmpty(name) && separator === "--") {
    return { _tag: "Launch", name, args: forwarded }
  }
  return usage(LAUNCH_USAGE)
}

// Reproduces the argparse subparser messages the job command has always printed.
const parseUnknownJob = (name: string): CliCommand => {
  if (name === "-h" || name === "--help") {
    return help(JOB_HELP_TEXT)
  }
  if (Str.startsWith("-")(name)) {
    return usage(`${JOB_ARGPARSE_USAGE}sync job: error: the following arguments are required: job\n`)
  }
  return usage(
    `${JOB_ARGPARSE_USAGE}sync job: error: argument job: invalid choice: '${name}' (choose from 'npm-cache-clean', 'refresh-packages')\n`,
  )
}

const parseJob = (rest: readonly string[]): CliCommand => {
  const [name, ...extra] = rest
  if (name === undefined) {
    return usage(JOB_USAGE)
  }
  if (rest.length === 1 && isHelp(name)) {
    return help(JOB_HELP_TEXT)
  }
  if (name !== "npm-cache-clean" && name !== "refresh-packages") {
    return parseUnknownJob(name)
  }
  if (extra.includes("-h") || extra.includes("--help")) {
    return help(`usage: sync job ${name} [-h]\n\noptions:\n  -h, --help  show this help message and exit\n`)
  }
  if (extra.length > 0) {
    return usage(`${JOB_ARGPARSE_USAGE}sync job: error: unrecognized arguments: ${Arr.join(extra, " ")}\n`)
  }
  return { _tag: "Job", name }
}

export const parseCli = (args: readonly string[]): CliCommand => {
  const [first, ...rest] = args
  if (first === undefined) {
    return { _tag: "Sync" }
  }
  if (isHelp(first) && rest.length === 0) {
    return help(HELP_TEXT)
  }
  switch (first) {
    case "sync": {
      return parseSync(rest)
    }
    case "update": {
      return { _tag: "Update" }
    }
    case "launch": {
      return parseLaunch(rest)
    }
    case "job": {
      return parseJob(rest)
    }
    default: {
      return usage(SYNC_USAGE)
    }
  }
}
