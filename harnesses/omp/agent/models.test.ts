import { expect, test } from "bun:test";

type OmpModelsConfig = {
  readonly providers: {
    readonly cliproxy: {
      readonly modelOverrides: Readonly<Record<string, { readonly contextWindow: number }>>;
    };
  };
};

test("caps GPT-5.6 aliases at the 272K operating point", async () => {
  const config = Bun.YAML.parse(
    await Bun.file(new URL("./models.yml", import.meta.url)).text(),
  ) as OmpModelsConfig;
  const overrides = config.providers.cliproxy.modelOverrides;
  const modelIds = [
    "chatgpt/nnn-gpt-5.6-luna-max",
    "chatgpt/nnn-gpt-5.6-luna-max-fast",
    "chatgpt/nnn-gpt-5.6-sol-high",
    "chatgpt/nnn-gpt-5.6-terra-max",
    "chatgpt/nnn-gpt-5.6-terra-max-fast",
  ];

  for (const modelId of modelIds) {
    expect(overrides[modelId]?.contextWindow).toBe(272000);
  }
});
