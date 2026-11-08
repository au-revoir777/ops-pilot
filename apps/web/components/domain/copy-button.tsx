"use client";

import { Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useCopy } from "@/hooks/use-copy";
import { cn } from "@/lib/utils";

export function CopyButton({
  value,
  label,
  className,
  children,
}: {
  value: string;
  label: string;
  className?: string;
  children?: React.ReactNode;
}) {
  const copy = useCopy();
  return (
    <Button
      type="button"
      variant="ghost"
      size={children ? "sm" : "icon"}
      className={cn(!children && "size-6", className)}
      aria-label={children ? undefined : label}
      title={label}
      onClick={() => void copy(value, `${label.replace(/^Copy /, "")} copied`)}
    >
      <Copy className="size-3.5" />
      {children}
    </Button>
  );
}
