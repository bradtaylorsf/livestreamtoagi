import { describe, expect, it } from "vitest";

// Test the navigation structure directly (same pattern as AgentGrid.test.ts)

interface NavChild {
  href: string;
  label: string;
}

interface NavItem {
  label: string;
  href?: string;
  children?: NavChild[];
}

// Mirror the NAV_ITEMS from Navigation.tsx to verify structure
const NAV_ITEMS: NavItem[] = [
  { label: "Home", href: "/" },
  { label: "Agents", href: "/agents" },
  {
    label: "Watch",
    children: [
      { href: "/world", label: "World" },
      { href: "/conversations", label: "Conversations" },
      { href: "/lore", label: "Lore" },
    ],
  },
  { label: "Challenges", href: "/challenges" },
  { label: "Evals", href: "/evals" },
  { label: "Blog", href: "/blog" },
  {
    label: "About",
    children: [
      { href: "/about", label: "About" },
      { href: "/safety", label: "Safety" },
      { href: "/ethics", label: "Ethics" },
    ],
  },
];

describe("Navigation structure", () => {
  it("has at most 7 top-level items", () => {
    expect(NAV_ITEMS.length).toBeLessThanOrEqual(7);
  });

  it("every item has a label", () => {
    for (const item of NAV_ITEMS) {
      expect(item.label).toBeTruthy();
    }
  });

  it("leaf items have an href", () => {
    for (const item of NAV_ITEMS) {
      if (!item.children) {
        expect(item.href).toBeTruthy();
      }
    }
  });

  it("dropdown items have children with href and label", () => {
    const dropdowns = NAV_ITEMS.filter((item) => item.children);
    expect(dropdowns.length).toBeGreaterThanOrEqual(1);
    for (const dropdown of dropdowns) {
      expect(dropdown.children!.length).toBeGreaterThanOrEqual(1);
      for (const child of dropdown.children!) {
        expect(child.href).toBeTruthy();
        expect(child.label).toBeTruthy();
      }
    }
  });

  it("all original pages are still reachable", () => {
    const allHrefs = new Set<string>();
    for (const item of NAV_ITEMS) {
      if (item.href) allHrefs.add(item.href);
      if (item.children) {
        for (const child of item.children) {
          allHrefs.add(child.href);
        }
      }
    }

    const expectedPaths = [
      "/",
      "/agents",
      "/world",
      "/challenges",
      "/lore",
      "/conversations",
      "/about",
      "/safety",
      "/ethics",
      "/blog",
      "/evals",
    ];

    for (const path of expectedPaths) {
      expect(allHrefs).toContain(path);
    }
  });

  it("groups Watch and About as dropdown menus", () => {
    const watch = NAV_ITEMS.find((item) => item.label === "Watch");
    const about = NAV_ITEMS.find((item) => item.label === "About");

    expect(watch).toBeDefined();
    expect(watch!.children).toBeDefined();
    expect(about).toBeDefined();
    expect(about!.children).toBeDefined();
  });
});
