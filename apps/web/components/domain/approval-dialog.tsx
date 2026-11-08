"use client";

import { ClipboardCheck, Hand } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import type { RecommendationView } from "@/lib/epistemic";
import { CopyButton } from "./copy-button";
import { UntrustedText } from "./untrusted-text";

// The API has no remediation endpoint (OpsPilot is read-only, spec section 17),
// so the approval flow ends in copyable instructions and an explicit statement
// that execution is manual (UI prompt section 10).

export function ApprovalDialog({ recommendation, service }: { recommendation: RecommendationView; service: string | null }) {
  const [open, setOpen] = useState(false);
  const instructions = [
    `Action: ${recommendation.action}`,
    `Target: ${service ?? "unknown service"}`,
    `Why: ${recommendation.rationale}`,
    recommendation.references.length ? `References: ${recommendation.references.join(", ")}` : null,
    "Proposed by OpsPilot. Review before acting; OpsPilot does not execute changes.",
  ]
    .filter(Boolean)
    .join("\n");

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <ClipboardCheck /> Review action
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogTitle>Review recommended action</DialogTitle>
        <DialogDescription>
          This is a proposal. OpsPilot runs in read-only mode and has no way to execute it.
        </DialogDescription>
        <dl className="grid grid-cols-[6rem_1fr] gap-x-3 gap-y-2 text-sm">
          <dt className="text-muted-foreground">Action</dt>
          <dd>
            <UntrustedText text={recommendation.action} />
          </dd>
          <dt className="text-muted-foreground">Target</dt>
          <dd className="font-mono">{service ?? "unknown"}</dd>
          <dt className="text-muted-foreground">Why</dt>
          <dd>
            <UntrustedText text={recommendation.rationale} />
          </dd>
          <dt className="text-muted-foreground">Rollback</dt>
          <dd>Decided by the operator who executes it. Follow the referenced procedure.</dd>
        </dl>
        <div className="flex items-start gap-2 rounded-md border bg-muted/50 p-2.5 text-xs">
          <Hand className="mt-0.5 size-4 shrink-0" aria-hidden />
          <p>
            <span className="font-medium">Execution is manual.</span> Copy the instructions and carry them out through
            your normal change process.
          </p>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Close
          </Button>
          <CopyButton value={instructions} label="Copy instructions" className="border">
            Copy instructions
          </CopyButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
