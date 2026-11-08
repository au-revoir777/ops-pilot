"use client";

import Link from "next/link";
import { Suspense } from "react";
import { InvestigationForm } from "@/components/domain/investigation-form";
import { RecentInvestigations } from "@/components/domain/investigation-table";
import { EmptyState, ErrorState, LoadingRows } from "@/components/domain/states";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useInvestigations } from "@/hooks/use-api";

function Recent() {
  const list = useInvestigations({ limit: 10 }, { refetchInterval: 15_000 });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent investigations</CardTitle>
        <Button asChild variant="ghost" size="sm">
          <Link href="/history">All history</Link>
        </Button>
      </CardHeader>
      <CardContent>
        {list.isPending ? (
          <LoadingRows rows={4} label="Loading investigations" />
        ) : list.isError ? (
          <ErrorState error={list.error} onRetry={() => void list.refetch()} />
        ) : list.data.items.length === 0 ? (
          <EmptyState title="No investigations yet">Ask a question above to run the first one.</EmptyState>
        ) : (
          <RecentInvestigations items={list.data.items} />
        )}
      </CardContent>
    </Card>
  );
}

export default function InvestigationsPage() {
  return (
    <>
      <PageHeader
        title="Investigations"
        description="Ask a question about a service. Every step, fact and source behind the answer is shown."
      />
      <div className="space-y-4">
        <Suspense fallback={<LoadingRows rows={3} />}>
          <InvestigationForm />
        </Suspense>
        <Recent />
      </div>
    </>
  );
}
