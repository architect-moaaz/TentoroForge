"use client";

import { useState } from "react";
import {
  Download,
  FileArchive,
  Container,
  GitBranch,
  Loader2,
  Check,
  Copy,
  Package,
  FileText,
  FileCode,
  Settings,
  AlertCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";

interface ExportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  projectName: string;
}

interface FileContentResponse {
  filename: string;
  content: string;
}

interface GitPushResponse {
  success: boolean;
  branch: string;
  repo_url: string;
  commit_hash: string | null;
}

interface ProductionBundleResponse {
  files_written: string[];
  message: string;
}

type ExportTab = "files" | "git" | "bundle";

export function ExportDialog({
  open,
  onOpenChange,
  projectId,
  projectName,
}: ExportDialogProps) {
  const [activeTab, setActiveTab] = useState<ExportTab>("files");

  // File generation state
  const [isGenerating, setIsGenerating] = useState<string | null>(null);
  const [generatedFiles, setGeneratedFiles] = useState<Record<string, string>>({});
  const [copied, setCopied] = useState<string | null>(null);

  // Git push state
  const [repoUrl, setRepoUrl] = useState("");
  const [branch, setBranch] = useState("main");
  const [gitToken, setGitToken] = useState("");
  const [isPushing, setIsPushing] = useState(false);
  const [gitResult, setGitResult] = useState<GitPushResponse | null>(null);
  const [gitError, setGitError] = useState<string | null>(null);

  // Production bundle state
  const [isBundling, setIsBundling] = useState(false);
  const [bundleResult, setBundleResult] = useState<ProductionBundleResponse | null>(null);
  const [bundleError, setBundleError] = useState<string | null>(null);

  // ZIP download state
  const [includeReadme, setIncludeReadme] = useState(true);
  const [includeDockerCompose, setIncludeDockerCompose] = useState(true);
  const [includeEnvExample, setIncludeEnvExample] = useState(true);
  const [isDownloading, setIsDownloading] = useState(false);

  const generateFile = async (
    endpoint: string,
    key: string,
  ) => {
    setIsGenerating(key);
    try {
      const result = await api.post<FileContentResponse>(
        `/api/projects/${projectId}/export/${endpoint}`,
      );
      setGeneratedFiles((prev) => ({ ...prev, [key]: result.content }));
    } catch {
      // Error silently handled — user sees no content
    } finally {
      setIsGenerating(null);
    }
  };

  const handleGitPush = async () => {
    if (!repoUrl.trim()) return;
    setIsPushing(true);
    setGitResult(null);
    setGitError(null);

    try {
      const result = await api.post<GitPushResponse>(
        `/api/projects/${projectId}/export/git-push`,
        {
          repo_url: repoUrl.trim(),
          branch: branch.trim() || "main",
          token: gitToken.trim() || null,
        },
      );
      setGitResult(result);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Git push failed";
      setGitError(message);
    } finally {
      setIsPushing(false);
    }
  };

  const handleProductionBundle = async () => {
    setIsBundling(true);
    setBundleResult(null);
    setBundleError(null);

    try {
      const result = await api.post<ProductionBundleResponse>(
        `/api/projects/${projectId}/export/production-bundle`,
      );
      setBundleResult(result);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Bundle generation failed";
      setBundleError(message);
    } finally {
      setIsBundling(false);
    }
  };

  const handleDownloadZip = async () => {
    setIsDownloading(true);
    try {
      const token = localStorage.getItem("token");
      const resp = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500"}/api/projects/${projectId}/download`,
        {
          headers: {
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
        },
      );
      if (!resp.ok) throw new Error("Download failed");

      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${projectName.toLowerCase().replace(/\s+/g, "-")}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // Error silently handled
    } finally {
      setIsDownloading(false);
    }
  };

  const copyToClipboard = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopied(key);
    setTimeout(() => setCopied(null), 2000);
  };

  const FILE_ACTIONS = [
    {
      key: "dockerfile",
      endpoint: "dockerfile",
      label: "Dockerfile",
      description: "Multi-stage production build",
      icon: Container,
    },
    {
      key: "docker-compose",
      endpoint: "docker-compose",
      label: "docker-compose.yml",
      description: "App + PostgreSQL with health checks",
      icon: Settings,
    },
    {
      key: "readme",
      endpoint: "readme",
      label: "README.md",
      description: "Setup instructions & documentation",
      icon: FileText,
    },
    {
      key: "env-example",
      endpoint: "env-example",
      label: ".env.example",
      description: "Documented environment variables",
      icon: FileCode,
    },
  ];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Download className="h-5 w-5" />
            Export &amp; Deploy
          </DialogTitle>
        </DialogHeader>

        <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as ExportTab)}>
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="files" className="gap-1.5">
              <FileArchive className="h-3.5 w-3.5" />
              Files
            </TabsTrigger>
            <TabsTrigger value="git" className="gap-1.5">
              <GitBranch className="h-3.5 w-3.5" />
              Git Push
            </TabsTrigger>
            <TabsTrigger value="bundle" className="gap-1.5">
              <Package className="h-3.5 w-3.5" />
              Bundle
            </TabsTrigger>
          </TabsList>

          {/* ============================================================= */}
          {/* Files Tab — Generate & preview individual deployment files      */}
          {/* ============================================================= */}
          <TabsContent value="files" className="space-y-4">
            {/* ZIP download */}
            <div className="rounded-lg border p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">Download ZIP</p>
                  <p className="text-xs text-muted-foreground">
                    Download the full project as a ZIP archive
                  </p>
                </div>
                <Button
                  size="sm"
                  onClick={handleDownloadZip}
                  disabled={isDownloading}
                >
                  {isDownloading ? (
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Download className="mr-1.5 h-3.5 w-3.5" />
                  )}
                  {isDownloading ? "Downloading..." : "Download"}
                </Button>
              </div>
            </div>

            {/* Individual file generators */}
            <div className="space-y-3">
              <p className="text-sm font-medium">Generate Deployment Files</p>
              {FILE_ACTIONS.map(({ key, endpoint, label, description, icon: Icon }) => (
                <div key={key} className="rounded-lg border p-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                      <Icon className="h-4 w-4 text-muted-foreground" />
                      <div>
                        <p className="text-sm font-medium">{label}</p>
                        <p className="text-xs text-muted-foreground">{description}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5">
                      {generatedFiles[key] && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 gap-1 text-xs"
                          onClick={() => copyToClipboard(generatedFiles[key], key)}
                        >
                          {copied === key ? (
                            <Check className="h-3 w-3" />
                          ) : (
                            <Copy className="h-3 w-3" />
                          )}
                          {copied === key ? "Copied" : "Copy"}
                        </Button>
                      )}
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 text-xs"
                        onClick={() => generateFile(endpoint, key)}
                        disabled={isGenerating === key}
                      >
                        {isGenerating === key ? (
                          <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                        ) : null}
                        {generatedFiles[key] ? "Regenerate" : "Generate"}
                      </Button>
                    </div>
                  </div>

                  {/* File preview */}
                  {generatedFiles[key] && (
                    <pre className="mt-3 max-h-48 overflow-auto rounded-md bg-muted p-3 text-xs leading-relaxed">
                      {generatedFiles[key]}
                    </pre>
                  )}
                </div>
              ))}
            </div>
          </TabsContent>

          {/* ============================================================= */}
          {/* Git Push Tab                                                    */}
          {/* ============================================================= */}
          <TabsContent value="git" className="space-y-4">
            <div className="rounded-lg border p-4 space-y-4">
              <div>
                <p className="text-sm font-medium">Push to Git Repository</p>
                <p className="text-xs text-muted-foreground">
                  Push the generated code to your own Git repository
                </p>
              </div>

              <div className="space-y-3">
                <div className="space-y-1.5">
                  <Label htmlFor="repo-url" className="text-xs">
                    Repository URL
                  </Label>
                  <Input
                    id="repo-url"
                    placeholder="https://github.com/user/repo.git"
                    value={repoUrl}
                    onChange={(e) => setRepoUrl(e.target.value)}
                    className="h-8 text-sm"
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="branch" className="text-xs">
                      Branch
                    </Label>
                    <Input
                      id="branch"
                      placeholder="main"
                      value={branch}
                      onChange={(e) => setBranch(e.target.value)}
                      className="h-8 text-sm"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <Label htmlFor="git-token" className="text-xs">
                      Access Token (optional)
                    </Label>
                    <Input
                      id="git-token"
                      type="password"
                      placeholder="ghp_..."
                      value={gitToken}
                      onChange={(e) => setGitToken(e.target.value)}
                      className="h-8 text-sm"
                    />
                  </div>
                </div>

                <p className="text-xs text-muted-foreground">
                  For GitHub, use a Personal Access Token with repo scope. For
                  GitLab, use a Project Access Token.
                </p>
              </div>

              <Button
                className="w-full"
                onClick={handleGitPush}
                disabled={isPushing || !repoUrl.trim()}
              >
                {isPushing ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Pushing...
                  </>
                ) : (
                  <>
                    <GitBranch className="mr-2 h-4 w-4" />
                    Push to Repository
                  </>
                )}
              </Button>

              {/* Git result */}
              {gitResult && (
                <div className="rounded-md bg-green-50 dark:bg-green-950/20 border border-green-200 dark:border-green-800 p-3">
                  <div className="flex items-center gap-2 text-green-700 dark:text-green-400">
                    <Check className="h-4 w-4" />
                    <p className="text-sm font-medium">Successfully pushed</p>
                  </div>
                  <div className="mt-2 space-y-1 text-xs text-green-600 dark:text-green-500">
                    <p>Branch: {gitResult.branch}</p>
                    <p>Repository: {gitResult.repo_url}</p>
                    {gitResult.commit_hash && (
                      <p>Commit: {gitResult.commit_hash.slice(0, 8)}</p>
                    )}
                  </div>
                </div>
              )}

              {/* Git error */}
              {gitError && (
                <div className="rounded-md bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800 p-3">
                  <div className="flex items-center gap-2 text-red-700 dark:text-red-400">
                    <AlertCircle className="h-4 w-4" />
                    <p className="text-sm font-medium">Push failed</p>
                  </div>
                  <p className="mt-1 text-xs text-red-600 dark:text-red-500">
                    {gitError}
                  </p>
                </div>
              )}
            </div>
          </TabsContent>

          {/* ============================================================= */}
          {/* Bundle Tab — Generate all production files at once              */}
          {/* ============================================================= */}
          <TabsContent value="bundle" className="space-y-4">
            <div className="rounded-lg border p-4 space-y-4">
              <div>
                <p className="text-sm font-medium">Production Bundle</p>
                <p className="text-xs text-muted-foreground">
                  Generate all deployment files (Dockerfile, docker-compose.yml,
                  .env.example, README.md) and add them directly to the project
                  output directory.
                </p>
              </div>

              <div className="rounded-md bg-muted/50 p-3 space-y-1.5">
                <p className="text-xs font-medium">Files that will be created:</p>
                <ul className="text-xs text-muted-foreground space-y-0.5">
                  <li className="flex items-center gap-1.5">
                    <Container className="h-3 w-3" /> Dockerfile — multi-stage Next.js build
                  </li>
                  <li className="flex items-center gap-1.5">
                    <Settings className="h-3 w-3" /> docker-compose.yml — app + PostgreSQL
                  </li>
                  <li className="flex items-center gap-1.5">
                    <FileCode className="h-3 w-3" /> .env.example — documented env vars
                  </li>
                  <li className="flex items-center gap-1.5">
                    <FileText className="h-3 w-3" /> README.md — setup & deployment docs
                  </li>
                </ul>
              </div>

              <Button
                className="w-full"
                onClick={handleProductionBundle}
                disabled={isBundling}
              >
                {isBundling ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Generating...
                  </>
                ) : (
                  <>
                    <Package className="mr-2 h-4 w-4" />
                    Generate Production Bundle
                  </>
                )}
              </Button>

              {/* Bundle result */}
              {bundleResult && (
                <div className="rounded-md bg-green-50 dark:bg-green-950/20 border border-green-200 dark:border-green-800 p-3">
                  <div className="flex items-center gap-2 text-green-700 dark:text-green-400">
                    <Check className="h-4 w-4" />
                    <p className="text-sm font-medium">{bundleResult.message}</p>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {bundleResult.files_written.map((f) => (
                      <span
                        key={f}
                        className="inline-flex items-center rounded-md bg-green-100 dark:bg-green-900/30 px-2 py-0.5 text-xs text-green-700 dark:text-green-400"
                      >
                        {f}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Bundle error */}
              {bundleError && (
                <div className="rounded-md bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800 p-3">
                  <div className="flex items-center gap-2 text-red-700 dark:text-red-400">
                    <AlertCircle className="h-4 w-4" />
                    <p className="text-sm font-medium">Generation failed</p>
                  </div>
                  <p className="mt-1 text-xs text-red-600 dark:text-red-500">
                    {bundleError}
                  </p>
                </div>
              )}
            </div>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
