export function parseSseBlocks(text) {
  return text
    .replace(/\r\n/g, "\n")
    .split("\n\n")
    .map((block) => block.trim())
    .filter(Boolean)
    .map((block) => {
      let event = "message";
      const dataLines = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      const data = dataLines.join("");
      return { event, data: data ? JSON.parse(data) : null };
    });
}

export function createCodingApi({ apiBase = "http://127.0.0.1:8000", fetchImpl = fetch } = {}) {
  const base = apiBase.replace(/\/$/, "");

  async function json(path, init) {
    const url = `${base}${path}`;
    const response = init === undefined ? await fetchImpl(url) : await fetchImpl(url, init);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
    return body;
  }

  return {
    health() {
      return json("/api/coding/health");
    },
    listSessions() {
      return json("/api/coding/sessions");
    },
    createSession(body) {
      return json("/api/coding/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    },
    projectTree(root) {
      return json(`/api/coding/projects/tree?root=${encodeURIComponent(root)}`);
    },
    async runTurn(sessionId, prompt, onEvent) {
      const response = await fetchImpl(`${base}/api/coding/sessions/${encodeURIComponent(sessionId)}/turns/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${response.status}`);
      }
      if (!response.body) {
        const text = await response.text();
        parseSseBlocks(text).forEach(onEvent);
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        parts.forEach((part) => {
          parseSseBlocks(`${part}\n\n`).forEach(onEvent);
        });
      }
      buffer += decoder.decode();
      if (buffer.trim()) parseSseBlocks(`${buffer}\n\n`).forEach(onEvent);
    },
  };
}
