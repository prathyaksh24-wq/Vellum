import { describe, expect, test, vi } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(resolve(here, "../../design/Velllum/uploads/Vellum Default Re-designed.html"), "utf8");
const api = readFileSync(resolve(here, "../../design/Velllum/uploads/api/conversations.js"), "utf8");

describe("conversation library frontend", () => {
  test("exposes full/summary library and encoded message-search reads", async () => {
    const request=vi.fn(async()=>({}));
    const host={VellumApi:{client:{request,jsonOptions:(method,body)=>({method,body})}}};
    new Function("window",api)(host);
    await host.VellumApi.conversations.library();
    await host.VellumApi.conversations.library({includeMessages:false});
    await host.VellumApi.conversations.search("black holes",{space:"Research & notes"});
    await host.VellumApi.conversations.organize("chat/a",{assignment:"automatic"});
    await host.VellumApi.conversations.rebuildOrganization();
    expect(request.mock.calls.map(([url])=>url)).toEqual([
      "/api/conversations/library", "/api/conversations/library?include_messages=false",
      "/api/conversations/search?q=black+holes&space=Research+%26+notes",
      "/api/conversations/chat%2Fa/organization", "/api/conversations/organization/rebuild",
    ]);
  });

  test("projects include assigned chats while Recents can filter them separately", () => {
    const sidebar=html.slice(html.indexOf('const Sidebar ='),html.indexOf('const RailFly ='));
    expect(sidebar.includes('chats.filter(chat=>!chat.archived)')).toBe(true);
    expect(sidebar.includes('sorted.filter(chat=>chat.projectId===project.id).map(row)')).toBe(true);
    expect(sidebar.includes('<SidebarSection id="projects"')).toBe(true);
    expect(sidebar.includes('<SidebarSection id="recents"')).toBe(true);
    expect(sidebar.includes('recentFilter')).toBe(true);
    expect(sidebar.includes('onProjectNewChat(project.id)')).toBe(true);
    expect(sidebar.includes('onMoveToProject(id,project.id)')).toBe(true);
  });

  test("sections retain saved disclosure state and make collapsed controls inert", () => {
    expect(html.includes('aria-expanded={open} aria-controls={regionId}')).toBe(true);
    expect(html.includes('aria-hidden={!open} inert={!open}')).toBe(true);
    expect(html.includes('.sb-section-collapse{display:grid;grid-template-rows:0fr')).toBe(true);
    expect(html.includes('.sb-section-collapse.open{grid-template-rows:1fr')).toBe(true);
    expect(html.includes('recents:true')).toBe(true);
    expect(html.includes("'vellum-sidebar-sections'")).toBe(true);
    expect(html.includes('JSON.stringify(secOpen)')).toBe(true);
  });

  test("searches message content and uses the shared message-focus helper", () => {
    expect(html.includes('API.conversations.search(q, filters)')).toBe(true);
    expect(html.includes('hits[0].message_id')).toBe(true);
    expect(html.includes('scrollToConversationMessage(messageId)')).toBe(true);
    expect(html.includes('Search titles and messages')).toBe(true);
  });

  test("supports durable manual Space corrections and automatic reset", () => {
    expect(html).toContain("const SpacePickerModal");
    expect(html).toContain("dispatchConversationAction('conversation.space.set'");
    expect(html).toContain("assignment: 'manual'");
    expect(html).toContain("assignment: 'automatic'");
  });

  test("routes conversation controls and chat receipts through one App Action runtime", () => {
    expect(html).toContain("createConversationActionRuntime");
    expect(html).toContain("'conversation.unpin' : 'conversation.pin'");
    expect(html).toContain("dispatchConversationAction('conversation.archive'");
    expect(html).toContain("dispatchConversationAction('conversation.delete'");
    expect(html).toContain("conversationActionRuntimeRef.current.applyReceipt(receipt)");
    expect(html).toContain("conversationActionRuntimeRef.current.rememberRequest(request)");
  });

  test("does not replace optimistic chats when initial backend hydration finishes late", () => {
    expect(html).toContain("const mergeConversationRecords = (current, serverConversations) =>");
    expect(html).toContain("const localOnly = current.filter(chat => !serverIds.has(chat.id));");
    expect(html).toContain("setChats(current => mergeConversationRecords(current, conversationData.conversations));");
    expect(html).not.toContain("setChats(conversationData.conversations);");
  });
});
