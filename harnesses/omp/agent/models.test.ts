import { expect, test } from "bun:test";

type OmpModelsConfig = {
  readonly providers: {
    readonly "opencode-go": {
      readonly modelOverrides: Readonly<Record<string, { readonly contextWindow: number }>>;
    };
  };
};

test("caps GPT-5.6 model variants at the 272K operating point", async () => {
  const config = Bun.YAML.parse(
    await Bun.file(new URL("./models.yml", import.meta.url)).text(),
  ) as OmpModelsConfig;
  const overrides = config.providers["opencode-go"].modelOverrides;

  expect(overrides["gpt-5.6-luna"]?.contextWindow).toBe(272000);
  expect(overrides["gpt-5.6-sol"]?.contextWindow).toBe(272000);
  expect(overrides["gpt-5.6-terra"]?.contextWindow).toBe(272000);
});
