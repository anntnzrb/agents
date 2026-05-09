import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import { normalizeTier, type ServiceTier } from "./logic.js";

type JsonObject = Record<string, unknown>;

export type ProviderOptionsProvider = "openai";

export type ProviderOptionsSettings = {
	serviceTier: Record<ProviderOptionsProvider, ServiceTier>;
};

const SETTINGS_NAMESPACE = "providerPatcher";
const LEGACY_PROVIDER_OPTIONS_NAMESPACE = "providerOptions";
const LEGACY_SETTINGS_NAMESPACE = "serviceTier";
const DEFAULT_SETTINGS: ProviderOptionsSettings = { serviceTier: { openai: "off" } };

const isObject = (value: unknown): value is JsonObject => typeof value === "object" && value !== null && !Array.isArray(value);

const settingsPath = (): string => join(getAgentDir(), "settings.json");

const readSettingsObject = async (): Promise<JsonObject> => {
	try {
		const raw = await readFile(settingsPath(), "utf8");
		const parsed: unknown = JSON.parse(raw);
		return isObject(parsed) ? parsed : {};
	} catch (error) {
		if ((error as { code?: unknown }).code === "ENOENT") return {};
		throw error;
	}
};

const getOpenAITier = (namespace: unknown): ServiceTier | undefined => {
	if (!isObject(namespace)) return undefined;
	return normalizeTier(typeof namespace["openai"] === "string" ? namespace["openai"] : undefined);
};

const getNestedOpenAIServiceTier = (namespace: unknown): ServiceTier | undefined => {
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

export const loadSettings = async (): Promise<ProviderOptionsSettings> => {
	const settings = await readSettingsObject();
	return parseNamespace(settings);
};

export const saveSettings = async (next: ProviderOptionsSettings): Promise<void> => {
	const path = settingsPath();
	const settings = await readSettingsObject();
	const existing = isObject(settings[SETTINGS_NAMESPACE]) ? settings[SETTINGS_NAMESPACE] : {};
	settings[SETTINGS_NAMESPACE] = {
		...existing,
		serviceTier: {
			...(isObject(existing["serviceTier"]) ? existing["serviceTier"] : {}),
			openai: next.serviceTier.openai,
		},
	};
	await mkdir(dirname(path), { recursive: true });
	await writeFile(path, `${JSON.stringify(settings, null, 2)}\n`, "utf8");
};
