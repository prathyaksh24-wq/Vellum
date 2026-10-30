/** One briefing volume on the 3D shelf. */
export type ShelfBriefBook = {
  id: string;
  date: string;
  title: string;
  shortTitle: string;
  tagline?: string;
  tools?: string[];
  agents?: Array<
    import("./brief-cover-meta").CoverAgent & {
      portrait?: HTMLImageElement | null;
      brandLogo?: HTMLImageElement | null;
    }
  >;
  motif?: import("./brief-cover-meta").BriefCoverMotif;
  edition?: import("./brief-cover-art").CoverEdition;
  /** Cover width in scene units — must match BriefingShelfEngine geometry. */
  coverPlaneWidth: number;
  /** Optional cover image URL — future user-controlled artwork. */
  coverImage?: string | null;
  thickness: number;
  height: number;
  cover: string;
  accent: string;
  ink: string;
  titleColor?: string;
  /** Today's volume — stronger idle shimmer / light pool while browsing. */
  spotlight?: boolean;
};
