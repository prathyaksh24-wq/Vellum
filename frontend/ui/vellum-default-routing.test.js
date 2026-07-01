import { readFileSync } from "node:fs";
import { describe, expect, test } from "vitest";

const source = readFileSync("ui/vellum-default.html", "utf8");

describe("minimal LLM routing settings", () => {
  test("loads and labels provider routing, fallbacks, and credential health", () => {
    expect(source).toContain("routingStatus");
    expect(source).toContain("Provider routing");
    expect(source).toContain("Fallback chain");
    expect(source).toContain("Credential pools");
    expect(source).toContain("Latest route");
  });

  test("supports policy, fallback, strategy, reset, and credential mutations", () => {
    expect(source).toContain("setGlobalRoutingPolicy");
    expect(source).toContain("setFallbacks");
    expect(source).toContain("setCredentialStrategy");
    expect(source).toContain("resetCredentialPool");
    expect(source).toContain("addCredential");
    expect(source).toContain("removeCredential");
  });

  test("clears entered secrets and never stores them in localStorage", () => {
    expect(source).toContain("secret: ''");
    expect(source).not.toMatch(/localStorage\.setItem\([^\n]*credential/i);
    expect(source).not.toMatch(/localStorage\.setItem\([^\n]*api.?key/i);
  });
});
