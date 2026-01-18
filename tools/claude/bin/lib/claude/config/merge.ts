/**
 * Configuration merging utilities
 */

import { existsSync } from "fs";
import { safeJsonRead, safeJsonWrite } from "../../shared/json.ts";
import { paths } from "./paths.ts";

/**
 * Merge global configs into final global configuration
 * @returns Promise that resolves when merge is complete or skipped
 */
export const mergeConfigs = async (): Promise<void> => {
  if (!existsSync(paths.claude)) return;

  await Promise.all([safeJsonRead(paths.global), safeJsonRead(paths.claude)])
    .then(([global, claude]) =>
      safeJsonWrite(paths.global, { ...global, ...claude }),
    )
    .catch((err) => console.warn(`Config merge failed: ${err}`));
};
