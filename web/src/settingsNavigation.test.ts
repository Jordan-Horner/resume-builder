import { describe, expect, it } from "vitest";
import { resolveSettingsSection } from "./settingsNavigation";

describe("Settings section routing", () => {
  it("starts with scrapers and restores the last section", () => {
    expect(resolveSettingsSection("/settings", null)).toBe("scrapers");
    expect(resolveSettingsSection("/settings", "blocked-companies")).toBe("blocked-companies");
  });
  it("honors deep links over previous section", () => {
    expect(resolveSettingsSection("/settings/integrations", "scrapers")).toBe("integrations");
    expect(resolveSettingsSection("/settings/blocked-companies", null)).toBe("blocked-companies");
  });
  it("preserves legacy links and safely handles unknown sections", () => {
    expect(resolveSettingsSection("/integrations", "scrapers")).toBe("integrations");
    expect(resolveSettingsSection("/settings/invalid", "integrations")).toBe("scrapers");
  });
});
