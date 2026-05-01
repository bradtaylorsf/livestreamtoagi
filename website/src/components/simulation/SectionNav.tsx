import Link from "next/link";

interface SectionLink {
  href: string;
  label: string;
}

interface SectionNavProps {
  links: SectionLink[];
}

export default function SectionNav({ links }: SectionNavProps) {
  return (
    <div className="flex items-center gap-3 flex-wrap">
      {links.map((link) => (
        <Link
          key={link.href}
          href={link.href}
          className="inline-flex items-center gap-2 rounded border border-neon-cyan px-3 py-1.5 text-xs text-neon-cyan hover:bg-neon-cyan/10 transition-colors"
        >
          {link.label}
        </Link>
      ))}
    </div>
  );
}
