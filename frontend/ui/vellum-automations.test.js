import { describe, expect, test } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(resolve(here, "../../design/Velllum/uploads/Vellum Default Re-designed.html"), "utf8");

describe("Vellum default automations surface", () => {
  test("mounts a dedicated Scheduled workspace", () => {
    expect(html).not.toContain("Template list only. Live automation management is intentionally not enabled");
    expect(html).toContain("'scheduled'");
    expect(html).toContain("<ScheduledView");
    expect(html).toContain("Scheduled");
    expect(html).toContain("Create with Vellum");
    expect(html).toContain("Set up manually");
  });

  test("lists tasks with filters, status dots, details, and an actions menu", () => {
    expect(html).toContain("scheduleLabel(record.schedule)");
    expect(html).toContain("destinationLabel(selected.destination, chats)");
    expect(html).toContain("runStatusLabel(lastRun(selected))");
    expect(html).toContain("Actions for ");
    expect(html).toContain("Run now");
    expect(html).toContain("Reset task");
    expect(html).toContain("Delete task");
  });

  test("manual setup covers task, destination, project, model, and schedule fields", () => {
    expect(html).toContain('id="au-name"');
    expect(html).toContain('id="au-description"');
    expect(html).toContain('id="au-instructions"');
    expect(html).toContain('ariaLabel="Runs in"');
    expect(html).toContain('ariaLabel="Pinned chat"');
    expect(html).toContain('ariaLabel="Automation project"');
    expect(html).toContain('ariaLabel="Automation model"');
    expect(html).toContain('ariaLabel="Reasoning mode"');
    expect(html).toContain('ariaLabel="Automation frequency"');
    expect(html).toContain('ariaLabel="Automation notifications"');
    expect(html).toContain('id="au-interval-value"');
    expect(html).toContain('id="au-time"');
    expect(html).toContain("AUTOMATION_REASONING_MODES");
    expect(html).toContain("{value: 'extra high', label: 'Extra high'}");
    expect(html).toContain("{value: 'ultra', label: 'Ultra'}");
    expect(html).toContain("project_id: projectId || null");
    expect(html).toContain("notifications: {level: notification}");
  });

  test("full-access opt-in is a deliberate confirmation with warning copy", () => {
    expect(html).toContain('role="switch" aria-checked={fullAccess}');
    expect(html).toContain("Run unattended");
    expect(html).toContain("Unattended runs can perform actions without asking first");
    expect(html).toContain("Enable this only for tasks you trust");
  });

  test("chat-guided creation starts in project context when available", () => {
    expect(html).toContain("API.automations.createPrompt()");
    expect(html).toContain("sendMessage(prompt, [], {forceNew: true, projectId})");
    expect(html).toContain("onStartAutomationChat");
  });

  test("mutations call the extended API client and refresh the list", () => {
    expect(html).toContain("API.automations.create(payload)");
    expect(html).toContain("API.automations.update(editing.record.id, payload)");
    expect(html).toContain("API.automations.update(record.id, {state:");
    expect(html).toContain("API.automations.remove(record.id)");
    expect(html).toContain("API.automations.run(record.id)");
    expect(html).toContain("API.automations.list()");
  });

  test("uses quiet generic errors and an explicit discard action", () => {
    expect(html).toContain("Save failed");
    expect(html).toContain("Unavailable");
    expect(html).toContain("Discard");
    expect(html).toContain("Discard changes?");
    expect(html).toContain("Your unsaved changes will be lost.");
    expect(html).toContain("au-form-error");
  });
});
