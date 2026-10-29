import {test, expect} from 'vitest';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import '../../design/Velllum/uploads/components/answer-markdown.js';
window.React = React;

test('renders formatting, lists and tables as semantic elements', () => {
  const html = renderToStaticMarkup(window.VellumUI.AnswerMarkdown({text:'### Brief\n\n**Useful** and `code`\n\n- One\n- Two\n\n| Team | Score |\n| --- | --- |\n| A | 2 |'}));
  expect(html).toContain('<strong>Useful</strong>');
  expect(html).toContain('<code>code</code>');
  expect(html).toContain('<ul>');
  expect(html).toContain('<table>');
  expect(html).not.toContain('###');
});

test('escapes untrusted HTML and blocks unsafe link schemes', () => {
  const html = renderToStaticMarkup(window.VellumUI.AnswerMarkdown({text:'<img src=x onerror=alert(1)> [click](javascript:alert) [source](https://example.com)'}));
  expect(html).not.toContain('<img');
  expect(html).not.toContain('href="javascript:');
  expect(html).toContain('href="https://example.com"');
  expect(html).toContain('noopener noreferrer');
});
