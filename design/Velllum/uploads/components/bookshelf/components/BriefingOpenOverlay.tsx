"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { Trash2, X } from "lucide-react";
import {toast} from "sonner";
import type {
  BookOpenTransition,
  ShelfMode,
} from "../shelf/BriefingShelfEngine";
import type { FullBook, ShelfBookItem } from "../lib/book-types";
import { cn } from "../lib/utils";
import { BookReader } from "../reader/BookReader";

import {useBookRuntime} from "../VellumRuntime";

const PAGE_CONTENT_INSET = 0.05;

function clamp01(value: number) {
  return Math.min(1, Math.max(0, value));
}

function easeOutCubic(value: number) {
  const t = clamp01(value);
  return 1 - (1 - t) ** 3;
}

function insetRect(
  rect: NonNullable<BookOpenTransition["readerRect"]>,
  fraction: number,
) {
  const padX = rect.width * fraction;
  const padY = rect.height * fraction;
  return {
    x: rect.x + padX,
    y: rect.y + padY,
    width: Math.max(120, rect.width - padX * 2),
    height: Math.max(160, rect.height - padY * 2),
  };
}

/**
 * Fullscreen reader that expands out of the open book's page rect.
 * Keeps the 3D transition math; content is the full imported book.
 */
export function BriefingOpenOverlay({
  mode,
  transition,
  book,
  onBack,
  onRemove,
}: {
  mode: ShelfMode;
  transition: BookOpenTransition | null;
  book: ShelfBookItem;
  onBack: () => void;
  onRemove: (id:string) => Promise<void>;
}) {
  const runtime = useBookRuntime();
  const isActive =
    mode === "focusing" || mode === "open" || mode === "returning";
  const [loaded, setLoaded] = useState<{ id: string; book: FullBook } | null>(
    null,
  );
  const [loadError,setLoadError] = useState("");
  const [confirming,setConfirming] = useState(false);
  const [removing,setRemoving] = useState(false);
  const removeButton=useRef<HTMLButtonElement>(null),keepButton=useRef<HTMLButtonElement>(null);
  const removingRef=useRef(false);
  const cancelRemoval=useCallback(()=>{setConfirming(false);removeButton.current?.focus();},[]);
  const fullBook = loaded?.id === book.id ? loaded.book : null;

  useEffect(()=>{setConfirming(false);},[book.id]);
  useEffect(()=>{
    if(!confirming || removing) return;
    keepButton.current?.focus();
    let timer:number;
    const reset=()=>{window.clearTimeout(timer);timer=window.setTimeout(cancelRemoval,5000);};
    const events=['pointermove','pointerdown','keydown','wheel'] as const;
    reset();events.forEach(type=>window.addEventListener(type,reset,{passive:true}));
    return()=>{window.clearTimeout(timer);events.forEach(type=>window.removeEventListener(type,reset));};
  },[confirming,removing,cancelRemoval]);

  const confirmRemoval=async()=>{
    if(removingRef.current) return;
    removingRef.current=true;setRemoving(true);
    try{await onRemove(book.id);}
    catch(error){setConfirming(false);toast.error(error instanceof Error ? error.message : 'The book could not be removed.');}
    finally{removingRef.current=false;setRemoving(false);}
  };

  useEffect(() => {
    if (!isActive) return;
    setLoadError("");
    let cancelled = false;
    const abort = new AbortController();
    void runtime.loadBook(book,abort.signal)
      .then((fullBook) => {if(!cancelled) setLoaded({id:book.id,book:fullBook});})
      .catch((error) => {if(!cancelled && error.name!=='AbortError') setLoadError(error.message || 'The book could not be opened.');});
    return () => {
      cancelled = true; abort.abort();
    };
  }, [isActive, book.id]);

  useEffect(() => {
    if (!isActive) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if(confirming || removing){
          event.preventDefault();event.stopImmediatePropagation();
          if(!removing) cancelRemoval();
          return;
        }
        // Ignore Esc pressed while typing inside form fields (e.g. dialogs).
        const target = event.target as HTMLElement | null;
        if (
          target &&
          (target.tagName === "INPUT" ||
            target.tagName === "TEXTAREA" ||
            target.tagName === "SELECT" ||
            target.isContentEditable)
        ) {
          return;
        }
        event.preventDefault();
        event.stopImmediatePropagation();
        onBack();
      }
    };
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [isActive, onBack,confirming,removing,cancelRemoval]);

  if (!isActive) return null;

  const expand = transition?.expand ?? (mode === "open" ? 1 : 0);
  const rawRect = transition?.readerRect;
  const viewport = transition?.viewport ?? { width: 0, height: 0 };
  const startRect = rawRect ? insetRect(rawRect, PAGE_CONTENT_INSET) : null;

  const whiteOpacity = easeOutCubic(expand);
  const contentOpacity =
    mode === "open"
      ? 1
      : mode === "returning"
        ? clamp01(expand)
        : clamp01((expand - 0.55) / 0.35);
  const showWhitePanel = expand > 0.04 || mode === "open" || mode === "returning";

  let panelStyle: CSSProperties | undefined;
  if (startRect && viewport.width > 0) {
    panelStyle = {
      position: "absolute",
      left: startRect.x + (0 - startRect.x) * easeOutCubic(expand),
      top: startRect.y + (0 - startRect.y) * easeOutCubic(expand),
      width:
        startRect.width +
        (viewport.width - startRect.width) * easeOutCubic(expand),
      height:
        startRect.height +
        (viewport.height - startRect.height) * easeOutCubic(expand),
      opacity: whiteOpacity,
      overflow: "hidden",
      borderRadius: `${Math.max(0, 18 * (1 - easeOutCubic(expand)))}px`,
      boxShadow:
        expand < 0.98
          ? `0 ${24 * (1 - expand)}px ${64 * (1 - expand)}px rgba(0,0,0,${0.18 * (1 - expand)})`
          : "none",
    };
  } else {
    panelStyle = {
      position: "absolute",
      inset: 0,
      opacity: whiteOpacity,
      overflow: "hidden",
    };
  }

  return (
    <div className="pointer-events-none absolute inset-0 z-40">
      {showWhitePanel ? (
        <div
          style={panelStyle}
          className="pointer-events-auto flex flex-col bg-white dark:bg-[#1a1512]"
        >
          <div
            className="relative flex items-center justify-start gap-2 px-4 pt-4"
            style={{ opacity: contentOpacity }}
          >
            <button
              type="button"
              onClick={onBack}
              disabled={removing}
              aria-label="Close book"
              className="flex size-9 cursor-pointer items-center justify-center rounded-full text-neutral-500 transition-colors hover:bg-neutral-100 hover:text-neutral-900 dark:text-neutral-400 dark:hover:bg-white/10 dark:hover:text-neutral-100"
            >
              <X className="size-4" strokeWidth={2} />
            </button>
            <button ref={removeButton} type="button" className="bk-reader-remove-trigger" onClick={()=>setConfirming(true)} disabled={removing} aria-expanded={confirming} aria-haspopup="dialog">
              <Trash2 size={15} strokeWidth={1.6}/>Remove
            </button>
            {confirming && <div className="bk-reader-remove-popover" role="alertdialog" aria-labelledby="bk-reader-remove-question" aria-busy={removing}>
              <p id="bk-reader-remove-question">Remove this book?</p>
              <div className="bk-reader-remove-choices">
                <button type="button" className="bk-reader-remove-confirm" disabled={removing} onClick={()=>void confirmRemoval()}>{removing?'Removing…':'Remove'}</button>
                <button ref={keepButton} type="button" className="bk-reader-keep" disabled={removing} onClick={cancelRemoval}>Keep</button>
              </div>
            </div>}
          </div>
          <div
            className={cn("flex min-h-0 flex-1 flex-col overflow-hidden")}
            style={{ opacity: contentOpacity }}
          >
            {fullBook ? (
              <BookReader key={fullBook.id} book={fullBook} />
            ) : (
              <div className="flex min-h-0 flex-1 items-center justify-center">
                <p role={loadError ? "alert" : "status"}
                  className="text-[13px] text-neutral-400 dark:text-neutral-500">
                  {loadError || "Opening book…"}
                </p>
              </div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
