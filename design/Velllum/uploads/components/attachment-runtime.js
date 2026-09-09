(function () {
  var MAX_BYTES = 10 * 1024 * 1024;

  function inferMime(file) {
    if (file.type) return file.type;
    var ext = String(file.name || "").split(".").pop().toLowerCase();
    var known = {
      txt: "text/plain", md: "text/markdown", csv: "text/csv", json: "application/json",
      yaml: "application/yaml", yml: "application/yaml", xml: "application/xml",
      html: "text/html", py: "text/x-python", js: "text/javascript", ts: "text/typescript",
      docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", webp: "image/webp", gif: "image/gif",
    };
    return known[ext] || "application/octet-stream";
  }

  function readDataUrl(file) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () { resolve(String(reader.result || "")); };
      reader.onerror = function () { reject(new Error((file.name || "Attachment") + " could not be read.")); };
      reader.readAsDataURL(file);
    });
  }

  async function prepareFiles(files, existingAttachments, client) {
    var selected = Array.from(files || []);
    if (!selected.length) return [];
    if (selected.length > 10) throw new Error("Attach no more than 10 files at once.");
    selected.forEach(function (file) {
      if (file.size > MAX_BYTES) throw new Error((file.name || "Attachment") + " is larger than 10 MB.");
    });
    if (!client || typeof client.prepareAttachments !== "function") throw new Error("Attachment preparation is unavailable.");
    var uploads = await Promise.all(selected.map(async function (file) {
      return { name: file.name, mime_type: inferMime(file), data_url: await readDataUrl(file) };
    }));
    var existingDigests = (existingAttachments || []).map(function (item) { return item.digest; }).filter(Boolean);
    var response = await client.prepareAttachments(uploads, existingDigests);
    return (response.attachments || []).map(function (attachment) {
      return Object.assign({}, attachment, {
        url: attachment.data_url || attachment.url || null,
        fresh: true,
      });
    });
  }

  function actionEffect(receipt, turn) {
    if (!receipt || receipt.action_id !== "composer.attachment.import") return null;
    var result = receipt.result || {};
    if (receipt.status !== "applied") return { error: receipt.message || "Attachment import failed." };
    return {
      openPicker: result.client_effect && result.client_effect.type === "attachment.picker.open",
      attachments: (turn && turn.turn_kind === "mixed") ? [] : (result.attachments || []).map(function (attachment) {
        return Object.assign({}, attachment, { url: attachment.data_url || attachment.url || null });
      }),
      deferredMessage: result.deferred_message || "",
    };
  }

  function mergeAttachments(current, incoming) {
    var digests = new Set((current || []).map(function (item) { return item.digest; }).filter(Boolean));
    return (current || []).concat((incoming || []).filter(function (item) {
      if (!item.digest || !digests.has(item.digest)) {
        if (item.digest) digests.add(item.digest);
        return true;
      }
      return false;
    }));
  }

  window.VellumUI = window.VellumUI || {};
  window.VellumUI.Attachments = {
    MAX_BYTES: MAX_BYTES,
    prepareFiles: prepareFiles,
    actionEffect: actionEffect,
    mergeAttachments: mergeAttachments,
  };
})();
