// Palettes live in app/themes.css; this list drives the switcher and the
// contrast check. Add a palette by adding its CSS blocks and one entry here.
export const PALETTES = [
  { id: "graphite", label: "Graphite", description: "Neutral slate, restrained blue" },
  { id: "ocean", label: "Ocean", description: "Cool teal-blue on blue-gray" },
  { id: "ember", label: "Ember", description: "Warm neutral, amber accent" },
  { id: "forest", label: "Forest", description: "Green-gray, muted green accent" },
] as const;

export type PaletteId = (typeof PALETTES)[number]["id"];
export const DEFAULT_PALETTE: PaletteId = "graphite";
export const PALETTE_STORAGE_KEY = "opspilot-palette";

export function isPalette(value: unknown): value is PaletteId {
  return PALETTES.some((p) => p.id === value);
}

// Runs before first paint (inline in <head>) so the saved palette never flashes.
export const paletteBootScript = `try{var p=localStorage.getItem("${PALETTE_STORAGE_KEY}");if(${JSON.stringify(
  PALETTES.map((p) => p.id),
)}.indexOf(p)<0)p="${DEFAULT_PALETTE}";document.documentElement.setAttribute("data-theme",p)}catch(e){document.documentElement.setAttribute("data-theme","${DEFAULT_PALETTE}")}`;
