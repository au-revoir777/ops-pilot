"use client";

import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { isActive, NAV } from "./nav";

function Logo({ collapsed }: { collapsed: boolean }) {
  return (
    <Link href="/" className="flex items-center gap-2 rounded-md px-1 py-1" aria-label="OpsPilot home">
      <svg viewBox="0 0 24 24" className="size-6 shrink-0 text-primary" aria-hidden>
        <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" strokeWidth="2" />
        <path d="M5 13h3l2-5 3 9 2-6 1.5 2H19" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {collapsed ? null : <span className="text-[15px] font-semibold tracking-tight">OpsPilot</span>}
    </Link>
  );
}

export function Sidebar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Main"
      className={cn(
        "hidden shrink-0 flex-col border-r bg-sidebar transition-[width] duration-150 md:flex",
        collapsed ? "w-14" : "w-52",
      )}
    >
      <div className={cn("flex h-12 items-center border-b px-3", collapsed && "justify-center px-0")}>
        <Logo collapsed={collapsed} />
      </div>
      <ul className="flex-1 space-y-0.5 p-2">
        {NAV.map((item) => {
          const active = isActive(pathname, item.href);
          const link = (
            <Link
              href={item.href}
              aria-current={active ? "page" : undefined}
              aria-label={collapsed ? item.label : undefined}
              className={cn(
                "flex h-8 items-center gap-2.5 rounded-md px-2 text-sm",
                active ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                collapsed && "justify-center px-0",
              )}
            >
              <item.icon className="size-4 shrink-0" aria-hidden />
              {collapsed ? null : item.label}
            </Link>
          );
          return (
            <li key={item.href}>
              {collapsed ? (
                <Tooltip content={item.label} side="right">
                  {link}
                </Tooltip>
              ) : (
                link
              )}
            </li>
          );
        })}
      </ul>
      <div className="border-t p-2">
        <button
          type="button"
          onClick={onToggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className={cn(
            "flex h-8 w-full items-center gap-2.5 rounded-md px-2 text-sm text-muted-foreground hover:bg-accent/60 hover:text-foreground",
            collapsed && "justify-center px-0",
          )}
        >
          {collapsed ? <PanelLeftOpen className="size-4" aria-hidden /> : <PanelLeftClose className="size-4" aria-hidden />}
          {collapsed ? null : "Collapse"}
        </button>
      </div>
    </nav>
  );
}
