import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..', '..');
const html = fs.readFileSync(path.join(root, 'design', 'Velllum', 'uploads', 'Vellum Default Re-designed.html'), 'utf8');
const chat = fs.readFileSync(path.join(root, 'design', 'Velllum', 'uploads', 'api', 'chat.js'), 'utf8');

describe('Vellum organizational runtime UI', () => {
  it('consumes organization events and renders department, agent, and task attribution', () => {
    expect(chat).toContain('ev === "organization"');
    expect(chat).toContain('vellum:organization');
    expect(html).toContain('data-vellum-organizational-runtime');
    expect(html).toContain('/api/agent-runtime/departments');
    expect(html).toContain('/api/agent-runtime/tasks');
    expect(html).toContain('task.agent_name');
    expect(html).toContain("event.event === 'disagreement'");
    expect(html).toContain('event.attribution');
  });

  it('supports recursive cancel while leaving the main composer active', () => {
    expect(html).toContain('/cancel`');
    expect(html).toContain('{confirm:true}');
    expect(html).toContain('data-composer-remains-active="true"');
    expect(html).not.toContain('disabled={active.length');
  });

  it('keeps specialist contributions separate from the final assistant response', () => {
    expect(html).toContain('final_contribution');
    expect(html).toContain('Agent organization');
    expect(chat).toContain('if (ev === "organization")');
    expect(chat).toContain('ev === "final"');
  });
});
