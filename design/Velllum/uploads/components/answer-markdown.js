(function () {
  // React escapes text; source content never becomes HTML or event handlers.
  const inline = text => {
    const nodes = [], pattern = /\*\*([^*\n]+)\*\*|`([^`\n]+)`|\[([^\]\n]+)\]\(([^\s)]+)\)/g;
    let cursor = 0, match;
    while ((match = pattern.exec(text))) {
      if (match.index > cursor) nodes.push(text.slice(cursor, match.index));
      if (match[1]) nodes.push(React.createElement('strong', {key:match.index}, match[1]));
      else if (match[2]) nodes.push(React.createElement('code', {key:match.index}, match[2]));
      else if (/^https?:\/\//i.test(match[4])) nodes.push(React.createElement('a', {key:match.index, href:match[4], target:'_blank', rel:'noopener noreferrer'}, match[3]));
      else nodes.push(match[3]);
      cursor = pattern.lastIndex;
    }
    if (cursor < text.length) nodes.push(text.slice(cursor));
    return nodes;
  };
  const cells = line => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => cell.trim());
  function AnswerMarkdown({text}) {
    const lines = String(text || '').split('\n'), blocks = [];
    let i = 0;
    const add = (tag, children, props={}) => blocks.push(React.createElement(tag, {key:blocks.length,...props}, children));
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) {i++; continue;}
      if (/^\s*```/.test(line)) {
        const code=[]; i++;
        while (i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i++]);
        if (i < lines.length) i++;
        add('pre', React.createElement('code', null, code.join('\n'))); continue;
      }
      if (i+1 < lines.length && line.includes('|') && /^\s*\|?\s*:?-{3,}:?\s*\|/.test(lines[i+1])) {
        const headers=cells(line), rows=[];i+=2;
        while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(cells(lines[i++]));
        add('div', React.createElement('table', null,
          React.createElement('thead', null, React.createElement('tr', null, headers.map((cell,k) => React.createElement('th',{key:k},inline(cell))))),
          React.createElement('tbody', null, rows.map((row,r) => React.createElement('tr',{key:r},row.map((cell,k) => React.createElement('td',{key:k},inline(cell))))))
        ), {className:'answer-table'});continue;
      }
      const list = line.match(/^\s*(?:([-*])|\d+[.)])\s+(.+)$/);
      if (list) {
        const ordered=!list[1], items=[];
        while (i < lines.length) {
          const item=lines[i].match(ordered ? /^\s*\d+[.)]\s+(.+)$/ : /^\s*[-*]\s+(.+)$/);
          if (!item) break;
          items.push(React.createElement('li',{key:items.length},inline(item[1])));i++;
        }
        add(ordered?'ol':'ul',items);continue;
      }
      const heading=line.match(/^\s{0,3}#{1,6}\s+(.+)$/);
      if (heading) {add('h3',inline(heading[1]));i++;continue;}
      add('p',inline(line));i++;
    }
    return React.createElement('div',{className:'answer-markdown'},blocks);
  }
  window.VellumUI={...window.VellumUI,AnswerMarkdown};
})();
