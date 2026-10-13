import type { Plugin } from "@opencode/plugin/tui";

const THRESHOLD_MS = 5000;

export default {
  id: "autobg",
  setup(context) {
    const timers = new Map<string, ReturnType<typeof setTimeout>>();

    const open = (sessionID: string) => {
      const session = context.data.session.get(sessionID);
      if (!session || session.parentID !== undefined) return false;
      const route = context.ui.router.current();
      if (route.type === "session" && context.data.session.root(route.sessionID) === sessionID) return true;
      return context.ui.tabs.list().some((tab) => tab.sessionID === sessionID);
    };

    const clear = (id: string) => {
      clearTimeout(timers.get(id));
      timers.delete(id);
    };

    const dispose = [
      context.data.on("session.tool.called", (event) => {
        if (event.data.executed) return;
        const { sessionID } = event.data;
        const id = `${sessionID}:${event.data.id}`;
        clear(id);
        timers.set(
          id,
          setTimeout(() => {
            timers.delete(id);
            if (!open(sessionID)) return;
            void context.client.session.background({ sessionID }).catch(() => {});
          }, THRESHOLD_MS),
        );
      }),
      context.data.on("session.tool.success", (event) => clear(`${event.data.sessionID}:${event.data.id}`)),
      context.data.on("session.tool.failed", (event) => clear(`${event.data.sessionID}:${event.data.id}`)),
    ];

    return () => {
      dispose.forEach((stop) => stop());
      timers.forEach((timer) => clearTimeout(timer));
    };
  },
} satisfies Plugin.Definition;
