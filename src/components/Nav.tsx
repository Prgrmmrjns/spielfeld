import Link from "next/link";

const links = [
  { href: "/", label: "Matchday" },
  { href: "/players", label: "Player impact" },
  { href: "/model", label: "Model" },
  { href: "/track-record", label: "Track record" },
];

export function Nav() {
  return (
    <header className="relative z-20 border-b border-white/10">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-6 px-5 py-4">
        <Link href="/" className="display text-2xl tracking-wide text-ink">
          SPIELFELD
        </Link>
        <nav className="flex flex-wrap items-center gap-4 text-sm text-muted">
          {links.map((l) => (
            <Link key={l.href} href={l.href} className="transition hover:text-ink">
              {l.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
