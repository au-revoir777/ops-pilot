import { ShieldAlert } from "lucide-react";
import { redact } from "@/lib/redact";
import { cn } from "@/lib/utils";

// Retrieved documents, logs and model output are untrusted (UI prompt section 10).
// They are only ever rendered as React text nodes: no HTML parsing, no Markdown
// rendering, no auto-linking. React escapes everything, so "<script>" is just
// characters on screen. Credential-looking values are redacted first.

export function UntrustedText({ text, className }: { text: string; className?: string }) {
  return <span className={cn("whitespace-pre-wrap break-words", className)}>{redact(text)}</span>;
}

/** A visibly quoted, source-attributed container for retrieved text. */
export function QuotedExcerpt({
  text,
  source,
  flags = [],
  className,
}: {
  text: string;
  source: string;
  flags?: string[];
  className?: string;
}) {
  const suspicious = flags.length > 0;
  return (
    <figure className={cn("space-y-1", className)}>
      {suspicious ? (
        <p className="flex items-center gap-1 text-xs font-medium text-status-down-text">
          <ShieldAlert className="size-3.5" aria-hidden />
          Possible prompt injection ({flags.join(", ")}). Shown as inert text; it cannot trigger anything.
        </p>
      ) : null}
      <blockquote
        className={cn(
          "border-l-2 bg-muted/50 py-1.5 pr-2 pl-3 text-xs leading-relaxed text-foreground",
          suspicious ? "border-status-down" : "border-kind-retrieved",
        )}
      >
        <UntrustedText text={text} />
      </blockquote>
      <figcaption className="font-mono text-[11px] text-muted-foreground">{source}</figcaption>
    </figure>
  );
}
