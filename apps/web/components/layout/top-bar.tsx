"use client";

import { CircleHelp, Command, Lock, Menu, Monitor, Moon, Palette, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { StatusDot } from "@/components/domain/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip } from "@/components/ui/tooltip";
import { useConfig, useDependencyHealth, useServices } from "@/hooks/use-api";
import { usePalette } from "@/hooks/use-palette";
import { PALETTES, type PaletteId } from "@/lib/themes";
import { isActive, NAV } from "./nav";

export function EnvironmentBadge() {
  const { data, isError } = useConfig();
  if (isError) return <Badge variant="unknown">ENV UNKNOWN</Badge>;
  if (!data) return <Badge variant="outline" className="w-14 animate-pulse">&nbsp;</Badge>;
  const env = data.environment.toLowerCase();
  const local = ["local", "development", "dev", "test"].includes(env);
  return (
    <Badge variant="outline" className="font-mono uppercase" title={`APP_ENV=${data.environment}`}>
      {local ? "LOCAL" : env === "production" || env === "cloud" ? "CLOUD" : env}
    </Badge>
  );
}

/** One dot for everything: the worst of the platform's dependencies and the services' health. */
function HealthSummary() {
  const health = useDependencyHealth();
  const services = useServices();
  const healths = (services.data?.services ?? []).map((s) => s.health ?? "unknown");
  const down = healths.filter((h) => h === "down").length;
  const degraded = healths.filter((h) => h === "degraded").length;
  let status = "unknown";
  let text = "Checking health…";
  if (health.isError || services.isError) {
    status = "down";
    text = "The OpsPilot API is unreachable";
  } else if (health.data && services.data) {
    const platform = health.data.status;
    status = platform === "down" || down ? "down" : platform === "degraded" || degraded ? "degraded" : "healthy";
    text = `Platform ${platform}; ${healths.length} services: ${down} down, ${degraded} degraded`;
  }
  return (
    <Tooltip content={text}>
      <Link href="/system" className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs hover:bg-accent">
        <StatusDot status={status} />
        {/* The accessible name starts with the visible word (WCAG 2.5.3). */}
        <span className="sr-only lg:not-sr-only lg:capitalize">{status === "unknown" ? "Health" : status}</span>
        <span className="sr-only">: {text}</span>
      </Link>
    </Tooltip>
  );
}

export function ReadOnlyIndicator() {
  const { data } = useConfig();
  if (data && !data.read_only) return null;
  return (
    <Tooltip
      content={
        <span className="block space-y-1">
          <span className="block font-medium">Read-only mode</span>
          <span className="block">
            The agent can read metrics, logs, deployments and the knowledge base. It cannot restart, roll back, scale
            or change anything. Recommendations are proposals you carry out yourself.
          </span>
        </span>
      }
    >
      <button type="button" className="inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 text-[11px] font-semibold tracking-wide">
        <Lock className="size-3" aria-hidden /> READ-ONLY
      </button>
    </Tooltip>
  );
}

export function AppearanceMenu() {
  const { theme, setTheme } = useTheme();
  const [palette, setPalette] = usePalette();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Appearance: palette and mode">
          <Palette />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuLabel>Palette</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={palette} onValueChange={(v) => setPalette(v as PaletteId)}>
          {PALETTES.map((p) => (
            <DropdownMenuRadioItem key={p.id} value={p.id}>
              <span className="flex flex-col">
                <span>{p.label}</span>
                <span className="text-xs text-muted-foreground">{p.description}</span>
              </span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuLabel>Mode</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={theme ?? "system"} onValueChange={setTheme}>
          <DropdownMenuRadioItem value="light">
            <Sun /> Light
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">
            <Moon /> Dark
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="system">
            <Monitor /> System
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function MobileNav() {
  const pathname = usePathname();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="md:hidden" aria-label="Navigation">
          <Menu />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        {NAV.map((n) => (
          <DropdownMenuItem key={n.href} asChild>
            <Link href={n.href} aria-current={isActive(pathname, n.href) ? "page" : undefined}>
              <n.icon /> {n.label}
            </Link>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function TopBar({ onOpenPalette, onOpenHelp }: { onOpenPalette: () => void; onOpenHelp: () => void }) {
  return (
    <header className="flex h-12 shrink-0 items-center gap-2 border-b bg-card px-3 lg:px-4">
      <MobileNav />
      <EnvironmentBadge />
      <ReadOnlyIndicator />
      <div className="flex-1" />
      <button
        type="button"
        onClick={onOpenPalette}
        className="hidden h-8 w-60 items-center gap-2 whitespace-nowrap rounded-md border bg-background px-2.5 text-sm text-muted-foreground hover:bg-accent lg:flex"
      >
        <Command className="size-3.5" aria-hidden />
        <span className="flex-1 text-left">Search or run a command</span>
        <kbd className="rounded-sm border bg-muted px-1 font-mono text-[10px]">Ctrl K</kbd>
      </button>
      <Button variant="ghost" size="icon" className="lg:hidden" onClick={onOpenPalette} aria-label="Command palette">
        <Command />
      </Button>
      <HealthSummary />
      <AppearanceMenu />
      <Button variant="ghost" size="icon" onClick={onOpenHelp} aria-label="Keyboard shortcuts and help">
        <CircleHelp />
      </Button>
    </header>
  );
}
