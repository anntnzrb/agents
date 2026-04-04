import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";

import { applyEditor } from "./editor.ts";
import { handleModelSelect, restoreModeFromSelection } from "./modes-core.ts";
import { cycleMode, handleModeCommand, selectModeUI } from "./modes-ui.ts";
import { setLastObservedModel } from "./modes-state.ts";
import type { ModelSelectEvent } from "./types.ts";

export default function promptEditorExtension(pi: ExtensionAPI): void {
  pi.registerCommand("mode", {
    description: "Select prompt mode",
    handler: async (args, ctx) => {
      await handleModeCommand(pi, args, ctx);
    },
  });

  pi.registerShortcut("ctrl+shift+m", {
    description: "Select prompt mode",
    handler: async (ctx) => {
      await selectModeUI(pi, ctx);
    },
  });

  pi.registerShortcut("ctrl+space", {
    description: "Cycle prompt mode",
    handler: async (ctx) => {
      await cycleMode(pi, ctx);
    },
  });

  const restore = async (ctx: ExtensionContext) => {
    setLastObservedModel(ctx.model?.provider, ctx.model?.id);
    await restoreModeFromSelection(pi, ctx);
    applyEditor(pi, ctx);
  };

  pi.on("session_start", async (_event, ctx) => {
    await restore(ctx);
  });

  pi.on("model_select", async (event: ModelSelectEvent, ctx) => {
    setLastObservedModel(event.model.provider, event.model.id);
    await handleModelSelect(pi, event, ctx);
  });
}
