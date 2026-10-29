import { beforeEach, describe, expect, test, vi } from "vitest";

async function loadRuntime() {
  vi.resetModules();
  window.VellumUI = {};
  await import("../../design/Velllum/uploads/components/attachment-runtime.js");
  return window.VellumUI.Attachments;
}

describe("Conversation attachment runtime", () => {
  beforeEach(() => vi.restoreAllMocks());

  test("picker, drop, and paste files normalize through the backend attachment owner", async () => {
    const runtime = await loadRuntime();
    const file = new File(["hello"], "note.txt", {type: "text/plain"});
    const record = {name: "note.txt", kind: "document", digest: "digest-1", text_content: "hello"};
    const client = {prepareAttachments: vi.fn(async () => ({attachments: [record]}))};

    const prepared = await runtime.prepareFiles([file], [{digest: "old"}], client);

    expect(client.prepareAttachments).toHaveBeenCalledWith([
      expect.objectContaining({name: "note.txt", mime_type: "text/plain", data_url: expect.stringContaining("base64,")}),
    ], ["old"]);
    expect(prepared).toEqual([{...record, url: null, fresh: true}]);
  });

  test("NLP receipts stage pure attachments but mark mixed attachments as already consumed", async () => {
    const runtime = await loadRuntime();
    const receipt = {
      action_id: "composer.attachment.import",
      status: "applied",
      result: {attachments: [{name: "note.txt", digest: "d1", text_content: "hello"}]},
    };

    expect(runtime.actionEffect(receipt, {turn_kind: "action"}).attachments).toHaveLength(1);
    expect(runtime.actionEffect(receipt, {turn_kind: "mixed"}).attachments).toEqual([]);
  });

  test("unknown NLP sources open the picker and preserve deferred conversational work", async () => {
    const runtime = await loadRuntime();
    const effect = runtime.actionEffect({
      action_id: "composer.attachment.import",
      status: "applied",
      result: {
        attachments: [],
        client_effect: {type: "attachment.picker.open"},
        deferred_message: "summarize it",
      },
    }, {turn_kind: "mixed"});

    expect(effect).toMatchObject({openPicker: true, deferredMessage: "summarize it", attachments: []});
  });

  test("duplicate records merge only once", async () => {
    const runtime = await loadRuntime();
    expect(runtime.mergeAttachments(
      [{name: "one", digest: "same"}],
      [{name: "duplicate", digest: "same"}, {name: "two", digest: "two"}],
    )).toEqual([{name: "one", digest: "same"}, {name: "two", digest: "two"}]);
  });
});
