import { beforeEach, describe, expect, test, vi } from "vitest";
import { createTerminalWorkspace } from "./terminal-workspace.js";

class FakeTerminal {
  constructor() {
    this.lines = [];
    this.handlers = [];
  }
  open() {}
  focus() {}
  write(data) {
    this.lines.push(data);
  }
  writeln(data) {
    this.lines.push(`${data}\r\n`);
  }
  onData(handler) {
    this.handlers.push(handler);
    return { dispose() {} };
  }
  emit(data) {
    this.handlers.forEach((handler) => handler(data));
  }
  dispose() {}
}

class FakeSocket {
  constructor() {
    this.sent = [];
    this.readyState = WebSocket.OPEN;
  }
  send(data) {
    this.sent.push(JSON.parse(data));
  }
  close() {}
}

describe("createTerminalWorkspace", () => {
  let root;
  let sockets;

  beforeEach(() => {
    global.WebSocket = { OPEN: 1 };
    root = document.createElement("div");
    document.body.innerHTML = "";
    document.body.appendChild(root);
    sockets = [];
  });

  test("mounts one default terminal tab", async () => {
    const workspace = createTerminalWorkspace(root, {
      TerminalClass: FakeTerminal,
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
    });

    await workspace.mount();

    expect(root.querySelector(".terminal-tab.active").textContent).toContain("PowerShell");
    expect(sockets[0].sent[0]).toMatchObject({ type: "start", profile: "powershell" });
  });

  test("plus button opens a new terminal tab", async () => {
    const workspace = createTerminalWorkspace(root, {
      TerminalClass: FakeTerminal,
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
    });

    await workspace.mount();
    root.querySelector("[data-terminal-new]").click();

    expect(root.querySelectorAll(".terminal-tab")).toHaveLength(2);
    expect(sockets).toHaveLength(2);
  });

  test("slash new creates a requested profile tab", async () => {
    const workspace = createTerminalWorkspace(root, {
      TerminalClass: FakeTerminal,
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
    });

    await workspace.mount();
    workspace.handleCommand("/new cmd");

    expect(sockets[1].sent[0]).toMatchObject({ type: "start", profile: "cmd" });
  });

  test("vellum command enters vellum mode without sending shell input", async () => {
    const onOpenVellum = vi.fn();
    const workspace = createTerminalWorkspace(root, {
      TerminalClass: FakeTerminal,
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
      onOpenVellum,
    });

    await workspace.mount();
    workspace.handleCommand("vellum");

    expect(onOpenVellum).toHaveBeenCalledOnce();
    expect(sockets[0].sent).toHaveLength(1);
  });

  test("unknown slash commands print terminal output", async () => {
    const workspace = createTerminalWorkspace(root, {
      TerminalClass: FakeTerminal,
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
    });

    await workspace.mount();
    workspace.handleCommand("/unknown");

    expect(workspace.activeTerminal.lines.join("")).toContain("unknown command");
  });
});
