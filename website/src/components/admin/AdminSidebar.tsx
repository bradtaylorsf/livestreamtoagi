"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/admin", label: "Dashboard", icon: "◆" },
  { href: "/admin/simulations", label: "Simulations", icon: "▶" },
] as const;

export default function AdminSidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-56 shrink-0 border-r border-border bg-surface min-h-screen p-4">
      <Link
        href="/admin"
        className="block font-pixel text-xs text-neon-cyan mb-8"
      >
        ADMIN
      </Link>
      <nav className="flex flex-col gap-1">
        {NAV_ITEMS.map(({ href, label, icon }) => {
          const isActive =
            href === "/admin"
              ? pathname === "/admin"
              : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-2 rounded px-3 py-2 text-sm transition-colors ${
                isActive
                  ? "bg-surface-light text-neon-cyan"
                  : "text-foreground/70 hover:bg-surface-light hover:text-foreground"
              }`}
            >
              <span className="text-xs">{icon}</span>
              {label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
