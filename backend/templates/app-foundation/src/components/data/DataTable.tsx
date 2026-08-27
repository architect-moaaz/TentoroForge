"use client";

import { useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";

export interface Column<T = any> {
  key: string;
  label: string;
  render?: (value: any, item: T) => React.ReactNode;
  href?: (item: T) => string;  // makes the cell a clickable link
  className?: string;
}

interface DataTableProps<T = any> {
  data: T[];
  columns: Column<T>[];
  total?: number;
  page?: number;
  pageSize?: number;
  onPageChange?: (page: number) => void;
  emptyMessage?: string;
  className?: string;
}

export function DataTable<T extends Record<string, any>>({
  data,
  columns,
  total,
  page = 1,
  pageSize = 50,
  onPageChange,
  emptyMessage = "No data",
  className,
}: DataTableProps<T>) {
  const totalPages = total ? Math.ceil(total / pageSize) : 1;

  return (
    <div className={cn("rounded-xl border bg-card shadow-sm overflow-hidden", className)}>
      {/* Desktop table */}
      <div className="hidden md:block overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              {columns.map((col) => (
                <TableHead key={col.key} className={col.className}>{col.label}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.length === 0 ? (
              <TableRow>
                <TableCell colSpan={columns.length} className="text-center py-8 text-muted-foreground">
                  {emptyMessage}
                </TableCell>
              </TableRow>
            ) : (
              data.map((item, i) => (
                <TableRow key={item.id || i} className="hover:bg-muted/50">
                  {columns.map((col) => {
                    const value = item[col.key];
                    const content = col.render ? col.render(value, item) : String(value ?? "—");
                    return (
                      <TableCell key={col.key} className={col.className}>
                        {col.href ? (
                          <Link href={col.href(item)} className="font-medium text-primary hover:underline">
                            {content}
                          </Link>
                        ) : content}
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Mobile cards */}
      <div className="block md:hidden divide-y">
        {data.length === 0 ? (
          <p className="text-center py-8 text-muted-foreground">{emptyMessage}</p>
        ) : (
          data.map((item, i) => (
            <div key={item.id || i} className="p-4 space-y-1">
              {columns.map((col) => {
                const value = item[col.key];
                const content = col.render ? col.render(value, item) : String(value ?? "—");
                return (
                  <div key={col.key} className="flex justify-between text-sm">
                    <span className="text-muted-foreground">{col.label}</span>
                    <span className="font-medium text-foreground">
                      {col.href ? (
                        <Link href={col.href(item)} className="text-primary hover:underline">{content}</Link>
                      ) : content}
                    </span>
                  </div>
                );
              })}
            </div>
          ))
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && onPageChange && (
        <div className="flex items-center justify-between border-t px-4 py-3">
          <span className="text-xs text-muted-foreground">Page {page} of {totalPages}</span>
          <div className="flex gap-1">
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
