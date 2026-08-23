import { registerAdapter } from "#registry";
import { G2aAdapter } from "./g2a.ts";
import { KinguinAdapter } from "./kinguin.ts";
import { PlatiAdapter } from "./plati.ts";
import { Z2uAdapter } from "./z2u.ts";
import { FunPayAdapter } from "./funpay.ts";

export { G2aAdapter } from "./g2a.ts";
export { KinguinAdapter } from "./kinguin.ts";
export { PlatiAdapter } from "./plati.ts";
export { Z2uAdapter } from "./z2u.ts";
export { FunPayAdapter } from "./funpay.ts";
export * from "./common.ts";

let isInitialized = false;

/**
 * Initialize and register all built-in marketplace adapters.
 */
export function registerBuiltinAdapters(): void {
  if (isInitialized) return;
  registerAdapter(new G2aAdapter());
  registerAdapter(new KinguinAdapter());
  registerAdapter(new PlatiAdapter());
  registerAdapter(new Z2uAdapter());
  registerAdapter(new FunPayAdapter());
  isInitialized = true;
}
