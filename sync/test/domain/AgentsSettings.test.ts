import { describe, expect, test } from "bun:test"

import { Array as Arr } from "effect"

import {
  appendPreservedSections,
  extractPreservedTopLevels,
  parseTomlKeyPath,
  parseTomlTableHeader,
  cliproxyModelsUrl,
  hasCliproxyEndpointPlaceholder,
  parseAgentsSettings,
  renderCliproxyEndpointTemplate,
} from "#domain/AgentsSettings"

describe("agents settings", () => {
  test("validates and normalizes the gateway URL", () => {
    const settings = parseAgentsSettings({ gateway: { base_url: "https://gateway.example.test:9443/v1///" } })
    expect(settings.gateway.base_url).toBe("https://gateway.example.test:9443/v1")
    expect(cliproxyModelsUrl(settings)).toBe("https://gateway.example.test:9443/v1/models")
  })

  test("rejects malformed settings and forbidden endpoints", () => {
    for (const value of [
      null,
      {},
      { gateway: {} },
      { gateway: { base_url: 1 } },
      { gateway: { base_url: "http://host/v1", extra: true } },
      { gateway: { base_url: "http://host/v1" }, extra: true },
      ...Arr.map(
        [
          "",
          " https://host/v1",
          "https://host/api",
          "https://host/v1?",
          "https://host/v1#",
          "https://user:pass@host/v1",
          "ftp://host/v1",
          "https:///v1",
        ],
        (base_url) => ({ gateway: { base_url } }),
      ),
    ]) {
      expect(() => parseAgentsSettings(value)).toThrow()
    }
  })

  test("replaces every endpoint placeholder and requires one", () => {
    const settings = parseAgentsSettings({ gateway: { base_url: "http://localhost:8080/v1/" } })
    const template = `\${CLIPROXY_CLIENT_BASE_URL} \${CLIPROXY_CLIENT_ORIGIN} \${CLIPROXY_CLIENT_BASE_URL}`
    expect(hasCliproxyEndpointPlaceholder(template)).toBe(true)
    expect(renderCliproxyEndpointTemplate(template, settings)).toBe(
      "http://localhost:8080/v1 http://localhost:8080 http://localhost:8080/v1",
    )
    expect(hasCliproxyEndpointPlaceholder("none")).toBe(false)
    expect(() => renderCliproxyEndpointTemplate("none", settings)).toThrow(
      "missing CLIProxyAPI endpoint placeholder",
    )
  })
})

test("parses quoted and dotted TOML headers", () => {
  expect(parseTomlKeyPath(String.raw`"pr\u006fjects".'a.b'`)).toEqual(["projects", "a.b"])
  expect(parseTomlTableHeader(`[[projects.items]] # comment`)).toEqual(["projects", "items"])
  expect(parseTomlTableHeader("[bad.]")).toBeNull()
  expect(parseTomlKeyPath("a..b")).toBeNull()
})

test("extracts matching subtables and array tables in order", () => {
  const doc = String.raw`[hooks.state."orchestrator"]
spawn_count = 3

[hooks.statement]
unrelated = true

[[projects.items]]
name = "p1"

["pr\u006fjects".escaped]
name = "unicode"

[project]
other = 1
`
  expect(extractPreservedTopLevels(doc, ["hooks.state", "projects"]))
    .toBe(String.raw`[hooks.state."orchestrator"]
spawn_count = 3

[[projects.items]]
name = "p1"

["pr\u006fjects".escaped]
name = "unicode"
`)
  expect(extractPreservedTopLevels(doc, [])).toBe("")
  expect(appendPreservedSections("rendered\n", "[user]\nx=1\n")).toBe("rendered\n\n[user]\nx=1\n")
})
