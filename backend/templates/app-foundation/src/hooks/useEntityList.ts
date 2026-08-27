"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

interface UseEntityListOptions {
  entity: string;           // e.g., "expenses"
  defaultFilters?: Record<string, string>;
  defaultSort?: string;
  defaultLimit?: number;
}

interface QueryResult<T = Record<string, any>> {
  data: T[];
  total: number;
  page: number;
  limit: number;
}

export function useEntityList<T = Record<string, any>>(options: UseEntityListOptions) {
  const { entity, defaultFilters = {}, defaultSort, defaultLimit = 50 } = options;
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<Record<string, string>>(defaultFilters);
  const [page, setPage] = useState(1);

  const queryParams = new URLSearchParams();
  if (search) queryParams.set("search", search);
  queryParams.set("page", String(page));
  queryParams.set("limit", String(defaultLimit));
  if (defaultSort) queryParams.set("sort", defaultSort);
  Object.entries(filters).forEach(([key, value]) => {
    if (value && value !== "all") queryParams.set(key, value);
  });

  const { data, isLoading, error, refetch } = useQuery<QueryResult<T>>({
    queryKey: [entity, search, filters, page],
    queryFn: async () => {
      const res = await fetch(`/api/data/${entity}?${queryParams}`);
      if (!res.ok) throw new Error("Failed to fetch");
      return res.json();
    },
  });

  const { data: stats } = useQuery<{ total: number }>({
    queryKey: [`${entity}-stats`],
    queryFn: async () => {
      const res = await fetch(`/api/data/${entity}/stats`);
      if (!res.ok) return { total: 0 };
      return res.json();
    },
  });

  return {
    items: data?.data || [],
    total: data?.total || stats?.total || 0,
    page,
    setPage,
    search,
    setSearch,
    filters,
    setFilter: (key: string, value: string) => setFilters((f) => ({ ...f, [key]: value })),
    isLoading,
    error,
    refetch,
  };
}
