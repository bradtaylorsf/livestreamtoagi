"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/", label: "Home" },
  { href: "/agents", label: "Agents" },
  { href: "/world", label: "World" },
  { href: "/challenges", label: "Challenges" },
  { href: "/lore", label: "Lore" },
  { href: "/conversations", label: "Conversations" },
] as const;

export default function Navigation() {
  const pathname = usePathname();

  return (
    <nav className="border-b border-border bg-surface px-4 py-3">
      <div className="mx-auto flex max-w-6xl items-center justify-between">
        <Link
          href="/"
          className="font-pixel text-sm text-neon-cyan hover:text-neon-magenta transition-colors"
        >
          LIVESTREAM→AGI
        </Link>
        <ul className="flex gap-1">
          {NAV_ITEMS.map(({ href, label }) => {
            const isActive =
              href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <li key={href}>
                <Link
                  href={href}
                  className={`rounded px-3 py-2 text-sm transition-colors ${
                    isActive
                      ? "bg-surface-light text-neon-cyan"
                      : "text-foreground/70 hover:bg-surface-light hover:text-foreground"
                  }`}
                >
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>
      </div>
    </nav>
  );
}
