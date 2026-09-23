import {describe, expect, test} from "vitest";
import {readFileSync} from "node:fs";
import {resolve} from "node:path";
import {fingerprint, root, servedSources, validateParityInventory} from "./action-parity-contract.mjs";

const inventory = JSON.parse(readFileSync(resolve(root, "frontend/ui/action-parity.inventory.json"), "utf8"));

describe("served visual-control parity gate", () => {
  test("all reviewed handlers and covered controls remain accounted for", () => {
    expect(validateParityInventory(inventory)).toEqual([]);
  });

  test("a newly added state-changing visual control fails until reviewed", () => {
    const sources = servedSources();
    const path = "design/Velllum/uploads/Vellum Default Re-designed.html";
    sources[path] = sources[path].replace(
      "onClick={onLayoutReset}>Reset surfaces</button>",
      "onClick={onLayoutReset}>Reset surfaces</button><button onClick={() => setUnregisteredPreference(true)}>Save preference</button>",
    );
    expect(validateParityInventory(inventory, sources).join("\n")).toContain("visual handlers changed");
  });

  test("a covered control fails when its App Action mapping is removed", () => {
    const withoutAction = structuredClone(inventory);
    delete withoutAction.covered[0].actionId;
    expect(validateParityInventory(withoutAction).join("\n")).toContain("Incomplete covered control");
  });

  test("a non-state text change does not require action registration", () => {
    const sources = servedSources();
    const path = "design/Velllum/uploads/Vellum Default Re-designed.html";
    sources[path] = sources[path].replace("Reset surfaces</button>", "Reset workspace surfaces</button>");
    expect(fingerprint(path, sources[path])).toEqual(inventory.handlerFingerprints[path]);
  });

  test("a new externally served React control file cannot bypass the gate", () => {
    const sources = servedSources();
    const path = "design/Velllum/uploads/Vellum Default Re-designed.html";
    sources[path] = sources[path].replace(
      '<script type="text/babel" data-presets="react" src="components/v-select.jsx"></script>',
      '<script type="text/babel" data-presets="react" src="components/v-select.jsx"></script><script type="text/babel" src="components/new-controls.jsx"></script>',
    );
    expect(validateParityInventory(inventory, sources).join("\n")).toContain("unreviewed served React source");
  });

  test("uppercase script tags cannot bypass React source discovery", () => {
    const sources = servedSources();
    const path = "design/Velllum/uploads/Vellum Default Re-designed.html";
    sources[path] = sources[path].replace(
      "</body>",
      '<SCRIPT TYPE="text/babel" SRC="components/new-controls.jsx"></SCRIPT></body>',
    );
    expect(validateParityInventory(inventory, sources).join("\n")).toContain("unreviewed served React source");
  });

  test("an extra inline React control script cannot bypass the gate", () => {
    const sources = servedSources();
    const path = "design/Velllum/uploads/Vellum Default Re-designed.html";
    sources[path] = sources[path].replace(
      "</body>",
      '<script type="text/babel" data-presets="react"><button onClick={() => setBypass(true)}>Bypass</button></script></body>',
    );
    expect(() => validateParityInventory(inventory, sources)).toThrow("Expected one reviewed inline React script");
  });

  test("a reviewed React component cannot silently become unserved", () => {
    const sources = servedSources();
    const path = "design/Velllum/uploads/Vellum Default Re-designed.html";
    sources[path] = sources[path].replace(
      '<script type="text/babel" data-presets="react" src="components/v-select.jsx"></script>',
      "",
    );
    expect(validateParityInventory(inventory, sources).join("\n")).toContain("reviewed React source is no longer served");
  });

  test("exemptions are specific to non-committing gestures and drafts", () => {
    expect(inventory.exemptions.length).toBeGreaterThan(0);
    expect(inventory.exemptions.every(item => item.scope && item.reason)).toBe(true);
    expect(inventory.exemptions.some(item => /\bclick\b|\bsubmit\b/i.test(item.scope))).toBe(false);
    expect(inventory.deferred.every(item => item.surface && item.reason)).toBe(true);
  });
});
