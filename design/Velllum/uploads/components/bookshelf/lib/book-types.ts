/** Book item as returned by GET /api/books (no content payload). */
export type ShelfBookItem = {
  id: string;
  title: string;
  author: string;
  source: string;
  gutenbergId: number | null;
  hasCover: boolean;
  /** Same-origin cover URL for WebGL textures / <img>. */
  coverUrl: string | null;
  /** Server-side width/height of the real cover (null when procedural). */
  coverAspect: number | null;
  /** Palette extracted from the real cover — drives spine/back/boards. */
  spineColor: string;
  accentColor: string;
  inkColor: string;
  contentChars: number;
  /** 0..1 reading progress. */
  progress: number;
  dateAdded: string;
};

/** Full book as returned by GET /api/books/[id] (includes content). */
export type FullBook = ShelfBookItem & {
  content: string;
};
