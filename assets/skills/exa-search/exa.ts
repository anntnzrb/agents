import { runExa } from "./src/cli";

if (import.meta.main) {
  const code = await runExa(process.argv.slice(2));
  process.exit(code);
}
