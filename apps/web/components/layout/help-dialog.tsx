"use client";

import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { NAV } from "./nav";

const SHORTCUTS: [string, string][] = [
  ["Ctrl K / ⌘ K", "Open the command palette"],
  ["?", "Show this help"],
  ...NAV.map((n): [string, string] => [n.shortcut, `Go to ${n.label}`]),
  ["Ctrl Enter", "Run the investigation (in the query box)"],
  ["Esc", "Close a dialog or menu"],
];

export function HelpDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>Keyboard shortcuts</DialogTitle>
        <DialogDescription>Shortcuts are ignored while you type in a field.</DialogDescription>
        <table className="w-full text-sm">
          <caption className="sr-only">Keyboard shortcuts</caption>
          <tbody>
            {SHORTCUTS.map(([keys, action]) => (
              <tr key={keys} className="border-b last:border-0">
                <td className="py-1.5 pr-4">
                  <kbd className="rounded-sm border bg-muted px-1.5 py-0.5 font-mono text-xs">{keys}</kbd>
                </td>
                <td className="py-1.5">{action}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="space-y-1 text-xs text-muted-foreground">
          <p>
            <span className="font-medium text-foreground">Reading an investigation.</span> Findings are split by kind:
            facts are measured, retrieved evidence is quoted from documents, hypotheses are candidates, and the
            diagnosis is the most likely cause, not a certainty.
          </p>
          <p>
            <span className="font-medium text-foreground">Confidence</span> is a documented heuristic over the evidence,
            not a probability. Open its breakdown to see each component.
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
