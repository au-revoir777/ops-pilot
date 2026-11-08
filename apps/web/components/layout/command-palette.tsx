"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Command } from "cmdk";
import { CircleHelp, Copy, FlaskConical, Moon, Palette, Play } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useCopy } from "@/hooks/use-copy";
import { usePalette } from "@/hooks/use-palette";
import { getLastRequestId } from "@/lib/api/client";
import { PALETTES } from "@/lib/themes";
import { NAV } from "./nav";

const itemClass =
  "flex cursor-default items-center gap-2 rounded-sm px-2 py-1.5 text-sm data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground [&_svg]:size-4 [&_svg]:text-muted-foreground";
const groupClass =
  "[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground";

/**
 * Every typed word must start a word of the command. cmdk's default fuzzy match
 * ranked "copy correlation id" first for "ocean", so Enter ran the wrong action.
 */
export function matchWords(value: string, search: string): number {
  const words = value.toLowerCase().split(/\s+/);
  const terms = search.toLowerCase().trim().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return 1;
  return terms.every((t) => words.some((w) => w.startsWith(t))) ? 1 : 0;
}

export function CommandPalette({
  open,
  onOpenChange,
  onOpenHelp,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onOpenHelp: () => void;
}) {
  const router = useRouter();
  const { resolvedTheme, setTheme } = useTheme();
  const [, setPalette] = usePalette();
  const copy = useCopy();

  const run = (fn: () => void) => () => {
    onOpenChange(false);
    fn();
  };

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/50" />
        <DialogPrimitive.Content
          className="fixed top-[15vh] left-1/2 z-50 w-[calc(100%-2rem)] max-w-xl -translate-x-1/2 overflow-hidden rounded-lg border bg-popover text-popover-foreground shadow-lg"
          aria-describedby={undefined}
        >
          <DialogPrimitive.Title className="sr-only">Command palette</DialogPrimitive.Title>
          <Command label="Command palette" loop filter={matchWords}>
            <Command.Input
              placeholder="Type a command or page…"
              className="h-11 w-full border-b bg-transparent px-3 text-sm outline-none placeholder:text-muted-foreground"
            />
            <Command.List className="max-h-80 overflow-y-auto p-1">
              <Command.Empty className="px-3 py-6 text-center text-sm text-muted-foreground">No matching command.</Command.Empty>
              <Command.Group heading="Go to" className={groupClass}>
                {NAV.map((n) => (
                  <Command.Item key={n.href} value={`go ${n.label}`} onSelect={run(() => router.push(n.href))} className={itemClass}>
                    <n.icon /> {n.label}
                    <kbd className="ml-auto font-mono text-[10px] text-muted-foreground">{n.shortcut}</kbd>
                  </Command.Item>
                ))}
              </Command.Group>
              <Command.Group heading="Actions" className={groupClass}>
                <Command.Item value="start investigation" onSelect={run(() => router.push("/investigations?new=1"))} className={itemClass}>
                  <Play /> Start investigation
                </Command.Item>
                <Command.Item value="inject incident lab" onSelect={run(() => router.push("/incident-lab"))} className={itemClass}>
                  <FlaskConical /> Inject incident (opens the Incident Lab)
                </Command.Item>
                <Command.Item
                  value="copy correlation id"
                  onSelect={run(() => {
                    const id = getLastRequestId();
                    if (id) void copy(id, "Correlation ID copied");
                  })}
                  className={itemClass}
                >
                  <Copy /> Copy last correlation ID
                </Command.Item>
                <Command.Item
                  value="toggle dark mode"
                  onSelect={run(() => setTheme(resolvedTheme === "dark" ? "light" : "dark"))}
                  className={itemClass}
                >
                  <Moon /> Toggle dark mode
                </Command.Item>
                <Command.Item value="help keyboard shortcuts" onSelect={run(onOpenHelp)} className={itemClass}>
                  <CircleHelp /> Keyboard shortcuts
                </Command.Item>
              </Command.Group>
              <Command.Group heading="Palette" className={groupClass}>
                {PALETTES.map((p) => (
                  <Command.Item key={p.id} value={`palette ${p.label}`} onSelect={run(() => setPalette(p.id))} className={itemClass}>
                    <Palette /> Switch to {p.label}
                  </Command.Item>
                ))}
              </Command.Group>
            </Command.List>
          </Command>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
