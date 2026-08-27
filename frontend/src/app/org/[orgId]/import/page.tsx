"use client";

import { use, useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Upload, FileSpreadsheet, CheckCircle2, AlertCircle } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const PERSON_FIELDS = [
  { value: "email", label: "Email" },
  { value: "first_name", label: "First Name" },
  { value: "last_name", label: "Last Name" },
  { value: "title", label: "Title" },
  { value: "department", label: "Department" },
  { value: "team", label: "Team" },
  { value: "manager_email", label: "Manager Email" },
  { value: "__skip", label: "(Skip)" },
];

interface ImportError {
  row: number;
  field: string;
  message: string;
  value: string | null;
}

interface ImportResult {
  total_rows: number;
  imported: number;
  skipped: number;
  errors: ImportError[];
}

function ImportPage({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Record<string, string>[]>([]);
  const [columns, setColumns] = useState<string[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);

  const handleFileSelect = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const selectedFile = e.target.files?.[0];
      if (!selectedFile) return;

      setFile(selectedFile);
      setResult(null);

      const text = await selectedFile.text();
      let rows: Record<string, string>[] = [];

      if (selectedFile.name.endsWith(".json")) {
        try {
          rows = JSON.parse(text);
        } catch {
          return;
        }
      } else {
        // Parse CSV
        const lines = text.split("\n").filter((l) => l.trim());
        if (lines.length < 2) return;

        const headers = lines[0].split(",").map((h) => h.trim());
        for (let i = 1; i < lines.length; i++) {
          const values = lines[i].split(",").map((v) => v.trim());
          const row: Record<string, string> = {};
          headers.forEach((h, idx) => {
            row[h] = values[idx] || "";
          });
          rows.push(row);
        }
      }

      if (rows.length === 0) return;

      const cols = Object.keys(rows[0]);
      setColumns(cols);
      setPreview(rows.slice(0, 5));

      // Auto-map columns by name
      const autoMapping: Record<string, string> = {};
      const fieldNames = PERSON_FIELDS.map((f) => f.value);
      cols.forEach((col) => {
        const normalized = col.toLowerCase().replace(/[\s_-]+/g, "_");
        const match = fieldNames.find((f) => f === normalized);
        if (match) {
          autoMapping[match] = col;
        }
      });
      setMapping(autoMapping);
    },
    [],
  );

  async function handleImport() {
    if (!file) return;
    setImporting(true);
    setResult(null);

    try {
      // Build column mapping (reverse: field -> source column)
      const columnMapping: Record<string, string> = {};
      for (const [field, sourceCol] of Object.entries(mapping)) {
        if (field !== "__skip" && sourceCol) {
          columnMapping[field] = sourceCol;
        }
      }

      const formData = new FormData();
      formData.append("file", file);
      formData.append("column_mapping", JSON.stringify(columnMapping));

      const importResult = await api.upload<ImportResult>(
        `/api/orgs/${orgId}/people/import`,
        formData,
      );
      setResult(importResult);
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "people"] });
    } catch {
      setResult({
        total_rows: 0,
        imported: 0,
        skipped: 0,
        errors: [{ row: 0, field: "", message: "Import failed", value: null }],
      });
    } finally {
      setImporting(false);
    }
  }

  function reset() {
    setFile(null);
    setPreview([]);
    setColumns([]);
    setMapping({});
    setResult(null);
  }

  return (
    <div className="p-8">
      <h1 className="mb-6 text-2xl font-semibold text-foreground">Import People</h1>

      {/* Step 1: File Upload */}
      {!file && (
        <Card className="border-dashed">
          <CardHeader className="items-center text-center">
            <Upload className="mb-2 h-10 w-10 text-muted-foreground" />
            <CardTitle>Upload a file</CardTitle>
            <CardDescription>
              CSV or JSON file with people data
            </CardDescription>
          </CardHeader>
          <CardContent className="flex justify-center">
            <Label
              htmlFor="file-input"
              className="cursor-pointer rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              Choose File
            </Label>
            <Input
              id="file-input"
              type="file"
              accept=".csv,.json"
              className="hidden"
              onChange={handleFileSelect}
            />
          </CardContent>
        </Card>
      )}

      {/* Step 2: Preview + Column Mapping */}
      {file && !result && (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <FileSpreadsheet className="h-5 w-5 text-muted-foreground" />
                  <div>
                    <CardTitle className="text-base">{file.name}</CardTitle>
                    <CardDescription>
                      {preview.length} rows previewed, {columns.length} columns
                    </CardDescription>
                  </div>
                </div>
                <Button variant="outline" size="sm" onClick={reset}>
                  Change file
                </Button>
              </div>
            </CardHeader>
          </Card>

          {/* Column Mapping */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Column Mapping</CardTitle>
              <CardDescription>
                Map source columns to person fields
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid gap-3 sm:grid-cols-2">
                {PERSON_FIELDS.filter((f) => f.value !== "__skip").map(
                  (field) => (
                    <div key={field.value} className="flex items-center gap-2">
                      <Label className="w-32 text-sm">{field.label}</Label>
                      <Select
                        value={mapping[field.value] || ""}
                        onValueChange={(v) =>
                          setMapping({
                            ...mapping,
                            [field.value]: v === "__none" ? "" : v,
                          })
                        }
                      >
                        <SelectTrigger className="flex-1">
                          <SelectValue placeholder="Select column" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="__none">-- None --</SelectItem>
                          {columns.map((col) => (
                            <SelectItem key={col} value={col}>
                              {col}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  ),
                )}
              </div>
            </CardContent>
          </Card>

          {/* Preview Table */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Preview</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      {columns.map((col) => (
                        <TableHead key={col}>{col}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {preview.map((row, i) => (
                      <TableRow key={i}>
                        {columns.map((col) => (
                          <TableCell key={col}>{row[col] || ""}</TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>

          <div className="flex justify-end gap-3">
            <Button variant="outline" onClick={reset}>
              Cancel
            </Button>
            <Button onClick={handleImport} disabled={importing}>
              {importing ? "Importing..." : "Import"}
            </Button>
          </div>
        </div>
      )}

      {/* Step 3: Results */}
      {result && (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <div className="flex items-center gap-3">
                {result.imported > 0 ? (
                  <CheckCircle2 className="h-6 w-6 text-green-600" />
                ) : (
                  <AlertCircle className="h-6 w-6 text-destructive" />
                )}
                <div>
                  <CardTitle>Import Complete</CardTitle>
                  <CardDescription>
                    {result.imported} imported, {result.skipped} skipped out of{" "}
                    {result.total_rows} total
                  </CardDescription>
                </div>
              </div>
            </CardHeader>
          </Card>

          {result.errors.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">
                  Issues ({result.errors.length})
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {result.errors.map((err, i) => (
                    <div
                      key={i}
                      className="flex items-start gap-2 rounded-md bg-destructive/5 px-3 py-2 text-sm"
                    >
                      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                      <span>
                        {err.row > 0 && `Row ${err.row}: `}
                        {err.message}
                        {err.value && (
                          <span className="ml-1 text-muted-foreground">
                            ({err.value})
                          </span>
                        )}
                      </span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          <Button onClick={reset}>Import Another File</Button>
        </div>
      )}
    </div>
  );
}

export default function ImportPageWrapper({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = use(params);
  return <ImportPage orgId={orgId} />;
}
