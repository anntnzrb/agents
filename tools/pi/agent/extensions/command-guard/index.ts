import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { createCommandGuard } from "./extension";

const __dirname = dirname(fileURLToPath(import.meta.url));
const configPath = join(__dirname, "command-guard.jsonc");

export default createCommandGuard(configPath);
