import { mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const outputPath = join(root, "public", "THIRD_PARTY_NOTICES.txt");
const checkOnly = process.argv.includes("--check");
const lock = JSON.parse(readFileSync(join(root, "package-lock.json"), "utf8"));
// Vite emits its modulepreload polyfill/preload helper and Rolldown emits
// bundler runtime helpers into the public artifact. They are build dependencies
// rather than npm production dependencies, so include them explicitly.
const emittedBuildPackages = new Set(["node_modules/vite", "node_modules/rolldown"]);

function normalize(text) {
  return text
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) => line.trimEnd())
    .join("\n")
    .trimEnd();
}

function licenseText(packagePath, packageName) {
  const candidates = readdirSync(packagePath)
    .filter((name) => /^(licen[cs]e|copying|copyright)(\.|$)/i.test(name))
    .sort((left, right) => left.localeCompare(right));
  if (candidates.length > 0) {
    return normalize(readFileSync(join(packagePath, candidates[0]), "utf8"));
  }
  const override = join(
    root,
    "scripts",
    "license-overrides",
    `${packageName.replaceAll("/", "__").replaceAll("@", "")}.txt`,
  );
  try {
    return normalize(readFileSync(override, "utf8"));
  } catch {
    throw new Error(`No license text found for production dependency ${packageName}`);
  }
}

const dependencies = Object.entries(lock.packages)
  .filter(([path, metadata]) => (
    path.startsWith("node_modules/") && (!metadata.dev || emittedBuildPackages.has(path))
  ))
  .map(([path, metadata]) => {
    const packagePath = join(root, path);
    const manifest = JSON.parse(readFileSync(join(packagePath, "package.json"), "utf8"));
    return {
      name: manifest.name,
      version: metadata.version,
      license: metadata.license || manifest.license || "UNKNOWN",
      text: licenseText(packagePath, manifest.name),
    };
  })
  .sort((left, right) => left.name.localeCompare(right.name) || left.version.localeCompare(right.version));

const separator = "=".repeat(78);
const generated = `${normalize([
  "AGENT ECONOMY DASHBOARD - THIRD-PARTY NOTICES",
  "",
  "This file is generated from dashboard/package-lock.json and the license files",
  "distributed with every production dependency, plus build packages whose",
  "polyfills/runtime helpers are emitted into the public bundle. Do not edit it",
  "by hand; run",
  "`npm run licenses` from dashboard after dependency changes.",
  "",
  `Runtime and artifact-contributing packages: ${dependencies.length}`,
  "",
  ...dependencies.flatMap((dependency) => [
    separator,
    `${dependency.name}@${dependency.version}`,
    `Declared license: ${dependency.license}`,
    separator,
    dependency.text,
    "",
  ]),
].join("\n"))}\n`;

if (checkOnly) {
  let committed = "";
  try {
    committed = readFileSync(outputPath, "utf8");
  } catch {
    throw new Error("THIRD_PARTY_NOTICES.txt is missing; run `npm run licenses`");
  }
  const committedWithCanonicalNewlines = committed.replace(/\r\n?/g, "\n");
  if (committedWithCanonicalNewlines !== generated) {
    throw new Error("THIRD_PARTY_NOTICES.txt is stale; run `npm run licenses`");
  }
} else {
  mkdirSync(dirname(outputPath), { recursive: true });
  writeFileSync(outputPath, generated, "utf8");
}
