/**
 * The five tabs, and the mapping between a URL and the element that fills the screen.
 *
 * One list, used by the tab strip, by the router and by the content area, so a tab cannot
 * exist in the strip without an element behind it or the other way round.
 */

export interface TabDefinition {
  /** The path segment, which is also the tab's id: `/device_links/rules`. */
  id: string;
  /** What the tab says. */
  label: string;
  /** An `mdi:` icon name, shown instead of the label when the screen is narrow. */
  icon: string;
  /** The custom element that fills the content area for this tab. */
  tagName: string;
}

export const TABS: readonly TabDefinition[] = [
  {
    id: "overview",
    label: "Overview",
    icon: "mdi:view-dashboard-outline",
    tagName: "device-links-overview",
  },
  { id: "rules", label: "Rules", icon: "mdi:link-variant", tagName: "device-links-rules" },
  { id: "devices", label: "Devices", icon: "mdi:z-wave", tagName: "device-links-devices" },
  {
    id: "profiles",
    label: "Profiles",
    icon: "mdi:file-multiple-outline",
    tagName: "device-links-profiles",
  },
  { id: "activity", label: "Activity", icon: "mdi:history", tagName: "device-links-activity" },
];

/** The tab shown when the URL names none, or names one that does not exist. */
export const DEFAULT_TAB = TABS[0]?.id ?? "overview";

/**
 * Return the tab a panel route selects.
 *
 * Anything unrecognised falls back to the first tab rather than to an empty screen: a
 * bookmark from a later version naming a tab this build does not have should land
 * somewhere useful.
 */
export function tabFromPath(path: string | undefined | null): string {
  const first = (path ?? "").split("/").filter(Boolean)[0];
  return TABS.some((tab) => tab.id === first) ? (first as string) : DEFAULT_TAB;
}
