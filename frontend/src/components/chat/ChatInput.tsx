"use client";

import { useState, useRef, useCallback } from "react";
import {
  Send, Loader2, Mic, Volume2, VolumeX, Paperclip, X, FileText, ImageIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useSpeechRecognition } from "@/lib/voice";
import {
  SlashCommandPalette,
  useSlashCommandFilter,
  type SlashCommand,
} from "./SlashCommands";

/** One uploaded attachment, as returned by
 *  `POST /api/projects/{id}/attachments`. */
export interface ChatAttachment {
  id: string;
  filename: string;
  kind: "image" | "pdf" | "text";
}

interface ChatInputProps {
  /** `attachmentIds` is empty unless the user attached something. */
  onSend: (message: string, attachmentIds?: string[]) => void;
  disabled?: boolean;
  placeholder?: string;
  /** Whether spoken-reply (TTS) mode is on — controls the speaker toggle icon. */
  voiceReplyOn?: boolean;
  /** Toggle spoken replies. When omitted, the speaker button is hidden. */
  onToggleVoiceReply?: () => void;
  /** Hide the speaker toggle when TTS isn't available in this browser. */
  showVoiceReplyToggle?: boolean;
  /** Upload boundary, injected so this component stays presentational and
   *  testable. When omitted the paperclip is hidden entirely — that keeps
   *  every other ChatInput mount (which has no project to attach to)
   *  unchanged rather than showing a button that cannot work. */
  uploadAttachment?: (file: File) => Promise<ChatAttachment>;
}

