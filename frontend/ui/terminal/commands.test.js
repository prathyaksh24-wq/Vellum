import { describe, expect, test } from "vitest";
import { parseTerminalCommand } from "./commands.js";

describe("parseTerminalCommand", () => {
  test("passes ordinary shell input through", () => {
    expect(parseTerminalCommand("Get-Location")).toEqual({
      type: "shell",
      raw: "Get-Location",
    });
  });

  test("opens vellum mode for bare vellum", () => {
    expect(parseTerminalCommand("vellum")).toEqual({ type: "vellum" });
  });

  test("opens vellum mode for slash vellum", () => {
    expect(parseTerminalCommand("/vellum")).toEqual({ type: "vellum" });
  });

  test("parses shell switch commands", () => {
    expect(parseTerminalCommand("/shell cmd")).toEqual({
      type: "switch-shell",
      profile: "cmd",
    });
  });

  test("parses new tab commands", () => {
    expect(parseTerminalCommand("/new ubuntu")).toEqual({
      type: "new-tab",
      profile: "ubuntu",
    });
    expect(parseTerminalCommand("/new")).toEqual({
      type: "new-tab",
      profile: null,
    });
  });

  test("parses tabs and close commands", () => {
    expect(parseTerminalCommand("/tabs")).toEqual({ type: "tabs" });
    expect(parseTerminalCommand("/close")).toEqual({ type: "close-tab" });
  });

  test("reports unknown slash commands", () => {
    expect(parseTerminalCommand("/wat")).toEqual({
      type: "unknown",
      command: "/wat",
    });
  });
});
