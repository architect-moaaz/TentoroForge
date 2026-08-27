"use client";

import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Loader2,
  Table2,
  ChevronLeft,
  ChevronRight,
  AlertCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import { nextSortState, dbRowsUrl, type SortState } from "@/lib/db-rows";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface DbTable {
  name: string;
  row_count: number;
  columns: {
    name: string;
    type: string;
    nullable: boolean;
    default: string | null;
  }[];
}

interface RowsResult {
  columns: string[];
  rows: Record<string, unknown>[];
  total: number;
  limit: number;
  offset: number;
}

interface DatabaseBrowserProps {
  projectId: string;
  dbPort?: number | null;
  /** When set, the browser is controlled to this table (e.g. from an ERD click). */
  table?: string | null;
}

const PAGE_SIZE = 50;

export function DatabaseBrowser({ projectId, dbPort, table }: DatabaseBrowserProps) {
  const [selectedTable, setSelectedTable] = useState<string | null>(table ?? null);
  const [page, setPage] = useState(0);
  const [sortState, setSortState] = useState<SortState>({ sort: null, dir: "asc" });

  useEffect(() => {
    if (table && table !== selectedTable) {
      setSelectedTable(table);
      setPage(0);
      setSortState({ sort: null, dir: "asc" });
    }
  }, [table]); // eslint-disable-line react-hooks/exhaustive-deps

  const { data: tablesData, isLoading: tablesLoading, error: tablesError } = useQuery({
    queryKey: ["project", projectId, "db-tables"],
    queryFn: () =>
      api.get<{ tables: DbTable[] }>(`/api/projects/${projectId}/db/tables`),
    enabled: !!dbPort,
  });

  const offset = page * PAGE_SIZE;
  const { data: queryResult, isLoading: queryLoading } = useQuery({
    queryKey: ["project", projectId, "db-rows", selectedTable, page, sortState.sort, sortState.dir],
    queryFn: () =>
      api.get<RowsResult>(
        dbRowsUrl(projectId, selectedTable as string, page, PAGE_SIZE, sortState.sort, sortState.dir),
      ),
    enabled: !!selectedTable && !!dbPort,
  });

  const tables = tablesData?.tables ?? [];

  if (!dbPort) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2">
        <AlertCircle className="h-8 w-8 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">
          No database running — start preview first
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full">
      {/* Table list */}
      <div className="w-52 shrink-0 overflow-y-auto border-r">
        <div className="border-b px-3 py-2">
          <span className="text-xs font-semibold uppercase text-muted-foreground">
            Tables
          </span>
        </div>
        {tablesLoading ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          </div>
        ) : tablesError ? (
          <p className="px-3 py-4 text-xs text-red-500">
            Failed to load tables
          </p>
        ) : (
          tables.map((t) => (
            <button
              key={t.name}
              className={cn(
                "flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-muted/50",
                selectedTable === t.name && "bg-muted font-medium",
              )}
              onClick={() => {
                setSelectedTable(t.name);
                setPage(0);
                setSortState({ sort: null, dir: "asc" });
              }}
            >
              <Table2 className="h-3 w-3 shrink-0 text-muted-foreground" />
              <span className="truncate">{t.name}</span>
              <span className="ml-auto text-[10px] text-muted-foreground">
                {t.row_count}
              </span>
            </button>
          ))
        )}
      </div>

      {/* Data grid */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {!selectedTable ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            Select a table to browse data
          </div>
        ) : queryLoading ? (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : !queryResult || queryResult.rows.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            No data in {selectedTable}
          </div>
        ) : (
          <>
            <div className="flex-1 overflow-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-slate-50">
                  <tr>
                    {queryResult.columns.map((col) => (
                      <th
                        key={col}
                        className="cursor-pointer select-none border-b px-3 py-2 text-left font-medium text-slate-600 hover:bg-slate-100"
                        onClick={() => {
                          setSortState((s) => nextSortState(s, col));
                          setPage(0);
                        }}
                      >
                        {col}
                        {sortState.sort === col ? (sortState.dir === "asc" ? " ▲" : " ▼") : ""}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {queryResult.rows.map((row, i) => (
                    <tr key={i} className="hover:bg-slate-50/50">
                      {queryResult.columns.map((col) => (
                        <td
                          key={col}
                          className="border-b px-3 py-1.5 font-mono text-slate-700"
                        >
                          {row[col] === null ? (
                            <span className="text-gray-400 italic">null</span>
                          ) : (
                            String(row[col])
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <div className="flex items-center justify-between border-t px-3 py-2">
              <span className="text-xs text-muted-foreground">
                Showing {queryResult.rows.length === 0 ? 0 : offset + 1}–{offset + queryResult.rows.length} of {queryResult.total}
              </span>
              <div className="flex gap-1">
                <Button variant="ghost" size="icon" className="h-7 w-7" disabled={page === 0} onClick={() => setPage(page - 1)}>
                  <ChevronLeft className="h-3 w-3" />
                </Button>
                <Button variant="ghost" size="icon" className="h-7 w-7" disabled={offset + PAGE_SIZE >= queryResult.total} onClick={() => setPage(page + 1)}>
                  <ChevronRight className="h-3 w-3" />
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
