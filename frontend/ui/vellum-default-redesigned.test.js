import { describe, expect, test } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(resolve(here, "../../design/Velllum/uploads/Vellum Default Re-designed.html"), "utf8");
const selectComponent = readFileSync(
  resolve(here, "../../design/Velllum/uploads/components/v-select.jsx"),
  "utf8",
);
const booksView = readFileSync(
  resolve(here, "../../design/Velllum/uploads/components/books-view.jsx"),
  "utf8",
);

describe("Vellum default redesigned frontend", () => {
  test("connects the Books view through separate API, state, presentation and bundled graphics", () => {
    expect(html).toContain('<script src="api/books.js"></script>');
    expect(html).toContain('<script src="components/books-state.js"></script>');
    expect(html).toContain('src="components/books-view.jsx"');
    expect(html).toContain('src="/books-entry.js"');
    expect(html).toContain("DefaultAgentView={DefaultAgentView}");
    expect(html).toContain("bookDraft.text");
    expect(html).not.toContain("IcArrowLeft");
  });

  test("routes composer EPUBs through the canonical Book-to-Skill import", () => {
    expect(booksView).toContain("BooksImportDialog:ImportDialog");
    expect(html).toContain("API.books.importEpub(file, consent)");
    expect(html).toContain("book_import_id:result.book.id");
    expect(html).toContain("result.book?.skill_status !== 'compiled'");
    expect(html).toContain("const regularFiles = files.filter(file => !isEpubFile(file))");
    expect(html).not.toContain("reader.readAsDataURL(epub)");
  });

  test("loads the modular frontend API bridge used by backend integrations", () => {
    expect(html).toMatch(/<script src="api\/client\.js(?:\?[^\"]+)?"><\/script>/);
    expect(html).toContain('<script src="api/chat.js"></script>');
    expect(html).toContain('<script src="api/app-actions.js"></script>');
    expect(html).toContain('<script src="components/app-action-runtime.js"></script>');
    expect(html).toContain('<script src="api/conversations.js"></script>');
    expect(html).toContain('<script src="api/plugins.js"></script>');
    expect(html).toMatch(/<script src="api\/settings\.js(?:\?[^\"]+)?"><\/script>/);
    expect(html).toMatch(/<script src="api\/knowledge\.js(?:\?[^\"]+)?"><\/script>/);
    expect(html).toContain('<script src="api/runtimes.js"></script>');
  });

  test("routes submitted NLP and sidebar controls through App Action receipts", () => {
    expect(html).toContain("action_context: workspaceActionRuntimeRef.current.context('nlp', chatId)");
    expect(html).toContain("actionReceipt: receipt =>");
    expect(html).toContain("workspaceActionRuntimeRef.current.applyReceipt(receipt)");
    expect(html).toContain("onTogglePin={() => dispatchSidebarVisibility(!sidebarPinned)}");
    expect(html).toContain("onExpand={() => dispatchSidebarVisibility(true)}");
    expect(html).toContain("className=\"toast-action\"");
    expect(html).not.toContain("setSidebarPinned");
  });

  test("loads the shared select component outside the application shell", () => {
    expect(html).toContain('src="components/v-select.jsx"');
    expect(html).toContain("const VSelect = window.VellumUI.VSelect");
    expect(html).not.toContain("const normalizeSelectOptions");
    expect(selectComponent).toContain("window.VellumUI");
    expect(selectComponent).toContain('role="combobox"');
    expect(selectComponent).toContain('role="listbox"');
    expect(selectComponent).toContain('event.key === "ArrowDown"');
  });

  test("keeps the approved web UI shell instead of the old desktop chrome", () => {
    expect(html).toContain("galaxy-container");
    expect(html).toContain("AppBackground");
    expect(html).toContain("dock-layer");
    expect(html).toContain("Show dock");
    expect(html).toContain("Dock position");
    expect(html).not.toContain('class="titlebar"');
  });

  test("includes Spotify plugin controls and player API integration", () => {
    expect(html).toContain("const SpotifyAPI");
    expect(html).toContain("/api/plugins/spotify/status");
    expect(html).toContain("/api/plugins/spotify/oauth/start");
    expect(html).toContain("/api/plugins/spotify/player/action");
    expect(html).toContain("SpotifyPlayer");
  });

  test("uses backend-owned YouTube OAuth without collecting credentials in the UI", () => {
    expect(html).toContain("const YouTubeAPI");
    expect(html).toContain("YouTubeAPI.intelligenceStatus()");
    expect(html).toContain("API.plugins.youtubeOAuthStart()");
    expect(html).toContain("API.plugins.youtubeSync");
    expect(html).toContain("API.plugins.youtubeDisconnect()");
    expect(html).not.toContain("clientSecret");
    expect(html).not.toContain("Email or phone");
    expect(html).not.toContain("Manage videos and drafts on your behalf");
  });

  test("installs Discord through the backend-owned bot authorization contract", () => {
    expect(html).toContain("API.plugins.discordInstall()");
    expect(html).toContain("vellum-discord-install");
    expect(html).toContain("Install bot");
    expect(html).not.toContain("DISCORD_BOT_TOKEN");
  });

  test("keeps model selection request-scoped and persisted with conversations", () => {
    for (const id of [
      "openai/gpt-5.6-sol",
      "openai/gpt-5.6-terra",
      "openai/gpt-5.6-luna",
      "anthropic/claude-opus-5",
      "moonshotai/kimi-k3",
      "deepseek/deepseek-v4-flash-0731",
    ]) {
      expect(html).toContain(id);
    }
    expect(html).toContain("model: turnModel");
    expect(html).toContain("model: modelId");
    expect(html).toContain("chat.model || selModel");
    expect(html).toContain("MODEL_PROVIDER_FILTERS");
    expect(html).toContain("modelFamily");
    expect(html).toContain("label: 'OpenAI'");
    expect(html).toContain("label: 'Claude'");
    expect(html).toContain("updateChat(activeChatId, chat => ({...chat, model: id}), true)");
    expect(html).not.toContain("API.settings.setActiveModel(id)");
  });

  test("does not contain unresolved Git conflict markers", () => {
    expect(html).not.toMatch(/^(<<<<<<<|=======|>>>>>>>)/m);
  });

  test("includes routing, OpenRouter, memory, and Hermes-compatible plugin surfaces", () => {
    expect(html).toContain("OpenRouter");
    expect(html).toContain("Provider routing, fallback models, and credential pools");
    expect(html).toContain("memoryDreamingRun");
    expect(html).toContain("Portable plugins are loaded through Vellum's Hermes-compatible");
    expect(html).toContain("API.runtimes.subagents()");
  });

  test("uses one live memory state and supports Vault or wiki chat context", () => {
    expect(html).toContain("<MemoryConsole page memoryData={memoryData} onRefresh={refreshMemoryData}");
    expect(html).toContain("Array.isArray(summary.sections)");
    expect(html).toContain("API.knowledge.search(value, scope, 20)");
    expect(html).toContain("New chat with context");
    expect(html).toContain("API.conversations.attachContext");
  });
});
