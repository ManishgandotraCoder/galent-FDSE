"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { IntakeStatusButton } from "@/components/intake/intake-status";

const LINKS = [
  { href: "/", label: "Workbench" },
  { href: "/eval", label: "Evaluation" },
  { href: "/readout", label: "Client readout" },
];

export function SiteNav() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-card">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8">
        <Link href="/" className="flex min-w-0 items-center gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent text-sm font-semibold text-white">
            D
          </span>
          <span className="min-w-0">
            <p className="truncate font-serif text-xl leading-none text-ink">DocProcessor</p>
            <p className="mt-1 text-[10px] font-medium tracking-[0.16em] text-muted uppercase">Accounts payable</p>
          </span>
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <IntakeStatusButton />
          <nav className="flex flex-wrap gap-1 text-sm">
            {LINKS.map((link) => {
              const active = pathname === link.href;
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  aria-current={active ? "page" : undefined}
                  className={`rounded-full px-3 py-1.5 transition-colors ${
                    active ? "bg-accent text-white" : "text-muted hover:bg-paper hover:text-ink"
                  }`}
                >
                  {link.label}
                </Link>
              );
            })}
          </nav>
        </div>
      </div>
    </header>
  );
}
