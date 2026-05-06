import { type ExtensionAPI, type ExtensionCommandContext } from "@mariozechner/pi-coding-agent";
import { type ServiceTier, tierLabel } from "./logic.js";
import { getApplicableTierChoices, getEffectiveServiceTier, patchProviderOptionsRequest, type TierChoice } from "./patchers.js";
import { loadSettings, saveSettings, type ProviderOptionsSettings } from "./settings.js";

const STATUS_KEY = "provider-patcher";

const formatStatus = (tier: ServiceTier): string => `tier: openai=${tierLabel(tier)}`;

const setStatus = (ctx: { ui: unknown }, value: string | undefined): void => {
	const ui = ctx.ui as { setStatus?: (key: string, text: string | undefined) => void };
	ui.setStatus?.(STATUS_KEY, value);
};

const choiceText = (choice: TierChoice, current: ServiceTier): string =>
	choice.tier === current ? `${choice.label} ✓ current` : choice.label;

const findChoiceByText = (choices: readonly TierChoice[], current: ServiceTier, text: string): TierChoice | undefined =>
	choices.find((choice) => choiceText(choice, current) === text);

export default function (pi: ExtensionAPI) {
	let settings: ProviderOptionsSettings = {
		serviceTier: { openai: "off" },
	};
	let loaded = false;

	const ensureLoaded = async (): Promise<ProviderOptionsSettings> => {
		if (!loaded) {
			settings = await loadSettings();
			loaded = true;
		}
		return settings;
	};

	const effectiveTier = (model: Parameters<typeof getEffectiveServiceTier>[0]): ServiceTier =>
		getEffectiveServiceTier(model, "openai", settings.serviceTier.openai);

	const updateStatus = (ctx: { ui: unknown; model?: unknown }): void => {
		const tier = effectiveTier(ctx.model as Parameters<typeof getEffectiveServiceTier>[0]);
		setStatus(ctx, tier === "off" ? undefined : formatStatus(tier));
	};

	pi.on("session_start", async (_event, ctx) => {
		await ensureLoaded();
		updateStatus(ctx);
	});

	pi.on("model_select", async (_event, ctx) => {
		await ensureLoaded();
		updateStatus(ctx);
	});

	pi.on("session_shutdown", async (_event, ctx) => {
		setStatus(ctx, undefined);
	});

	pi.on("before_provider_request", async (event, ctx) => {
		const current = await ensureLoaded();
		return patchProviderOptionsRequest({
			model: ctx.model as Parameters<typeof patchProviderOptionsRequest>[0]["model"],
			payload: event.payload,
			settings: current,
		});
	});

	pi.registerCommand("tier", {
		description: "Choose the request service tier for the currently selected model",
		handler: async (_args: string, ctx: ExtensionCommandContext) => {
			await ensureLoaded();

			const choices = getApplicableTierChoices(ctx.model as Parameters<typeof getApplicableTierChoices>[0]);
			if (choices.length === 0) {
				ctx.ui.notify("No service-tier patch applies to the currently selected model.", "info");
				return;
			}

			if (!ctx.hasUI) {
				ctx.ui.notify(`${formatStatus(effectiveTier(ctx.model as Parameters<typeof getEffectiveServiceTier>[0]))}. Run /tier in interactive mode to choose.`, "info");
				return;
			}

			const current = effectiveTier(ctx.model as Parameters<typeof getEffectiveServiceTier>[0]);
			const labels = choices.map((choice) => choiceText(choice, current));
			const selected = await (ctx.ui as unknown as { select: (title: string, options: string[]) => Promise<string | undefined> }).select(
				"Choose service tier for current model",
				labels,
			);
			if (!selected) return;

			const choice = findChoiceByText(choices, current, selected);
			if (!choice) return;

			settings = { ...settings, serviceTier: { ...settings.serviceTier, [choice.provider]: choice.tier } };
			loaded = true;
			await saveSettings(settings);
			updateStatus(ctx);
			ctx.ui.notify(formatStatus(choice.tier), "info");
		},
	});
}