export function ChatInput({
  onSend,
  disabled = false,
  placeholder = "Describe your app or ask for changes...",
  voiceReplyOn = false,
  onToggleVoiceReply,
  showVoiceReplyToggle = false,
  uploadAttachment,
}: ChatInputProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [uploading, setUploading] = useState(0);
  const [attachError, setAttachError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  /** Upload files and add chips. Errors surface inline: the backend's 400
   *  messages ("report.docx is not supported…") are written to be shown
   *  verbatim, and silently dropping a file the user just picked is the
   *  one outcome that must never happen. */
  const addFiles = useCallback(async (files: File[]) => {
    if (!uploadAttachment || files.length === 0) return;
    setAttachError(null);
    setUploading((n) => n + files.length);
    for (const f of files) {
      try {
        const rec = await uploadAttachment(f);
        setAttachments((prev) => [...prev, rec]);
      } catch (err) {
        setAttachError(err instanceof Error ? err.message : `Could not attach ${f.name}`);
      } finally {
        setUploading((n) => n - 1);
      }
    }
  }, [uploadAttachment]);

  /** Cmd-V of a screenshot — the single most common way this gets used,
   *  so it must work without touching the paperclip. */
  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    if (!uploadAttachment) return;
    const files = Array.from(e.clipboardData?.files ?? []);
    if (files.length > 0) {
      e.preventDefault();
      void addFiles(files);
    }
  }, [uploadAttachment, addFiles]);

  // Slash-command palette — visible only while the current value looks
  // like a command being typed (leading '/' + no whitespace yet).
  const { active: slashOpen, matches: slashMatches } = useSlashCommandFilter(value);
  const [slashIndex, setSlashIndex] = useState(0);

  /** Apply a picked slash command: replace the current input with the
   *  command's template, position the cursor at the `⎽` marker (which
   *  we strip), and refocus the textarea. `/undo` and `/help` insert a
   *  full user message and auto-send. */
  const applySlash = useCallback((cmd: SlashCommand) => {
    const marker = "⎽";
    const caret = cmd.insert.indexOf(marker);
    const cleaned = cmd.insert.replace(marker, "");
    // "/undo" and "/help" are one-shot verbs — auto-send the template
    // rather than making the user press Enter afterwards.
    if (cmd.id === "undo" || cmd.id === "help") {
      if (!disabled) onSend(cleaned);
      setValue("");
      return;
    }
    setValue(cleaned);
    // Restore focus + place the cursor at the marker after React
    // renders the new value.
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.focus();
      const pos = caret >= 0 ? caret : cleaned.length;
      el.setSelectionRange(pos, pos);
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 200) + "px";
    });
  }, [disabled, onSend]);

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    // An attachment on its own is a legitimate turn — people paste a
    // screenshot and hit Enter expecting "build this".
    if ((!trimmed && attachments.length === 0) || disabled || uploading > 0) return;
    onSend(trimmed, attachments.map((a) => a.id));
    setValue("");
    setAttachments([]);
    setAttachError(null);
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [value, disabled, onSend, attachments, uploading]);

  // ── Voice dictation: live transcript previews in the box; a natural pause
  // ends the utterance and auto-sends (the user's chosen behaviour). ──────────
  const { supported: micSupported, listening, toggle: toggleMic } =
    useSpeechRecognition({
      onInterim: (t) => setValue(t),
      onFinal: (t) => {
        setValue("");
        const trimmed = t.trim();
        if (trimmed && !disabled) onSend(trimmed);
      },
    });

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      // Slash-command palette navigation takes priority over textarea keys
      // when the palette is open with at least one match.
      if (slashOpen && slashMatches.length > 0) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setSlashIndex((i) => (i + 1) % slashMatches.length);
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          setSlashIndex(
            (i) => (i - 1 + slashMatches.length) % slashMatches.length,
          );
          return;
        }
        if (e.key === "Enter" || e.key === "Tab") {
          e.preventDefault();
          applySlash(slashMatches[slashIndex] ?? slashMatches[0]);
          return;
        }
        if (e.key === "Escape") {
          e.preventDefault();
          setValue("");
          return;
        }
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend, slashOpen, slashMatches, slashIndex, applySlash],
  );

  const handleInput = useCallback(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 200) + "px";
    }
  }, []);

  return (
    <div
      className="border-t bg-background px-4 md:px-6 py-3"
      onDragOver={uploadAttachment ? (e) => { e.preventDefault(); setDragging(true); } : undefined}
      onDragLeave={uploadAttachment ? () => setDragging(false) : undefined}
      onDrop={uploadAttachment ? (e) => {
        e.preventDefault();
        setDragging(false);
        void addFiles(Array.from(e.dataTransfer?.files ?? []));
      } : undefined}
    >
      <div className="mx-auto max-w-3xl">
        {/* Attached-file chips. Rendered above the box so a long filename
            never squeezes the textarea. */}
        {(attachments.length > 0 || uploading > 0) && (
          <div className="mb-2 flex flex-wrap gap-1.5">
            {attachments.map((a) => (
              <span
                key={a.id}
                className="inline-flex items-center gap-1.5 rounded-lg border bg-muted/50 px-2 py-1 text-xs"
              >
                {a.kind === "image"
                  ? <ImageIcon className="h-3 w-3 text-muted-foreground" />
                  : <FileText className="h-3 w-3 text-muted-foreground" />}
                <span className="max-w-[160px] truncate">{a.filename}</span>
                <button
                  type="button"
                  onClick={() => setAttachments((p) => p.filter((x) => x.id !== a.id))}
                  className="text-muted-foreground hover:text-foreground"
                  aria-label={`Remove ${a.filename}`}
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
            {uploading > 0 && (
              <span className="inline-flex items-center gap-1.5 rounded-lg border bg-muted/50 px-2 py-1 text-xs text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" />
                Uploading {uploading}…
              </span>
            )}
          </div>
        )}
        {attachError && (
          <p className="mb-2 text-xs text-red-600" role="alert">{attachError}</p>
        )}

        <div
          className={`relative flex items-end gap-2 rounded-2xl border bg-background shadow-sm transition-shadow focus-within:shadow-md focus-within:border-primary/30 ${
            dragging ? "border-primary ring-2 ring-primary/20" : ""
          }`}
        >
          {slashOpen && (
            <SlashCommandPalette
              matches={slashMatches}
              activeIndex={Math.min(slashIndex, Math.max(0, slashMatches.length - 1))}
              onHover={setSlashIndex}
              onPick={applySlash}
            />
          )}
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              // Reset the slash palette selection whenever the query
              // changes so ArrowDown doesn't land on a filtered-out row.
              if (e.target.value.startsWith("/")) setSlashIndex(0);
            }}
            onKeyDown={handleKeyDown}
            onInput={handleInput}
            onPaste={handlePaste}
            placeholder={listening ? "Listening…" : placeholder}
            disabled={disabled}
            rows={1}
            className="flex-1 resize-none bg-transparent px-4 py-3 text-sm placeholder:text-muted-foreground focus:outline-none disabled:opacity-50"
          />

          {/* Attach image / document */}
          {uploadAttachment && (
            <>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept="image/png,image/jpeg,image/gif,image/webp,application/pdf,.txt,.md,.csv,.tsv,.json,.yaml,.yml"
                className="hidden"
                onChange={(e) => {
                  void addFiles(Array.from(e.target.files ?? []));
                  e.target.value = "";   // let the same file be picked twice
                }}
              />
              <Button
                type="button"
                size="icon"
                variant="ghost"
                onClick={() => fileInputRef.current?.click()}
                disabled={disabled}
                title="Attach an image or document"
                className="h-8 w-8 shrink-0 mb-2 rounded-xl text-muted-foreground hover:text-foreground"
              >
                <Paperclip className="h-4 w-4" />
              </Button>
            </>
          )}

          {/* Spoken replies (TTS) toggle */}
          {showVoiceReplyToggle && onToggleVoiceReply && (
            <Button
              type="button"
              size="icon"
              variant="ghost"
              onClick={onToggleVoiceReply}
              title={voiceReplyOn ? "Spoken replies on" : "Spoken replies off"}
              aria-pressed={voiceReplyOn}
              className={`h-8 w-8 shrink-0 mb-2 rounded-xl transition-colors ${
                voiceReplyOn ? "text-primary" : "text-muted-foreground"
              }`}
            >
              {voiceReplyOn ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}
            </Button>
          )}

          {/* Microphone (speech-to-text, auto-send on pause) */}
          {micSupported && (
            <Button
              type="button"
              size="icon"
              variant="ghost"
              onClick={toggleMic}
              disabled={disabled}
              title={listening ? "Stop listening" : "Speak your message"}
              aria-pressed={listening}
              className={`h-8 w-8 shrink-0 mb-2 rounded-xl transition-colors ${
                listening
                  ? "text-red-500 bg-red-500/10 animate-pulse"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Mic className="h-4 w-4" />
            </Button>
          )}

          <Button
            size="icon"
            onClick={handleSend}
            disabled={
              disabled || uploading > 0 || (!value.trim() && attachments.length === 0)
            }
            className="h-8 w-8 shrink-0 mr-2 mb-2 rounded-xl transition-all disabled:opacity-30"
          >
            {disabled ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </Button>
        </div>
        <p className="mt-1.5 text-center text-[10px] text-muted-foreground">
          {listening
            ? "Listening — pause when you're done"
            : micSupported
              ? "Press Enter to send · click the mic to speak"
              : "Press Enter to send, Shift+Enter for new line"}
        </p>
      </div>
    </div>
  );
}
