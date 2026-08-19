import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { Effect, Schema } from "effect";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import { normalizeTier, type ServiceTier } from "./logic.js";

type JsonObject = Record<string, unknown>;

export type ProviderOptionsProvider = "openai";

export type ProviderOptionsSettings = {
  serviceTier: Record<ProviderOptionsProvider, ServiceTier>;
};

export class ProviderSettingsError extends Schema.TaggedError<ProviderSettingsError>()(
  "ProviderSettingsError",
  {
    message: Schema.String,
    cause: Schema.optional(Schema.Unknown),
  },
) {}

const SETTINGS_NAMESPACE = "providerPatcher";
const LEGACY_PROVIDER_OPTIONS_NAMESPACE = "providerOptions";
const LEGACY_SETTINGS_NAMESPACE = "serviceTier";
const DEFAULT_SETTINGS: ProviderOptionsSettings = {
  serviceTier: { openai: "off" },
};

const isObject = (value: unknown): value is JsonObject =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const settingsPath = (): string => join(getAgentDir(), "settings.json");

const readSettingsObjectEffect = Effect.fn("readSettingsObject")(function*(): Effect.fn.Return<
  JsonObject,
  never
> {
  return yield* Effect.tryPromise({
    try: () => readFile(settingsPath(), "utf8"),
    catch: () => "",
  }).pipe(
    Effect.map((raw) => {
      try {
        const parsed = JSON.parse(raw);
        return isObject(parsed) ? parsed : {};
      } catch {
        return {};
      }
    }),
    Effect.orElseSucceed(() => ({})),
  );
});

const getOpenAITier = (namespace: unknown): ServiceTier | undefined => {
  if (!isObject(namespace)) return undefined;
  return normalizeTier(
    typeof namespace["openai"] === "string" ? namespace["openai"] : undefined,
  );
};

const getNestedOpenAIServiceTier = (
  namespace: unknown,
): ServiceTier | undefined => {
  if (!isObject(namespace)) return undefined;
  return getOpenAITier(namespace["serviceTier"]);
};

const parseNamespace = (settings: JsonObject): ProviderOptionsSettings => {
  const configured = settings[SETTINGS_NAMESPACE];
  const legacyProviderOptions = settings[LEGACY_PROVIDER_OPTIONS_NAMESPACE];
  const legacy = settings[LEGACY_SETTINGS_NAMESPACE];
  return {
    serviceTier: {
      openai:
        getNestedOpenAIServiceTier(configured) ??
        getOpenAITier(configured) ??
        getNestedOpenAIServiceTier(legacyProviderOptions) ??
        getOpenAITier(legacyProviderOptions) ??
        getOpenAITier(legacy) ??
        DEFAULT_SETTINGS.serviceTier.openai,
    },
  };
};

export const loadSettingsEffect = Effect.fn("loadSettings")(function*(): Effect.fn.Return<
  ProviderOptionsSettings,
  never
> {
  const settings = yield* readSettingsObjectEffect();
  return parseNamespace(settings);
});

export const loadSettings = (): Promise<ProviderOptionsSettings> =>
  Effect.runPromise(loadSettingsEffect());

export const saveSettingsEffect = Effect.fn("saveSettings")(function*(
  next: ProviderOptionsSettings,
): Effect.fn.Return<void, ProviderSettingsError> {
  const path = settingsPath();
  const settings = yield* readSettingsObjectEffect();
  const existing = isObject(settings[SETTINGS_NAMESPACE])
    ? settings[SETTINGS_NAMESPACE]
    : {};
  settings[SETTINGS_NAMESPACE] = {
    ...existing,
    serviceTier: {
      ...(isObject(existing["serviceTier"]) ? existing["serviceTier"] : {}),
      openai: next.serviceTier.openai,
    },
  };

  yield* Effect.tryPromise({
    try: async () => {
      await mkdir(dirname(path), { recursive: true });
      await writeFile(path, `${JSON.stringify(settings, null, 2)}\n`, "utf8");
    },
    catch: (cause) =>
      new ProviderSettingsError({
        message: `Failed to save provider settings: ${cause instanceof Error ? cause.message : String(cause)}`,
        cause,
      }),
  });
});

export const saveSettings = (next: ProviderOptionsSettings): Promise<void> =>
  Effect.runPromise(saveSettingsEffect(next));
