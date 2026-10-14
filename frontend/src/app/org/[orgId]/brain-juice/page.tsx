"use client";

// Brain Juice became the Drafts Room (2026-10-14). The old address still
// opens the room.
import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

export default function BrainJuiceRedirect() {
  const params = useParams<{ orgId: string }>();
  const router = useRouter();
  useEffect(() => {
    router.replace(`/org/${params.orgId}/drafts-room`);
  }, [params.orgId, router]);
  return null;
}
