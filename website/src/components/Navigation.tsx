"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useEffect, useRef, useCallback } from "react";

interface NavChild {
  href: string;
  label: string;
}

interface NavItem {
  label: string;
  href?: string;
  children?: NavChild[];
}

const NAV_ITEMS: NavItem[] = [
  { label: "Home", href: "/" },
  { label: "Agents", href: "/agents" },
  {
    label: "Explore",
    children: [
      { href: "/world", label: "World" },
      { href: "/conversations", label: "Conversations" },
      { href: "/lore", label: "Lore" },
    ],
  },
  { label: "Challenges", href: "/challenges" },
  { label: "Simulations", href: "/simulations" },
  { label: "Evals", href: "/evals" },
  { label: "Blog", href: "/blog" },
  {
    label: "About",
    children: [
      { href: "/about", label: "About" },
      { href: "/safety", label: "Safety" },
      { href: "/ethics", label: "Ethics" },
      { href: "/contribute", label: "Contribute" },
      { href: "/donate", label: "Donate" },
    ],
  },
];

function isChildActive(children: NavChild[], pathname: string): boolean {
  return children.some((child) => pathname.startsWith(child.href));
}

function DropdownMenu({
  item,
  pathname,
}: {
  item: NavItem;
  pathname: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLLIElement>(null);
  const menuRef = useRef<HTMLUListElement>(null);

  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        close();
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open, close]);

  const parentActive = item.children
    ? isChildActive(item.children, pathname)
    : false;

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      close();
      return;
    }
    if (e.key === "ArrowDown" && open && menuRef.current) {
      e.preventDefault();
      const first = menuRef.current.querySelector<HTMLAnchorElement>(
        '[role="menuitem"]',
      );
      first?.focus();
    }
  }

  function handleMenuKeyDown(e: React.KeyboardEvent) {
    const items = menuRef.current?.querySelectorAll<HTMLAnchorElement>(
      '[role="menuitem"]',
    );
    if (!items) return;
    const idx = Array.from(items).indexOf(e.target as HTMLAnchorElement);

    if (e.key === "ArrowDown") {
      e.preventDefault();
      items[(idx + 1) % items.length]?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      items[(idx - 1 + items.length) % items.length]?.focus();
    } else if (e.key === "Escape") {
      close();
    }
  }

  return (
    <li ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        onKeyDown={handleKeyDown}
        aria-haspopup="true"
        aria-expanded={open}
        className={`rounded px-3 py-2 text-sm transition-colors flex items-center gap-1 ${
          parentActive
            ? "bg-surface-light text-neon-cyan"
            : "text-foreground/70 hover:bg-surface-light hover:text-foreground"
        }`}
      >
        {item.label}
        <svg
          className={`w-3 h-3 transition-transform ${open ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M19 9l-7 7-7-7"
          />
        </svg>
      </button>
      {open && (
        <ul
          ref={menuRef}
          role="menu"
          onKeyDown={handleMenuKeyDown}
          className="absolute left-1/2 -translate-x-1/2 top-full mt-1 w-44 rounded border border-border bg-surface shadow-lg py-1 z-50"
        >
          {item.children!.map((child) => {
            const active = pathname.startsWith(child.href);
            return (
              <li key={child.href} role="none">
                <Link
                  href={child.href}
                  role="menuitem"
                  tabIndex={-1}
                  onClick={close}
                  className={`block px-4 py-2 text-sm transition-colors ${
                    active
                      ? "text-neon-cyan bg-surface-light"
                      : "text-foreground/70 hover:bg-surface-light hover:text-foreground"
                  }`}
                >
                  {child.label}
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </li>
  );
}

export default function Navigation() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [mobileExpanded, setMobileExpanded] = useState<string | null>(null);

  // Close mobile menu on route change
  useEffect(() => {
    setMobileOpen(false);
    setMobileExpanded(null);
  }, [pathname]);

  return (
    <nav className="border-b border-border bg-surface px-4 py-3">
      <div className="mx-auto flex max-w-6xl items-center justify-between">
        <Link
          href="/"
          className="font-pixel text-sm text-neon-cyan hover:text-neon-magenta transition-colors"
        >
          LIVESTREAM→AGI
        </Link>

        {/* Desktop nav */}
        <ul className="hidden md:flex gap-1">
          {NAV_ITEMS.map((item) => {
            if (item.children) {
              return (
                <DropdownMenu
                  key={item.label}
                  item={item}
                  pathname={pathname}
                />
              );
            }
            const isActive =
              item.href === "/"
                ? pathname === "/"
                : pathname.startsWith(item.href!);
            return (
              <li key={item.href}>
                <Link
                  href={item.href!}
                  className={`rounded px-3 py-2 text-sm transition-colors ${
                    isActive
                      ? "bg-surface-light text-neon-cyan"
                      : "text-foreground/70 hover:bg-surface-light hover:text-foreground"
                  }`}
                >
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>

        {/* Mobile hamburger button */}
        <button
          className="md:hidden rounded p-2 text-foreground/70 hover:bg-surface-light hover:text-foreground transition-colors"
          onClick={() => setMobileOpen((v) => !v)}
          aria-label="Toggle menu"
          aria-expanded={mobileOpen}
        >
          <svg
            className="w-5 h-5"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
            aria-hidden="true"
          >
            {mobileOpen ? (
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M6 18L18 6M6 6l12 12"
              />
            ) : (
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M4 6h16M4 12h16M4 18h16"
              />
            )}
          </svg>
        </button>
      </div>

      {/* Mobile menu */}
      {mobileOpen && (
        <div className="md:hidden mt-3 border-t border-border pt-3">
          <ul className="space-y-1">
            {NAV_ITEMS.map((item) => {
              if (item.children) {
                const parentActive = isChildActive(item.children, pathname);
                const expanded = mobileExpanded === item.label;
                return (
                  <li key={item.label}>
                    <button
                      onClick={() =>
                        setMobileExpanded(expanded ? null : item.label)
                      }
                      aria-expanded={expanded}
                      className={`w-full flex items-center justify-between rounded px-3 py-2 text-sm transition-colors ${
                        parentActive
                          ? "bg-surface-light text-neon-cyan"
                          : "text-foreground/70 hover:bg-surface-light hover:text-foreground"
                      }`}
                    >
                      {item.label}
                      <svg
                        className={`w-3 h-3 transition-transform ${expanded ? "rotate-180" : ""}`}
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        strokeWidth={2}
                        aria-hidden="true"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M19 9l-7 7-7-7"
                        />
                      </svg>
                    </button>
                    {expanded && (
                      <ul className="ml-4 mt-1 space-y-1">
                        {item.children.map((child) => {
                          const active = pathname.startsWith(child.href);
                          return (
                            <li key={child.href}>
                              <Link
                                href={child.href}
                                className={`block rounded px-3 py-2 text-sm transition-colors ${
                                  active
                                    ? "text-neon-cyan bg-surface-light"
                                    : "text-foreground/70 hover:bg-surface-light hover:text-foreground"
                                }`}
                              >
                                {child.label}
                              </Link>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </li>
                );
              }
              const isActive =
                item.href === "/"
                  ? pathname === "/"
                  : pathname.startsWith(item.href!);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href!}
                    className={`block rounded px-3 py-2 text-sm transition-colors ${
                      isActive
                        ? "bg-surface-light text-neon-cyan"
                        : "text-foreground/70 hover:bg-surface-light hover:text-foreground"
                    }`}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </nav>
  );
}
