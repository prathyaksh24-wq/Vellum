"use client";

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { BriefDocument } from "../lib/brief";
import type { ShelfBookItem } from "../lib/book-types";
import { cn } from "../lib/utils";
import {
  BriefingShelfEngine,
  type BookOpenTransition,
  type SceneThemeName,
  type ShelfMode,
} from "../shelf/BriefingShelfEngine";
import {
  editionForSeed,
  motifForSeed,
  paletteForBrief,
} from "../shelf/brief-cover-art";
import type { ShelfBriefBook } from "../shelf/types";

/** Books per shelf row — mirrors the reference's 7-day weekly rows. */
const BOOKS_PER_ROW = 7;

const EMPTY_ASPECT_MAP: Map<string, number> = new Map();

const MS_PER_DAY = 86_400_000;

function pseudoShelfDate(index: number): string {
  // Newest first: each run of 7 books shares one "week", older rows step back
  // a week at a time — keeps the reference's week-stacked shelf layout.
  const daysAgo = Math.floor(index / BOOKS_PER_ROW) * 7;
  const date = new Date(Date.now() - daysAgo * MS_PER_DAY);
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/** No-cover fallback: slim trade-paperback proportions with slight variation. */
function proceduralCoverWidth(index: number) {
  return 1.14 + ((index % 5) - 2) * 0.018;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

/** Book thickness from real text size — 0.16" pamphlets to 0.23" tomes. */
function thicknessForBook(index: number, contentChars: number) {
  const jitter = ((index * 37) % 5) * 0.0012;
  const size = clamp(contentChars / 1_150_000, 0, 1);
  return 0.16 + size * 0.07 + jitter;
}

function bookDocument(book: ShelfBookItem): BriefDocument {
  return {
    schema_version: 1,
    type: "brief",
    title: book.title,
    description:
      book.author && book.author !== "Unknown" ? `by ${book.author}` : undefined,
    sections: [],
  };
}

function toShelfBook(
  book: ShelfBookItem,
  index: number,
  coverAspect: number | null,
  spotlight = false,
): ShelfBriefBook {
  const document = bookDocument(book);
  const height = 1.78 + (index % 3) * 0.02;
  const shelfDate = pseudoShelfDate(index);
  // Covers with an extracted palette tint the spine/back/boards to match;
  // procedural covers fall back to the reference seeded palettes.
  const procedural = paletteForBrief(shelfDate, index, [], []);
  const palette = {
    cover: book.spineColor || procedural.cover,
    accent: book.accentColor || procedural.accent,
    ink: book.inkColor || procedural.ink,
    titleColor: procedural.titleColor,
  };

  // Real cover images keep their printed aspect ratio; procedural covers
  // fall back to slim trade-paperback proportions.
  const coverPlaneWidth =
    coverAspect && coverAspect > 0
      ? clamp((height - 0.065) * coverAspect + 0.065, 0.95, 1.66)
      : proceduralCoverWidth(index);

  return {
    id: book.id,
    date: shelfDate,
    title: document.title,
    shortTitle: document.title,
    tagline: document.description,
    tools: [],
    agents: [],
    motif: motifForSeed(book.id, []),
    edition: editionForSeed(book.id),
    coverPlaneWidth,
    coverImage: book.coverUrl,
    thickness: thicknessForBook(index, book.contentChars ?? 0),
    height,
    cover: palette.cover,
    accent: palette.accent,
    ink: palette.ink,
    titleColor: palette.titleColor,
    spotlight,
  };
}

export type BriefingBookshelfHandle = {
  browseBy: (direction: number) => void;
  browseTo: (index: number) => void;
  focusBook: (index?: number) => void;
  returnToShelf: () => void;
  resetFocusView: () => void;
};

export type BriefingBookshelfProps = {
  books: ShelfBookItem[];
  activeIndex: number;
  onActiveIndexChange: (index: number) => void;
  onModeChange?: (mode: ShelfMode, selectedIndex: number | null) => void;
  onTransition?: (transition: BookOpenTransition) => void;
  onReady?: () => void;
  spotlightIndex?: number | null;
  /** Dark scene palette — light keeps the reference design untouched. */
  darkMode?: boolean;
  className?: string;
};

/**
 * React wrapper around the Three.js bookshelf engine.
 * Shelves real books with real cover images.
 */
export const BriefingBookshelf = forwardRef<
  BriefingBookshelfHandle,
  BriefingBookshelfProps
>(function BriefingBookshelf(
  {
    books,
    activeIndex,
    onActiveIndexChange,
    onModeChange,
    onTransition,
    onReady,
    spotlightIndex = null,
    darkMode = false,
    className,
  },
  ref,
) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<BriefingShelfEngine | null>(null);
  const onTransitionRef = useRef(onTransition);
  const darkModeRef = useRef(darkMode);
  const [ready, setReady] = useState(false);
  const [mode, setMode] = useState<ShelfMode>("browse");

  useEffect(() => {
    darkModeRef.current = darkMode;
  }, [darkMode]);

  useEffect(() => {
    onTransitionRef.current = onTransition;
  }, [onTransition]);

  const structureKey = useMemo(
    () => books.map((book) => book.id).join(","),
    [books],
  );

  const safeIndex = Math.min(
    Math.max(activeIndex, 0),
    Math.max(books.length - 1, 0),
  );

  // Preload cover images so each volume gets its true aspect ratio.
  const [aspectsState, setAspectsState] = useState<{
    key: string;
    map: Map<string, number>;
  } | null>(null);
  const coverAspects =
    aspectsState && aspectsState.key === structureKey
      ? aspectsState.map
      : EMPTY_ASPECT_MAP;
  // Boot always waits for the full aspect map keyed to this shelf — booting
  // earlier would size every volume with the fallback width and stretch
  // real covers sideways to fill the too-wide plane.
  const coversLoaded =
    books.length === 0 ||
    (aspectsState !== null && aspectsState.key === structureKey);

  useEffect(() => {
    if (books.length === 0) return;
    let cancelled = false;

    void Promise.all(
      books.map(
        (book) =>
          new Promise<[string, number | null]>((resolve) => {
            if (!book.coverUrl) {
              resolve([book.id, null]);
              return;
            }
            // Server already knows the aspect — just warm the image cache.
            if (book.coverAspect && book.coverAspect > 0) {
              resolve([book.id, book.coverAspect]);
              return;
            }
            const image = new Image();
            image.onload = () => {
              resolve([
                book.id,
                image.naturalHeight > 0
                  ? image.naturalWidth / image.naturalHeight
                  : null,
              ]);
            };
            image.onerror = () => resolve([book.id, null]);
            image.src = book.coverUrl;
          })),
    ).then((entries) => {
      if (cancelled) return;
      const next = new Map<string, number>();
      for (const [id, aspect] of entries) {
        if (aspect) next.set(id, aspect);
      }
      setAspectsState({ key: structureKey, map: next });
    });

    return () => {
      cancelled = true;
    };
  }, [books, structureKey]);

  const shelfBooks = useMemo(
    () =>
      books.map((book, index) =>
        toShelfBook(
          book,
          index,
          coverAspects.get(book.id) ?? null,
          spotlightIndex === index,
        ),
      ),
    [books, coverAspects, spotlightIndex],
  );

  const shelfBooksRef = useRef(shelfBooks);
  useEffect(() => {
    shelfBooksRef.current = shelfBooks;
  }, [shelfBooks]);

  const isReading =
    mode === "open" || mode === "focusing" || mode === "returning";

  useImperativeHandle(ref, () => ({
    browseBy: (direction) => engineRef.current?.browseBy(direction),
    browseTo: (index) => engineRef.current?.browseTo(index),
    focusBook: (index) => engineRef.current?.focusBook(index),
    returnToShelf: () => engineRef.current?.returnToShelf(),
    resetFocusView: () => engineRef.current?.resetFocusView(),
  }));

  const bootIndex =
    typeof spotlightIndex === "number" ? spotlightIndex : safeIndex;

  useEffect(() => {
    let cancelled = false;
    let engine: BriefingShelfEngine | null = null;
    // A rebuilt engine starts browsing; clear the old reader's input lock too.
    setMode("browse");

    async function start() {
      if (!canvasRef.current || shelfBooks.length === 0) return;
      if (cancelled || !canvasRef.current || !coversLoaded) return;

      engine = new BriefingShelfEngine(
        canvasRef.current,
        shelfBooksRef.current,
        {
          onActiveIndex: onActiveIndexChange,
          onMode: (nextMode, selectedIndex) => {
            setMode(nextMode);
            onModeChange?.(nextMode, selectedIndex);
          },
          onTransition: (transition) => onTransitionRef.current?.(transition),
          onReady: () => {
            setReady(true);
            onReady?.();
          },
        },
        {
          initialIndex: bootIndex,
          spotlightIndex,
          dark: darkModeRef.current,
        },
      );
      engineRef.current = engine;
    }

    void start();
    return () => {
      cancelled = true;
      engine?.dispose();
      engineRef.current = null;
      setReady(false);
    };
    // structureKey intentionally drives remount when the catalog identity changes;
    // theme changes do NOT reboot — setTheme swaps the room lights live.
  }, [
    bootIndex,
    coversLoaded,
    onActiveIndexChange,
    onModeChange,
    onReady,
    spotlightIndex,
    structureKey,
  ]);

  useEffect(() => {
    engineRef.current?.updateBooks(shelfBooks);
    engineRef.current?.setSpotlightIndex(
      typeof spotlightIndex === "number" ? spotlightIndex : null,
    );
  }, [shelfBooks, spotlightIndex]);

  // Live light switch — the engine swaps scene/fog/lights without a reboot.
  useEffect(() => {
    const theme: SceneThemeName = darkMode ? "dark" : "light";
    engineRef.current?.setTheme(theme);
    engineRef.current?.matchVellumBackground();
  }, [darkMode, ready]);

  useEffect(() => {
    if(!ready) return;
    const observer=new MutationObserver(()=>engineRef.current?.matchVellumBackground());
    observer.observe(document.documentElement,{attributes:true,attributeFilter:['style','data-theme','data-background']});
    return()=>observer.disconnect();
  },[ready]);

  if (books.length === 0) return null;

  return (
    <div
      className={cn(
        "relative isolate h-full min-h-0 w-full overflow-hidden bg-[#f2eee6] dark:bg-[#161210]",
        ready && "is-ready",
        isReading && "is-focused",
        className,
      )}
    >
      <canvas
        ref={canvasRef}
        tabIndex={0}
        aria-label="3D bookshelf of books"
        className={cn(
          "absolute inset-0 block h-full w-full touch-none outline-none transition-opacity duration-200",
          ready ? "opacity-100" : "opacity-0",
          isReading && "pointer-events-none",
          !isReading && ready ? "cursor-grab" : "",
        )}
      />

      {!ready ? (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center text-[13px] text-neutral-400">
          Loading shelf…
        </div>
      ) : null}

      <button
        type="button"
        aria-label="Previous book"
        disabled={safeIndex <= 0 || isReading}
        onClick={() => engineRef.current?.browseBy(-1)}
        className={cn(
          "absolute top-1/2 left-3 z-[17] flex size-9 -translate-y-1/2 cursor-pointer items-center justify-center text-neutral-400 transition-opacity hover:text-neutral-700 disabled:opacity-0 md:left-5 dark:text-neutral-500 dark:hover:text-neutral-200",
          isReading && "pointer-events-none opacity-0",
        )}
      >
        <ChevronLeft className="size-5" strokeWidth={1.6} />
      </button>
      <button
        type="button"
        aria-label="Next book"
        disabled={safeIndex >= books.length - 1 || isReading}
        onClick={() => engineRef.current?.browseBy(1)}
        className={cn(
          "absolute top-1/2 right-3 z-[17] flex size-9 -translate-y-1/2 cursor-pointer items-center justify-center text-neutral-400 transition-opacity hover:text-neutral-700 disabled:opacity-0 md:right-5 dark:text-neutral-500 dark:hover:text-neutral-200",
          isReading && "pointer-events-none opacity-0",
        )}
      >
        <ChevronRight className="size-5" strokeWidth={1.6} />
      </button>
    </div>
  );
});
