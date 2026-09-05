export const SETTINGS_SECTIONS = [
  { id: "scrapers", label: "Scrapers" },
  { id: "integrations", label: "Integrations" },
  { id: "blocked-companies", label: "Blocked companies" },
] as const;
export type SettingsSection = typeof SETTINGS_SECTIONS[number]["id"];
export const SETTINGS_SECTION_KEY = "resume-builder.settings-section.v1";

export function resolveSettingsSection(path: string, previous: string | null): SettingsSection {
  if (path.split("/")[1] === "integrations") return "integrations";
  const candidate = path.split("/")[2] || previous;
  return SETTINGS_SECTIONS.find((section) => section.id === candidate)?.id || "scrapers";
}
