import { describe, expect, test } from "bun:test";
import { applyServiceTier, normalizeTier } from "./logic.js";
import {
  effectiveOpenAIServiceTier,
  isOpenAIResponsesRequest,
  patchOpenAIServiceTier,
} from "./openai.js";
import {
  getApplicableTierChoices,
  getEffectiveServiceTier,
  patchProviderOptionsRequest,
} from "./patchers.js";

const responsesModel = {
  id: "gpt-5.2",
  api: "openai-responses",
  provider: "openai",
};

const codexModel = {
  id: "gpt-5.2-codex",
  api: "openai-codex-responses",
  provider: "openai-codex",
};

describe("provider-patcher helpers", () => {
  test("normalizes aliases without hardcoding config values in payload logic", () => {
    expect(normalizeTier("fast")).toBe("priority");
    expect(normalizeTier("normal")).toBe("default");
    expect(normalizeTier("flex")).toBe("flex");
    expect(normalizeTier("off")).toBe("off");
    expect(normalizeTier("garbage")).toBeUndefined();
  });

  test("matches OpenAI Responses payload shape by api, not provider/model ids", () => {
    expect(
      isOpenAIResponsesRequest(responsesModel, { model: "gpt-5.2", input: [] }),
    ).toBe(true);
    expect(
      isOpenAIResponsesRequest(codexModel, {
        model: "gpt-5.2-codex",
        input: [],
      }),
    ).toBe(true);
    expect(
      isOpenAIResponsesRequest(
        { ...responsesModel, provider: "corp-proxy" },
        { model: "x", input: [] },
      ),
    ).toBe(true);
    expect(
      isOpenAIResponsesRequest(
        { ...responsesModel, api: "openai-completions" },
        { model: "x", messages: [] },
      ),
    ).toBe(false);
    expect(isOpenAIResponsesRequest(responsesModel, null)).toBe(false);
  });

  test("injects, updates, or removes service_tier", () => {
    expect(applyServiceTier({ model: "gpt", input: [] }, "priority")).toEqual({
      model: "gpt",
      input: [],
      service_tier: "priority",
    });
    expect(
      applyServiceTier(
        { model: "gpt", input: [], service_tier: "flex" },
        "default",
      ),
    ).toEqual({
      model: "gpt",
      input: [],
      service_tier: "default",
    });
    expect(
      applyServiceTier(
        { model: "gpt", input: [], service_tier: "priority" },
        "off",
      ),
    ).toEqual({
      model: "gpt",
      input: [],
    });
    expect(
      applyServiceTier({ model: "gpt", input: [] }, "off"),
    ).toBeUndefined();
  });

  test("openai patcher combines matching and service tier mutation", () => {
    expect(
      patchOpenAIServiceTier(
        responsesModel,
        { model: "gpt", input: [] },
        "priority",
      ),
    ).toEqual({
      model: "gpt",
      input: [],
      service_tier: "priority",
    });
    expect(
      patchOpenAIServiceTier(
        { ...responsesModel, api: "openai-completions" },
        { model: "gpt", messages: [] },
        "priority",
      ),
    ).toBeUndefined();
    expect(
      patchOpenAIServiceTier(
        codexModel,
        { model: "gpt", input: [], service_tier: "priority" },
        "flex",
      ),
    ).toEqual({
      model: "gpt",
      input: [],
    });
    expect(
      patchOpenAIServiceTier(
        codexModel,
        { model: "gpt", input: [] },
        "default",
      ),
    ).toBeUndefined();
  });

  test("provider patch registry exposes tier choices for the selected model", () => {
    expect(
      getApplicableTierChoices(responsesModel).map((choice) => choice.tier),
    ).toEqual(["off", "default", "flex", "priority"]);
    expect(
      getApplicableTierChoices(codexModel).map((choice) => choice.tier),
    ).toEqual(["off", "priority"]);
    expect(
      getApplicableTierChoices({
        ...responsesModel,
        api: "openai-completions",
      }),
    ).toEqual([]);
  });

  test("codex responses only treats priority as an active service tier", () => {
    expect(effectiveOpenAIServiceTier(codexModel, "priority")).toBe("priority");
    expect(effectiveOpenAIServiceTier(codexModel, "default")).toBe("off");
    expect(effectiveOpenAIServiceTier(codexModel, "flex")).toBe("off");
    expect(getEffectiveServiceTier(codexModel, "openai", "flex")).toBe("off");
  });

  test("provider patch registry applies configured provider-specific options", () => {
    expect(
      patchProviderOptionsRequest({
        model: responsesModel,
        payload: { model: "gpt", input: [] },
        settings: { serviceTier: { openai: "priority" } },
      }),
    ).toEqual({ model: "gpt", input: [], service_tier: "priority" });
    expect(
      patchProviderOptionsRequest({
        model: codexModel,
        payload: { model: "gpt", input: [], service_tier: "priority" },
        settings: { serviceTier: { openai: "flex" } },
      }),
    ).toEqual({ model: "gpt", input: [] });
  });
});
