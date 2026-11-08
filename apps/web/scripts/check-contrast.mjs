// WCAG contrast check for every palette in light and dark (UI prompt 4.2 / 16.2).
// Reads the OKLCH tokens straight from app/themes.css and app/globals.css, so the
// check always matches what ships. Exits non-zero on any failure.
//
//   npm run contrast
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parse, wcagContrast } from "culori";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const themesCss = readFileSync(join(root, "app/themes.css"), "utf8");
const globalsCss = readFileSync(join(root, "app/globals.css"), "utf8");
const PALETTES = ["graphite", "ocean", "ember", "forest"];

function tokens(block) {
  const out = {};
  for (const m of block.matchAll(/--([a-z0-9-]+):\s*(oklch\([^)]+\))/g)) out[m[1]] = m[2];
  return out;
}

function blockFor(selectorPattern) {
  const re = new RegExp(`${selectorPattern}\\s*\\{([^}]*)\\}`, "m");
  const m = themesCss.match(re);
  if (!m) throw new Error(`No CSS block for ${selectorPattern}`);
  return tokens(m[1]);
}

const fixed = tokens(globalsCss.match(/:root\s*\{([^}]*)\}/m)[1]);
const fixedDark = { ...fixed, ...tokens(globalsCss.match(/^\.dark\s*\{([^}]*)\}/m)[1]) };

// [foreground token, background token, minimum ratio, what it is]
const TEXT = 4.5;
const UI = 3;
const PAIRS = [
  ["foreground", "background", TEXT, "body text"],
  ["foreground", "card", TEXT, "text on cards"],
  ["foreground", "muted", TEXT, "text on muted surfaces"],
  ["foreground", "sidebar", TEXT, "sidebar text"],
  ["muted-foreground", "background", TEXT, "secondary text"],
  ["muted-foreground", "card", TEXT, "secondary text on cards"],
  ["muted-foreground", "muted", TEXT, "secondary text on muted"],
  ["muted-foreground", "sidebar", TEXT, "inactive nav items"],
  ["card-foreground", "card", TEXT, "card text"],
  ["popover-foreground", "popover", TEXT, "menus and dialogs"],
  ["primary-foreground", "primary", TEXT, "primary buttons"],
  ["primary", "card", TEXT, "links / highlighted values on cards"],
  ["primary", "background", TEXT, "links on the page"],
  ["secondary-foreground", "secondary", TEXT, "secondary buttons"],
  ["accent-foreground", "accent", TEXT, "hovered and active items"],
  ["destructive-foreground", "destructive", TEXT, "destructive buttons"],
  ["ring", "background", UI, "focus ring"],
  ["ring", "card", UI, "focus ring on cards"],
  ["status-down-text", "card", TEXT, "error text on cards"],
  ["status-down-text", "background", TEXT, "error text on the page"],
  ["status-down-text", "muted", TEXT, "error text on muted surfaces"],
  ["status-healthy", "card", UI, "healthy icons"],
  ["kind-fact", "card", UI, "fact icon / border"],
  ["kind-retrieved", "card", UI, "retrieved icon / border"],
  ["kind-hypothesis", "card", UI, "hypothesis icon / border"],
  ["kind-validation", "card", UI, "validation icon / border"],
  ["kind-diagnosis", "card", UI, "diagnosis icon / border"],
  ["kind-recommendation", "card", UI, "recommendation icon / border"],
  ["kind-gap", "card", UI, "gap icon / border"],
];

// Fixed status badges: solid fill with their own text color, identical everywhere.
const BADGES = ["healthy", "degraded", "down", "unknown", "info"].map((s) => [
  `status-${s}-foreground`,
  `status-${s}`,
  TEXT,
  `${s} status badge`,
]);

let failures = 0;
let checks = 0;

function check(label, colors, [fg, bg, min, what]) {
  const a = colors[fg];
  const b = colors[bg];
  if (!a || !b) {
    console.error(`  MISSING  ${label}: ${fg} on ${bg}`);
    failures++;
    return;
  }
  const ratio = wcagContrast(parse(a), parse(b));
  checks++;
  if (ratio < min) {
    failures++;
    console.error(`  FAIL ${label.padEnd(16)} ${what.padEnd(46)} ${fg} on ${bg}: ${ratio.toFixed(2)} < ${min}`);
  }
}

for (const palette of PALETTES) {
  const light = { ...fixed, ...(palette === "graphite" ? blockFor(':root,\\s*\\[data-theme="graphite"\\]') : blockFor(`\\[data-theme="${palette}"\\]`)) };
  const dark = { ...fixedDark, ...(palette === "graphite" ? blockFor('\\.dark,\\s*\\[data-theme="graphite"\\]\\.dark') : blockFor(`\\[data-theme="${palette}"\\]\\.dark`)) };
  for (const [mode, colors] of [["light", light], ["dark", dark]]) {
    const label = `${palette}/${mode}`;
    for (const pair of PAIRS) check(label, colors, pair);
  }
}
for (const pair of BADGES) check("status badges", fixed, pair);

console.log(`${checks} contrast checks across ${PALETTES.length} palettes x 2 modes: ${failures ? `${failures} failed` : "all passed"}`);
process.exit(failures ? 1 : 0);
