"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, UploadCloud } from "lucide-react";
import { toast } from "sonner";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs";
import { Textarea } from "./ui/textarea";

import {useBookRuntime} from "../VellumRuntime";

type ImportBooksDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImported: () => void;
};

export function ImportBooksDialog({
  open,
  onOpenChange,
  onImported,
}: ImportBooksDialogProps) {
  const runtime = useBookRuntime();
  const consent = {rightsAttestationVersion:runtime.rightsVersion, scanApproved:true, localOnly:true};
  const [file, setFile] = useState<File | null>(null);
  const [cover, setCover] = useState<File | null>(null);
  const [fileTitle, setFileTitle] = useState("");
  const [fileAuthor, setFileAuthor] = useState("");
  const [uploading, setUploading] = useState(false);

  const [pasteTitle, setPasteTitle] = useState("");
  const [pasteAuthor, setPasteAuthor] = useState("");
  const [pasteText, setPasteText] = useState("");
  const [urlValue, setUrlValue] = useState("");
  const [importingPaste, setImportingPaste] = useState(false);
  const [importingUrl, setImportingUrl] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const coverInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) {
      setFile(null);
      setCover(null);
      setFileTitle("");
      setFileAuthor("");
      setPasteTitle("");
      setPasteAuthor("");
      setPasteText("");
      setUrlValue("");
    }
  }, [open]);

  const selectFile = (selected: File | null) => {
    setFile(selected);
    setFileTitle(selected?.name.replace(/\.(txt|md|epub)$/i, "").trim() || "");
    setFileAuthor("");
    setCover(null);
    if (coverInputRef.current) coverInputRef.current.value = "";
  };

  const handleUpload = async () => {
    if (!file) {
      toast.error("Choose a .txt, .md or .epub file first");
      return;
    }
    setUploading(true);
    try {
      const automaticTitle = file.name.replace(/\.(txt|md|epub)$/i, "").trim();
      const data = await runtime.importFile(file,fileTitle.trim() === automaticTitle ? "" : fileTitle.trim(),fileAuthor.trim(),cover,consent);
      if (data.alreadyPresent) toast.info(`“${data.title}” is already on your shelf`);
      else toast.success(`“${data.title}” added to the shelf`);
      onImported();
      onOpenChange(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Import failed — please try again");
    } finally {
      setUploading(false);
    }
  };

  const handlePaste = async () => {
    if (pasteTitle.trim().length === 0) {
      toast.error("Give the book a title");
      return;
    }
    if (pasteText.trim().length < 40) {
      toast.error("Paste a bit more text — that looks too short");
      return;
    }
    setImportingPaste(true);
    try {
      await runtime.importText(pasteTitle.trim(),pasteAuthor.trim(),pasteText,consent);
      toast.success(`“${pasteTitle.trim()}” added to the shelf`);
      onImported();
      onOpenChange(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Import failed — please try again");
    } finally {
      setImportingPaste(false);
    }
  };

  const handleUrl = async () => {
    if (urlValue.trim().length === 0) {
      toast.error("Paste a URL first");
      return;
    }
    setImportingUrl(true);
    try {
      const data = await runtime.importUrl(urlValue.trim(),consent);
      toast.success(`“${data.title}” added to the shelf`);
      onImported();
      onOpenChange(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Import failed — please try again");
    } finally {
      setImportingUrl(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85dvh] overflow-y-auto bg-white sm:max-w-lg dark:bg-[#1c1712]">
        <DialogHeader>
          <DialogTitle className="font-serif text-[1.25rem] tracking-[-0.02em] text-neutral-900 dark:text-neutral-100">
            Import books
          </DialogTitle>
          <DialogDescription className="text-[13px] text-neutral-500 dark:text-neutral-400">
            Add your own volumes to the shelf — upload a file, paste text, or
            fetch a plain-text URL.
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="upload" className="gap-4">
          <TabsList className="grid w-full grid-cols-2 bg-neutral-100 text-neutral-600 dark:bg-white/10 dark:text-neutral-300">
            <TabsTrigger value="upload" className="cursor-pointer text-[13px]">
              Upload file
            </TabsTrigger>
            <TabsTrigger value="paste" className="cursor-pointer text-[13px]">
              Paste text
            </TabsTrigger>
          </TabsList>

          {/* Upload file */}
          <TabsContent value="upload" className="space-y-3">
            <button
              type="button"
              onDragOver={event => {event.preventDefault(); event.dataTransfer.dropEffect='copy';}}
              onDrop={event => {event.preventDefault(); selectFile(event.dataTransfer.files?.[0] ?? null);}}
              onClick={() => fileInputRef.current?.click()}
              className="flex w-full cursor-pointer flex-col items-center gap-1.5 rounded-lg border border-dashed border-neutral-300 bg-neutral-50/50 px-4 py-7 text-center transition-colors hover:border-neutral-400 hover:bg-neutral-50 dark:border-white/20 dark:bg-white/5 dark:hover:border-white/35 dark:hover:bg-white/10"
            >
              <UploadCloud className="size-5 text-neutral-400 dark:text-neutral-500" />
              <span className="text-[13.5px] font-medium text-neutral-700 dark:text-neutral-200">
                {file ? file.name : "Choose a book file"}
              </span>
              <span className="text-[11.5px] text-neutral-400 dark:text-neutral-500">
                .txt · .md · .epub — text and cover are extracted automatically
              </span>
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".txt,.md,.epub,text/plain,text/markdown,application/epub+zip"
              className="hidden"
              onChange={(event) => {
                selectFile(event.target.files?.[0] ?? null);
                event.target.value = "";
              }}
            />
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="import-title" className="text-[12px] text-neutral-500 dark:text-neutral-400">
                  Title
                </Label>
                <Input
                  id="import-title"
                  value={fileTitle}
                  onChange={(event) => setFileTitle(event.target.value)}
                  placeholder="Book title"
                  className="h-9 border-neutral-200 text-[13.5px] dark:border-white/15"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="import-author" className="text-[12px] text-neutral-500 dark:text-neutral-400">
                  Author
                </Label>
                <Input
                  id="import-author"
                  value={fileAuthor}
                  onChange={(event) => setFileAuthor(event.target.value)}
                  placeholder="Author"
                  className="h-9 border-neutral-200 text-[13.5px] dark:border-white/15"
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label className="text-[12px] text-neutral-500 dark:text-neutral-400">
                Cover image (optional — auto-extracted from EPUB)
              </Label>
              <button
                type="button"
                onClick={() => coverInputRef.current?.click()}
                className="w-full cursor-pointer rounded-md border border-neutral-200 px-3 py-2 text-left text-[12.5px] text-neutral-500 transition-colors hover:bg-neutral-50 dark:border-white/15 dark:text-neutral-400 dark:hover:bg-white/5"
              >
                {cover ? cover.name : "Choose an image for the shelf cover…"}
              </button>
              <input
                ref={coverInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(event) => {
                  setCover(event.target.files?.[0] ?? null);
                }}
              />
            </div>
            <Button
              type="button"
              disabled={uploading || !file}
              onClick={() => void handleUpload()}
              className="h-9 w-full cursor-pointer bg-neutral-900 text-[13px] text-white hover:bg-neutral-700 disabled:opacity-60 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300"
            >
              {uploading ? (
                <>
                  <Loader2 className="size-4 animate-spin" /> Importing…
                </>
              ) : (
                "Add to shelf"
              )}
            </Button>
          </TabsContent>

          {/* Paste text */}
          <TabsContent value="paste" className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="paste-title" className="text-[12px] text-neutral-500 dark:text-neutral-400">
                  Title
                </Label>
                <Input
                  id="paste-title"
                  value={pasteTitle}
                  onChange={(event) => setPasteTitle(event.target.value)}
                  placeholder="Book title"
                  className="h-9 border-neutral-200 text-[13.5px] dark:border-white/15"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="paste-author" className="text-[12px] text-neutral-500 dark:text-neutral-400">
                  Author
                </Label>
                <Input
                  id="paste-author"
                  value={pasteAuthor}
                  onChange={(event) => setPasteAuthor(event.target.value)}
                  placeholder="Author"
                  className="h-9 border-neutral-200 text-[13.5px] dark:border-white/15"
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="paste-text" className="text-[12px] text-neutral-500 dark:text-neutral-400">
                Book text
              </Label>
              <Textarea
                id="paste-text"
                value={pasteText}
                onChange={(event) => setPasteText(event.target.value)}
                placeholder="Paste the full text here…"
                className="h-40 resize-none border-neutral-200 text-[13px] leading-relaxed dark:border-white/15"
              />
            </div>
            <Button
              type="button"
              disabled={importingPaste}
              onClick={() => void handlePaste()}
              className="h-9 w-full cursor-pointer bg-neutral-900 text-[13px] text-white hover:bg-neutral-700 disabled:opacity-60 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300"
            >
              {importingPaste ? (
                <>
                  <Loader2 className="size-4 animate-spin" /> Importing…
                </>
              ) : (
                "Add to shelf"
              )}
            </Button>
            <div className="rounded-lg border border-neutral-100 bg-neutral-50/60 p-3 dark:border-white/10 dark:bg-white/5">
              <p className="mb-2 text-[12px] font-medium text-neutral-500 dark:text-neutral-400">
                Or fetch a plain-text URL
              </p>
              <div className="flex gap-2">
                <Input
                  value={urlValue}
                  onChange={(event) => setUrlValue(event.target.value)}
                  placeholder="https://www.gutenberg.org/cache/epub/…/pg….txt"
                  className="h-9 border-neutral-200 bg-white text-[12.5px] dark:border-white/15 dark:bg-white/5"
                />
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={importingUrl}
                  onClick={() => void handleUrl()}
                  className="h-9 shrink-0 cursor-pointer border-neutral-200 px-3 text-[12.5px] text-neutral-700 hover:bg-neutral-100 disabled:opacity-60 dark:border-white/15 dark:text-neutral-200 dark:hover:bg-white/10"
                >
                  {importingUrl ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    "Fetch"
                  )}
                </Button>
              </div>
              <p className="mt-1.5 text-[11px] text-neutral-400 dark:text-neutral-500">
                Gutenberg and .epub URLs also grab the real cover automatically.
              </p>
            </div>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
