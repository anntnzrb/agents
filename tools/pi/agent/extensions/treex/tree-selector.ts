import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { TreeSelectorComponent } from "@earendil-works/pi-coding-agent";

type TreexSessionManager = {
    getTree(): unknown[];
    getLeafId(): string | null;
};

type TreeSelectorContext = {
    sessionManager: TreexSessionManager;
    ui: {
        custom<T>(
            factory: (
                tui: { terminal?: { rows?: number }; requestRender(): void },
                theme: unknown,
                keybindings: unknown,
                done: (result: T) => void,
            ) => unknown,
        ): Promise<T>;
    };
};

type LabelCapableExtensionAPI = ExtensionAPI & {
    setLabel?: (entryId: string, label?: string) => void;
};

export async function showTreeSelector(
    ctx: TreeSelectorContext,
    pi?: ExtensionAPI,
): Promise<string | null> {
    const tree = ctx.sessionManager.getTree();
    const currentLeafId = ctx.sessionManager.getLeafId();
    if (!tree || tree.length === 0) return null;

    return ctx.ui.custom<string | null>((tui, _theme, _kb, done) => {
        const rows = tui.terminal?.rows ?? 40;
        const selector = new TreeSelectorComponent(
            tree,
            currentLeafId,
            rows,
            (entryId: string) => done(entryId),
            () => done(null),
            (entryId: string, label?: string) => {
                (pi as LabelCapableExtensionAPI | undefined)?.setLabel?.(entryId, label);
            },
            undefined,
            undefined,
        );
        return {
            render: (width: number) => selector.render(width),
            invalidate: () => selector.invalidate(),
            handleInput: (data: string) => {
                selector.handleInput(data);
                tui.requestRender();
            },
            get focused() {
                return selector.focused;
            },
            set focused(value: boolean) {
                selector.focused = value;
            },
        };
    });
}
