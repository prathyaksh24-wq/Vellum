"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, List } from "lucide-react";
import { toast } from "sonner";
import type { FullBook } from "../lib/book-types";
import { splitBookIntoChapters } from "../lib/book-text";
import { cn } from "../lib/utils";

import {useBookRuntime} from "../VellumRuntime";

function clampIndex(value: number, length: number) {
  return Math.min(Math.max(value, 0), Math.max(length - 1, 0));
}

const FONT_SIZES = [
  { key: "s", label: "A", px: 15 },
  { key: "m", label: "A", px: 16.5 },
  { key: "l", label: "A", px: 18.5 },
] as const;
const FONT_STORAGE_KEY = "bookshelf.reader.fontSize";

/**
 * Fullscreen reader for an entire book — chapter navigation, table of
 * contents, reading progress that is saved and restored, and adjustable
 * type size. Typography mirrors the demo brief reader.
 */
export function BookReader({ book }: { book: FullBook }) {
  const runtime=useBookRuntime();
  const chapters = useMemo(
    () => splitBookIntoChapters(book.content ?? ""),
    [book.content],
  );
  const saved = book.progress ?? 0;
  const [chapterIndex, setChapterIndex] = useState(() =>
    saved > 0.005 && chapters.length > 1
      ? clampIndex(Math.floor(saved * chapters.length), chapters.length)
      : 0,
  );
  const [tocOpen, setTocOpen] = useState(false);
  const [chapterProgress, setChapterProgress] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const restoredRef = useRef(false);
  const initialChapterRef = useRef(true);
  const progressSaveTimer = useRef<number | null>(null);
  const lastSavedRef = useRef(0);

  const [fontPx, setFontPx] = useState(() => {
    if (typeof window === "undefined") return 16.5;
    try {
      const stored = window.localStorage.getItem(FONT_STORAGE_KEY);
      const match = FONT_SIZES.find((size) => String(size.px) === stored);
      return match ? match.px : 16.5;
    } catch {
      return 16.5;
    }
  });

  const chapter = chapters[chapterIndex] ?? chapters[0];
  const hasMultipleChapters = chapters.length > 1;

  // Resume where the reader left off (once, after first layout).
  useEffect(() => {
    if (restoredRef.current) return;
    restoredRef.current = true;
    if (saved <= 0.005) return;
    const frame = requestAnimationFrame(() => {
      const element = scrollRef.current;
      if (!element) return;
      const fraction = (saved * chapters.length) % 1;
      const max = element.scrollHeight - element.clientHeight;
      element.scrollTo({ top: Math.max(0, fraction * max) });
      setChapterProgress(max > 24 ? fraction : 1);
      if (hasMultipleChapters) {
        toast("Continuing where you left off", {
          description: `Chapter ${chapterIndex + 1} of ${chapters.length}`,
          duration: 2600,
        });
      }
    });
    return () => cancelAnimationFrame(frame);
  }, []);

  // Persist progress as the reader moves through the book.
  const saveProgress = (value: number) => {
    if (value <= 0.001 || Math.abs(value - lastSavedRef.current) < 0.01) return;
    lastSavedRef.current = value;
    if (progressSaveTimer.current) {
      window.clearTimeout(progressSaveTimer.current);
    }
    progressSaveTimer.current = window.setTimeout(() => {
      void runtime.saveProgress(book.id,value).catch(() => toast.error('Reading position could not be saved.'));
    }, 1200);
  };

  useEffect(() => {
    return () => {
      if (progressSaveTimer.current) {
        window.clearTimeout(progressSaveTimer.current);
      }
    };
  }, []);

  useEffect(() => {
    // The initial chapter effect must not overwrite the saved position restored
    // above in the same animation frame. Later chapter changes still start at 0.
    if (initialChapterRef.current) {
      initialChapterRef.current = false;
      if (saved > 0.005) return;
    }
    const frame = requestAnimationFrame(() => {
      const element = scrollRef.current;
      if (!element) return;
      element.scrollTo({ top: 0 });
      const max = element.scrollHeight - element.clientHeight;
      setChapterProgress(max > 24 ? element.scrollTop / max : 1);
    });
    return () => cancelAnimationFrame(frame);
  }, [chapterIndex]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "ArrowRight" && chapterIndex < chapters.length - 1) {
        event.preventDefault();
        setChapterIndex((current) => clampIndex(current + 1, chapters.length));
      }
      if (event.key === "ArrowLeft" && chapterIndex > 0) {
        event.preventDefault();
        setChapterIndex((current) => clampIndex(current - 1, chapters.length));
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [chapterIndex, chapters.length]);

  const onScroll = () => {
    const element = scrollRef.current;
    if (!element) return;
    const max = element.scrollHeight - element.clientHeight;
    const progress = max > 24 ? element.scrollTop / max : 1;
    setChapterProgress(progress);
    saveProgress((chapterIndex + progress) / Math.max(chapters.length, 1));
  };

  const overallProgress =
    chapters.length > 0
      ? (chapterIndex + chapterProgress) / chapters.length
      : 0;

  const sourceLabel =
    book.source === "gutenberg"
      ? "Project Gutenberg"
      : book.source === "url"
        ? "Imported from URL"
        : book.source === "upload"
          ? "Imported book"
          : "Imported book";

  const wordsInBook = useMemo(
    () => book.content.split(/\s+/).filter(Boolean).length,
    [book.content],
  );

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      {/* Slim book progress bar */}
      <div
        className="pointer-events-none absolute inset-x-0 top-0 z-10 h-[3px] bg-neutral-100 dark:bg-white/10"
        aria-hidden
      >
        <div
          className="h-full bg-neutral-800/70 transition-[width] duration-150 dark:bg-neutral-200/80"
          style={{ width: `${Math.round(overallProgress * 100)}%` }}
        />
      </div>

      {book.content ? (
        <>
          {/* Chapter toolbar */}
          {hasMultipleChapters ? (
            <div className="flex items-center justify-center gap-2 border-b border-neutral-100 px-4 pb-3 pt-4 dark:border-white/10">
              <button
                type="button"
                aria-label="Previous chapter"
                disabled={chapterIndex <= 0}
                onClick={() => setChapterIndex((c) => clampIndex(c - 1, chapters.length))}
                className="flex size-8 cursor-pointer items-center justify-center rounded-full text-neutral-500 transition-colors hover:bg-neutral-100 hover:text-neutral-900 disabled:cursor-default disabled:opacity-30 disabled:hover:bg-transparent dark:text-neutral-400 dark:hover:bg-white/10 dark:hover:text-neutral-100"
              >
                <ChevronLeft className="size-4" strokeWidth={1.8} />
              </button>
              <div className="flex min-w-0 items-center gap-1">
                <span className="max-w-[46vw] truncate font-serif text-[14px] italic text-neutral-600 sm:max-w-[420px] dark:text-neutral-300">
                  {chapter?.title ?? "Full text"}
                </span>
                <span className="shrink-0 text-[12px] tabular-nums text-neutral-400 dark:text-neutral-500">
                  · {chapterIndex + 1}/{chapters.length}
                </span>
              </div>
              <button
                type="button"
                aria-label="Next chapter"
                disabled={chapterIndex >= chapters.length - 1}
                onClick={() => setChapterIndex((c) => clampIndex(c + 1, chapters.length))}
                className="flex size-8 cursor-pointer items-center justify-center rounded-full text-neutral-500 transition-colors hover:bg-neutral-100 hover:text-neutral-900 disabled:cursor-default disabled:opacity-30 disabled:hover:bg-transparent dark:text-neutral-400 dark:hover:bg-white/10 dark:hover:text-neutral-100"
              >
                <ChevronRight className="size-4" strokeWidth={1.8} />
              </button>
              <button
                type="button"
                aria-label="Table of contents"
                onClick={() => setTocOpen((open) => !open)}
                className={cn(
                  "ml-1 flex size-8 cursor-pointer items-center justify-center rounded-full text-neutral-500 transition-colors hover:bg-neutral-100 hover:text-neutral-900 dark:text-neutral-400 dark:hover:bg-white/10 dark:hover:text-neutral-100",
                  tocOpen && "bg-neutral-100 text-neutral-900 dark:bg-white/10 dark:text-neutral-100",
                )}
              >
                <List className="size-4" strokeWidth={1.8} />
              </button>
              <div className="ml-1 flex items-center gap-0.5">
                {FONT_SIZES.map((size) => (
                  <button
                    key={size.key}
                    type="button"
                    aria-label={`Text size ${size.key.toUpperCase()}`}
                    onClick={() => {
                      setFontPx(size.px);
                      try {
                        window.localStorage.setItem(FONT_STORAGE_KEY, String(size.px));
                      } catch {
                        // ignore storage failures
                      }
                    }}
                    style={{ fontSize: `${9 + (size.key === "s" ? 0 : size.key === "m" ? 1.5 : 3)}px` }}
                    className={cn(
                      "flex h-8 w-7 cursor-pointer items-center justify-center rounded-full font-serif transition-colors hover:bg-neutral-100 hover:text-neutral-900 dark:hover:bg-white/10 dark:hover:text-neutral-100",
                      fontPx === size.px
                        ? "bg-neutral-100 text-neutral-900 dark:bg-white/10 dark:text-neutral-100"
                        : "text-neutral-500 dark:text-neutral-400",
                    )}
                  >
                    {size.label}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {/* Table of contents */}
          {hasMultipleChapters && tocOpen ? (
            <nav
              aria-label="Table of contents"
              className="max-h-56 overflow-y-auto border-b border-neutral-100 bg-neutral-50/60 px-4 py-3 dark:border-white/10 dark:bg-white/[0.04]"
            >
              <ol className="mx-auto grid max-w-2xl gap-0.5">
                {chapters.map((entry, index) => (
                  <li key={`${entry.title}-${index}`}>
                    <button
                      type="button"
                      onClick={() => {
                        setChapterIndex(index);
                        setTocOpen(false);
                      }}
                      className={cn(
                        "w-full cursor-pointer truncate rounded-md px-3 py-1.5 text-left text-[13.5px] transition-colors hover:bg-neutral-200/50 dark:hover:bg-white/10",
                        index === chapterIndex
                          ? "font-medium text-neutral-900 dark:text-neutral-100"
                          : "text-neutral-500 dark:text-neutral-400",
                      )}
                    >
                      <span className="mr-2 tabular-nums text-neutral-400 dark:text-neutral-500">
                        {index + 1}.
                      </span>
                      {entry.title}
                    </button>
                  </li>
                ))}
              </ol>
            </nav>
          ) : null}

          {/* Book content */}
          <div
            ref={scrollRef}
            onScroll={onScroll}
            className="min-h-0 flex-1 overflow-y-auto"
          >
            <article className="mx-auto max-w-2xl px-6 pb-24 pt-2 md:px-10">
              <header className="mb-10">
                <p className="text-[12px] font-medium uppercase tracking-[0.14em] text-neutral-400 dark:text-neutral-500">
                  {sourceLabel}
                </p>
                <h1 className="mt-2 font-serif text-[clamp(1.85rem,4vw,2.6rem)] font-semibold leading-[1.15] tracking-[-0.03em] text-neutral-900 dark:text-neutral-100">
                  {book.title}
                </h1>
                {book.author && book.author !== "Unknown" ? (
                  <p className="mt-2 font-serif text-[15px] italic text-neutral-500 dark:text-neutral-400">
                    by {book.author}
                  </p>
                ) : null}
                <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-neutral-400 dark:text-neutral-500">
                  <span>{wordsInBook.toLocaleString()} words</span>
                  {hasMultipleChapters ? (
                    <span>· {chapters.length} chapters</span>
                  ) : null}
                </div>
                {book.coverUrl ? (
                  <img
                    src={book.coverUrl}
                    alt={`Cover of ${book.title}`}
                    className="mt-6 w-28 rounded-md border border-neutral-200/70 shadow-[0_10px_28px_rgba(0,0,0,0.14)] dark:border-white/15 dark:shadow-[0_10px_28px_rgba(0,0,0,0.5)]"
                  />
                ) : null}
              </header>

              <div className="space-y-10">
                {hasMultipleChapters ? (
                  <section>
                    <h2 className="mb-4 font-serif text-[1.35rem] italic text-neutral-900 dark:text-neutral-100">
                      {chapter?.title}
                    </h2>
                    <div className="space-y-5">
                      {(chapter?.paragraphs ?? []).map((paragraph, index) => (
                        <p
                          key={index}
                          style={{ fontSize: `${fontPx}px` }}
                          className="leading-[1.78] text-neutral-700 dark:text-neutral-300"
                        >
                          {paragraph}
                        </p>
                      ))}
                    </div>
                  </section>
                ) : (
                  <div className="space-y-5">
                    {(chapter?.paragraphs ?? []).map((paragraph, index) => (
                      <p
                        key={index}
                        style={{ fontSize: `${fontPx}px` }}
                        className="leading-[1.78] text-neutral-700 dark:text-neutral-300"
                      >
                        {paragraph}
                      </p>
                    ))}
                  </div>
                )}
              </div>

              {hasMultipleChapters ? (
                <div className="mt-14 flex items-center justify-between border-t border-neutral-100 pt-6 dark:border-white/10">
                  <button
                    type="button"
                    disabled={chapterIndex <= 0}
                    onClick={() => setChapterIndex((c) => clampIndex(c - 1, chapters.length))}
                    className="cursor-pointer font-serif text-[14px] italic text-neutral-500 transition-colors hover:text-neutral-900 disabled:opacity-0 dark:text-neutral-400 dark:hover:text-neutral-100"
                  >
                    ← Previous chapter
                  </button>
                  <button
                    type="button"
                    disabled={chapterIndex >= chapters.length - 1}
                    onClick={() => setChapterIndex((c) => clampIndex(c + 1, chapters.length))}
                    className="cursor-pointer font-serif text-[14px] italic text-neutral-500 transition-colors hover:text-neutral-900 disabled:opacity-0 dark:text-neutral-400 dark:hover:text-neutral-100"
                  >
                    Next chapter →
                  </button>
                </div>
              ) : null}
            </article>
          </div>
        </>
      ) : (
        <div className="flex min-h-0 flex-1 items-center justify-center">
          <p className="animate-pulse text-[13px] text-neutral-400 dark:text-neutral-500">
            Opening book…
          </p>
        </div>
      )}
    </div>
  );
}
