"use client";

import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

interface UseEntityDetailOptions {
  entity: string;  // e.g., "expenses"
  redirectOnDelete?: string;  // e.g., "/expenses"
}

export function useEntityDetail<T = Record<string, any>>(options: UseEntityDetailOptions) {
  const { entity, redirectOnDelete } = options;
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();

  const { data: item, isLoading, error, refetch } = useQuery<T>({
    queryKey: [entity, id],
    queryFn: async () => {
      const res = await fetch(`/api/data/${entity}/${id}`);
      if (!res.ok) throw new Error("Not found");
      return res.json();
    },
    enabled: !!id,
  });

  const updateMutation = useMutation({
    mutationFn: async (data: Partial<T>) => {
      const res = await fetch(`/api/data/${entity}/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err?.error?.message || "Failed to update");
      }
      return res.json();
    },
    onSuccess: () => {
      toast.success("Updated successfully");
      queryClient.invalidateQueries({ queryKey: [entity, id] });
    },
    onError: (err: Error) => {
      toast.error(err.message);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`/api/data/${entity}/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed to delete");
    },
    onSuccess: () => {
      toast.success("Deleted");
      queryClient.invalidateQueries({ queryKey: [entity] });
      router.push(redirectOnDelete || `/${entity}`);
    },
    onError: (err: Error) => {
      toast.error(err.message);
    },
  });

  const handleDelete = () => {
    if (window.confirm("Are you sure you want to delete this? This action cannot be undone.")) {
      deleteMutation.mutate();
    }
  };

  return {
    id,
    item,
    isLoading,
    error,
    refetch,
    update: updateMutation.mutate,
    isUpdating: updateMutation.isPending,
    handleDelete,
    isDeleting: deleteMutation.isPending,
  };
}
