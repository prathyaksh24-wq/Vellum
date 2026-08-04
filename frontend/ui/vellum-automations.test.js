import { describe, expect, test } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(resolve(here, "../../design/Velllum/uploads/Vellum Default Re-designed.html"), "utf8");

describe("Vellum default automations surface", () => {
  test("replaces the template stub with a live management surface", () => {
    expect(html).not.toContain("Template list only. Live automation management is intentionally not enabled");
    expect(html).toContain("New automation");
    expect(html).toContain("Create with chat");
    expect(html).toContain("Run now");
    expect(html).toContain("built-in");
  });

  test("lists automations with schedule, destination, status, and last run", () => {
    expect(html).toContain("scheduleLabel(a.schedule)");
    expect(html).toContain("destinationLabel(a.destination)");
    expect(html).toContain("runStatusLabel(run)");
    expect(html).toContain("a.state === 'active' ? 'Pause' : 'Resume'");
    expect(html).toContain("a.builtin ? 'Reset' : 'Delete'");
  });

  test("manual create form covers all fields with VSelect pickers", () => {
    expect(html).toContain('id="au-name"');
    expect(html).toContain('id="au-instructions"');
    expect(html).toContain('id="au-schedule"');
    expect(html).toContain('ariaLabel="Automation destination"');
    expect(html).toContain('id="au-thread-id"');
    expect(html).toContain('ariaLabel="Model tier"');
    expect(html).toContain('ariaLabel="Reasoning mode"');
    expect(html).toContain("AUTOMATION_REASONING_MODES");
    expect(html).toContain("{value: 'extra high', label: 'Extra high'}");
    expect(html).toContain("{value: 'ultra', label: 'Ultra'}");
  });

  test("full-access opt-in is a deliberate confirmation with warning copy", () => {
    expect(html).toContain('role="switch" aria-checked={fullAccess}');
    expect(html).toContain("Runs unattended and bypasses confirmation gates");
    expect(html).toContain("runs entirely unattended and can perform actions without asking you each time");
    expect(html).toContain("Only enable it for tasks you fully trust");
  });

  test("create button starts the chat-guided flow with the explainer prompt", () => {
    expect(html).toContain("API.automations.createPrompt()");
    expect(html).toContain("sendMessage(prompt, [], {forceNew: true})");
    expect(html).toContain("onStartAutomationChat");
  });

  test("mutations call the extended API client and refresh the list", () => {
    expect(html).toContain("API.automations.create(payload)");
    expect(html).toContain("API.automations.update(record.id, payload)");
    expect(html).toContain("API.automations.update(a.id, {state:");
    expect(html).toContain("API.automations.remove(a.id)");
    expect(html).toContain("API.automations.run(a.id)");
    expect(html).toContain("API.automations.list()");
  });

  test("surfaces backend validation errors back into the settings panel", () => {
    expect(html).toContain("err.message");
    expect(html).toContain("au-form-error");
  });
});
