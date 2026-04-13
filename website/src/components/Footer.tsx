import Link from "next/link";

const LINKS = [
  { href: "/about", label: "About" },
  { href: "/ethics", label: "Ethics" },
  { href: "/blog", label: "Blog" },
  { href: "/agents", label: "Agents" },
  { href: "/world", label: "World" },
  { href: "/contribute", label: "Contribute" },
  { href: "/donate", label: "Donate" },
  { href: "https://github.com/bradtaylor/livestreamtoagi", label: "GitHub", external: true },
];

export default function Footer() {
  return (
    <footer className="border-t border-border bg-surface px-4 py-8 mt-16">
      <div className="mx-auto max-w-6xl flex flex-col sm:flex-row items-center justify-between gap-4">
        <div className="font-pixel text-xs text-foreground/40">
          LIVESTREAM → AGI
        </div>
        <nav className="flex flex-wrap gap-4 justify-center">
          {LINKS.map(({ href, label, ...rest }) =>
            "external" in rest ? (
              <a
                key={href}
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-foreground/50 hover:text-foreground transition-colors"
              >
                {label}
              </a>
            ) : (
              <Link
                key={href}
                href={href}
                className="text-sm text-foreground/50 hover:text-foreground transition-colors"
              >
                {label}
              </Link>
            ),
          )}
        </nav>
        <div className="text-xs text-foreground/30">
          Built by AI agents (with human supervision)
        </div>
      </div>
    </footer>
  );
}
