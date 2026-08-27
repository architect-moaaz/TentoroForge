"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

interface UseEntityFormOptions {
  entity: string;          // e.g., "expenses"
  redirectOnSuccess?: string; // e.g., "/expenses"
  mode?: "create" | "edit";
  entityId?: string;       // for edit mode
  initialValues?: Record<string, any>;
}

export function useEntityForm<T extends Record<string, any> = Record<string, any>>(
  options: UseEntityFormOptions
) {
  const { entity, redirectOnSuccess, mode = "create", entityId, initialValues = {} } = options;
  const [form, setForm] = useState<T>(initialValues as T);
  const router = useRouter();
  const queryClient = useQueryClient();

  const setField = (field: string, value: any) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const mutation = useMutation({
    mutationFn: async (data: T) => {
      const url = mode === "edit"
        ? `/api/data/${entity}/${entityId}`
        : `/api/data/${entity}`;
      const method = mode === "edit" ? "PUT" : "POST";

      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err?.error?.message || `Failed to ${mode}`);
      }
      return res.json();
    },
    onSuccess: (data) => {
      const action = mode === "edit" ? "Updated" : "Created";
      toast.success(`${action} successfully!`);
      queryClient.invalidateQueries({ queryKey: [entity] });
      if (redirectOnSuccess) {
        router.push(redirectOnSuccess);
      } else if (data?.id) {
        router.push(`/${entity}/${data.id}`);
      } else {
        router.push(`/${entity}`);
      }
    },
    onError: (err: Error) => {
      toast.error(err.message || "Something went wrong");
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    mutation.mutate(form);
  };

  return {
    form,
    setForm,
    setField,
    handleSubmit,
    isSubmitting: mutation.isPending,
    error: mutation.error?.message,
  };
}
