// Offline runtime; only the reviewed, locked JOSE library is bundled.
import { build } from "esbuild";
import { readFile, writeFile } from "node:fs/promises";
const license = await readFile("node_modules/jose/LICENSE.md", "utf8");
const result = await build({
  entryPoints: ["scripts/vertente_jose.js"], bundle: true, format: "esm",
  platform: "browser", target: "es2022", minify: true, write: false,
  banner: { js: `/*! jose 6.2.15 — MIT\n${license}*/` },
});
const output = result.outputFiles[0].text;
const path = "vertente/assets/jose.js";
if (process.argv.includes("--check")) {
  if (await readFile(path, "utf8") !== output) throw new Error("Rebuild JOSE with node scripts/build_jose.mjs");
} else await writeFile(path, output);
