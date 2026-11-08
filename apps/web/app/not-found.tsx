import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-md space-y-3 py-16 text-center">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <p className="text-sm text-muted-foreground">Nothing exists at this address. Check the link, or start from the dashboard.</p>
      <Button asChild>
        <Link href="/">Go to the dashboard</Link>
      </Button>
    </div>
  );
}
