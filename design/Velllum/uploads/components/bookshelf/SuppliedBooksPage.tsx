"use client";

import {createPortal} from "react-dom";
import {useBookRuntime} from "./VellumRuntime";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTheme } from "./VellumRuntime";
import { BookPlus, Moon, Sun } from "lucide-react";
import {toast} from "sonner";
import {
  BriefingBookshelf,
  type BriefingBookshelfHandle,
} from "./components/BriefingBookshelf";
import { BriefingOpenOverlay } from "./components/BriefingOpenOverlay";
import { ImportBooksDialog } from "./components/ImportBooksDialog";
import type { ShelfBookItem } from "./lib/book-types";
import type {
  BookOpenTransition,
  ShelfMode,
} from "./shelf/BriefingShelfEngine";

/**
 * 3D bookshelf of real books: scroll/drag to browse, click a volume to read
 * it fullscreen, and import your own books onto the shelves.
 */
export default function Page() {
  const runtime=useBookRuntime();
  const stageRef=useRef<HTMLDivElement>(null);
  const shelfRef = useRef<BriefingBookshelfHandle>(null);
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const books=runtime.books;
  const booksLoading=runtime.loading;
  const currentBooks=useRef(books);currentBooks.current=books;
  const handleActiveIndex=useCallback((index:number)=>{setActiveIndex(index);const book=currentBooks.current[index];if(book)runtime.onSelect(book.id);},[]);
  const [activeIndex, setActiveIndex] = useState(0);
  const [mode, setMode] = useState<ShelfMode>("browse");
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const [transition, setTransition] = useState<BookOpenTransition | null>(null);
  const [importOpen, setImportOpen] = useState(false);

  useEffect(() => setMounted(true), []);
  const darkMode = mounted && resolvedTheme === "dark";

  const loadBooks = useCallback(() => runtime.refresh(), [runtime.refresh]);
  const handleTransition=useCallback((next:BookOpenTransition) => {
    const rect=stageRef.current?.getBoundingClientRect();
    setTransition({...next,readerRect:next.readerRect && rect ? {...next.readerRect,x:next.readerRect.x+rect.left,y:next.readerRect.y+rect.top}:next.readerRect,viewport:{width:window.innerWidth,height:window.innerHeight}});
  },[]);
  const [ready,setReady]=useState(false);
  const handleReady=useCallback(()=>setReady(true),[]);
  const openedRequest=useRef('');
  useEffect(()=>{if(!runtime.openBookId){openedRequest.current='';return;}if(!ready || openedRequest.current===runtime.openBookId)return;const index=books.findIndex(book=>book.id===runtime.openBookId);if(index>=0){openedRequest.current=runtime.openBookId;shelfRef.current?.focusBook(index);}},[runtime.openBookId,books,ready]);

  // When the shelf composition changes (import), drop any stale reader state.
  const shelfIdentity = books.map((book) => book.id).join(",");
  useEffect(() => {
    setMode("browse");
    setOpenIndex(null);
    setTransition(null);
  }, [shelfIdentity]);

  const handleImported = useCallback(() => {
    void loadBooks().then(() => {
      setActiveIndex(0);
      // Give the engine a beat to rebuild, then present the new arrival.
      window.setTimeout(() => shelfRef.current?.browseTo(0), 120);
    });
  }, [loadBooks]);

  const contentIndex = openIndex ?? activeIndex;
  const activeBook = books[contentIndex] ?? null;
  const isReading = mode === "open" || mode === "focusing" || mode === "returning";

  const handleModeChange = useCallback(
    (nextMode: ShelfMode, selected: number | null) => {
      setMode(nextMode);
      if (nextMode === "open" && selected !== null) {
        setOpenIndex(selected);
      }
      if (nextMode === "browse") {
        runtime.onClose();
        setOpenIndex(null);
        setTransition(null);
      }
    },
    [],
  );

  const handleBack = useCallback(() => {
    shelfRef.current?.returnToShelf();
  }, []);
  const handleRemove = async (id:string) => {
    await runtime.removeBook(id);
    setMode("browse");setOpenIndex(null);setTransition(null);setActiveIndex(0);
    runtime.onClose();
    toast.success("Book removed from shelf");
  };

  return (
    <div ref={stageRef} className="bk-supplied-page relative flex h-full min-h-0 w-full flex-col overflow-hidden">
      <header className="pointer-events-none absolute inset-x-0 top-0 z-20 flex items-center justify-end gap-2 p-5 md:p-7">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setImportOpen(true)}
            className="pointer-events-auto flex cursor-pointer items-center gap-1.5 rounded-full bg-white/80 px-3 py-1.5 text-[12px] font-medium text-neutral-700 shadow-sm backdrop-blur transition hover:bg-white hover:text-neutral-950 dark:bg-white/10 dark:text-neutral-200 dark:hover:bg-white/15 dark:hover:text-white"
          >
            <BookPlus className="size-3.5" strokeWidth={1.8} />
            Import
          </button>
          <button
            type="button"
            onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
            aria-label={darkMode ? "Switch to light mode" : "Switch to dark mode"}
            className="pointer-events-auto flex size-[30px] cursor-pointer items-center justify-center rounded-full bg-white/80 text-neutral-700 shadow-sm backdrop-blur transition hover:bg-white hover:text-neutral-950 dark:bg-white/10 dark:text-neutral-200 dark:hover:bg-white/15 dark:hover:text-white"
          >
            {mounted && darkMode ? (
              <Sun className="size-3.5" strokeWidth={1.8} />
            ) : (
              <Moon className="size-3.5" strokeWidth={1.8} />
            )}
          </button>
        </div>
      </header>

      {booksLoading ? (
        <div className="absolute inset-0 z-10 flex items-center justify-center text-[13px] text-neutral-400 dark:text-neutral-500">
          Loading shelf…
        </div>
      ) : books.length === 0 ? (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-4 px-6 text-center">
          <p className="font-serif text-[1.15rem] italic text-neutral-500 dark:text-neutral-400">
            Your shelf is empty.
          </p>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setImportOpen(true)}
              className="cursor-pointer rounded-full bg-neutral-900 px-4 py-2 text-[13px] font-medium text-white transition hover:bg-neutral-700 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300"
            >
              Import a book
            </button>
          </div>
        </div>
      ) : (
        <BriefingBookshelf
          ref={shelfRef}
          books={books}
          activeIndex={activeIndex}
          onActiveIndexChange={handleActiveIndex}
          onModeChange={handleModeChange}
          onTransition={handleTransition}
          onReady={handleReady}
          spotlightIndex={0}
          darkMode={darkMode}
          className="absolute inset-0"
        />
      )}

      {activeBook && isReading ? createPortal(
        <div className="bk-reference bk-reference-reader" role="dialog" aria-modal="true" aria-label={`Read ${activeBook.title}`}><BriefingOpenOverlay
          mode={mode}
          transition={transition}
          book={activeBook}
          onBack={handleBack}
          onRemove={handleRemove}
        /></div>,document.body
      ) : null}

      <ImportBooksDialog
        open={importOpen}
        onOpenChange={setImportOpen}
        onImported={handleImported}
      />
    </div>
  );
}
