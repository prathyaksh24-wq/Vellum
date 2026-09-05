import { beforeEach, describe, expect, test, vi } from "vitest";

async function loadRuntime() {
  vi.resetModules();
  window.VellumUI = {};
  window.VellumApi = { appActions: {} };
  await import("../../design/Velllum/uploads/components/app-action-runtime.js");
  return window.VellumUI.AppActions;
}

function actionReceipt({ actionId, source = "ui", conversation, status = "applied", confirmation = null, deleted = false, navigation = null }) {
  return {
    receipt_id: "receipt-1",
    request_id: "request-1",
    action_id: actionId,
    action_version: "1",
    source,
    status,
    authorization: { decision: "allowed", access_class: "write", confirmation_required: status === "confirmation_required", agent_name: source === "ui" ? "VellumUI" : "VellumAgent" },
    target: { kind: "conversation", id: conversation && conversation.id || "new", revision: conversation && conversation.revision || 0 },
    result: {
      changed: true,
      ...(conversation ? { conversation } : {}),
      ...(deleted ? { deleted: true, conversation_id: conversation.id } : {}),
      ...(navigation ? { navigation } : {}),
    },
    confirmation,
    message: "Conversation updated.",
  };
}

function handlers(initial) {
  const records = new Map(initial.map(item => [item.id, item]));
  return {
    records,
    getConversation: id => records.get(id) || null,
    upsertConversation: conversation => records.set(conversation.id, conversation),
    removeConversation: id => records.delete(id),
    navigate: vi.fn(),
  };
}

describe("Conversation App Action adapter", () => {
  beforeEach(() => vi.restoreAllMocks());

  test("visible controls dispatch revisions and NLP receipts update the same state", async () => {
    const AppActions = await loadRuntime();
    const ui = handlers([{ id: "chat-1", title: "Chat", pinned: false, revision: 0 }]);
    const nlp = handlers([{ id: "chat-1", title: "Chat", pinned: false, revision: 0 }]);
    const receipt = actionReceipt({
      actionId: "conversation.pin",
      conversation: { id: "chat-1", title: "Chat", pinned: true, revision: 1 },
    });
    const client = { dispatch: vi.fn(async () => receipt) };
    const uiRuntime = AppActions.createConversationActionRuntime({ client, ...ui, requestIdFactory: () => "ui-1" });
    const nlpRuntime = AppActions.createConversationActionRuntime({ client: {}, ...nlp });

    await uiRuntime.dispatch("conversation.pin", { conversation_id: "chat-1" }, { conversationId: "other-chat" });
    nlpRuntime.applyReceipt({ ...receipt, source: "nlp" });

    expect(client.dispatch).toHaveBeenCalledWith(
      {
        request_id: "ui-1",
        action_id: "conversation.pin",
        action_version: "1",
        arguments: { conversation_id: "chat-1", target_revision: 0 },
      },
      expect.objectContaining({ source: "ui", invocation_conversation_id: "other-chat" }),
    );
    expect(ui.records.get("chat-1")).toEqual(nlp.records.get("chat-1"));
    expect(ui.records.get("chat-1").pinned).toBe(true);
  });

  test("confirmation keeps the chat until the bound delete request succeeds", async () => {
    const AppActions = await loadRuntime();
    const state = handlers([{ id: "chat-1", title: "Chat", revision: 0 }]);
    const confirmation = { token: "confirm-1", target_revision: 0 };
    const pending = actionReceipt({
      actionId: "conversation.delete",
      conversation: { id: "chat-1", title: "Chat", revision: 0 },
      status: "confirmation_required",
      confirmation,
    });
    const deleted = actionReceipt({
      actionId: "conversation.delete",
      conversation: { id: "chat-1", title: "Chat", revision: 0 },
      deleted: true,
      navigation: { view: "chat", conversation_id: null },
    });
    const client = {
      dispatch: vi.fn(async () => pending),
      confirm: vi.fn(async () => deleted),
    };
    const runtime = AppActions.createConversationActionRuntime({ client, ...state, requestIdFactory: () => "delete-1" });

    const receipt = await runtime.dispatch("conversation.delete", { conversation_id: "chat-1" }, { conversationId: "chat-1" });
    expect(state.records.has("chat-1")).toBe(true);
    await runtime.confirm(receipt, { conversationId: "chat-1" });

    expect(client.confirm).toHaveBeenCalledWith(
      "confirm-1",
      expect.objectContaining({ action_id: "conversation.delete", arguments: { conversation_id: "chat-1", target_revision: 0 } }),
      expect.objectContaining({ source: "ui", invocation_conversation_id: "chat-1" }),
    );
    expect(state.records.has("chat-1")).toBe(false);
    expect(state.navigate).toHaveBeenCalledWith({ view: "chat", conversation_id: null });
  });

  test("chat-originated delete requests remain available for bound confirmation", async () => {
    const AppActions = await loadRuntime();
    const state = handlers([{ id: "chat-1", title: "Chat", revision: 0 }]);
    const request = {
      request_id: "nlp-delete-1",
      action_id: "conversation.delete",
      action_version: "1",
      arguments: { conversation_id: "chat-1", target_revision: 0 },
    };
    const pending = {
      ...actionReceipt({
        actionId: "conversation.delete",
        conversation: { id: "chat-1", title: "Chat", revision: 0 },
        status: "confirmation_required",
        confirmation: { token: "confirm-nlp-1", target_revision: 0 },
      }),
      request_id: request.request_id,
      source: "nlp",
    };
    const deleted = {
      ...actionReceipt({
        actionId: "conversation.delete",
        conversation: { id: "chat-1", title: "Chat", revision: 0 },
        deleted: true,
      }),
      request_id: request.request_id,
      source: "nlp",
    };
    const client = { confirm: vi.fn(async () => deleted) };
    const runtime = AppActions.createConversationActionRuntime({ client, ...state });

    runtime.rememberRequest(request);
    runtime.applyReceipt(pending);
    expect(state.records.has("chat-1")).toBe(true);
    await runtime.confirm(pending, { source: "nlp", conversationId: "chat-1" });

    expect(client.confirm).toHaveBeenCalledWith(
      "confirm-nlp-1",
      request,
      expect.objectContaining({ source: "nlp", invocation_conversation_id: "chat-1" }),
    );
    expect(state.records.has("chat-1")).toBe(false);
  });
});
