(function () {
  // React escapes text; source content never becomes HTML or event handlers.
  const words = (text, key, options) => options.animate
    ? text.split(/(\s+)/).map((word,index) => /\S/.test(word) ? React.createElement('span',{key:key+'-'+index,className:'agent-word'},word) : word)
    : text;
  const plain = (text, key, options) => {
    const claims=(options.claims || []).filter(claim=>claim.form==='interpretation' && claim.text && text.includes(claim.text));
    if(!options.pencil || !claims.length)return words(text,key,options);
    const claim=claims[0],at=text.indexOf(claim.text);
    return [words(text.slice(0,at),key+'-before',options),React.createElement('em',{key:key+'-claim',className:'agent-inferred',title:'BooksAgent interpretation'},words(claim.text,key+'-text',options)),plain(text.slice(at+claim.text.length),key+'-after',{...options,claims:claims.slice(1)})];
  };
  const inline = (text, options = {}) => {
    const nodes = [], pattern = /\*\*([^*\n]+)\*\*|`([^`\n]+)`|\[([^\]\n]+)\]\(([^\s)]+)\)|\[(\d+)\](?!\()/g;
    let cursor = 0, match;
    while ((match = pattern.exec(text))) {
      if (match.index > cursor) nodes.push(plain(text.slice(cursor, match.index),cursor,options));
      if (match[1]) nodes.push(React.createElement('strong', {key:match.index}, plain(match[1],match.index,options)));
      else if (match[2]) nodes.push(React.createElement('code', {key:match.index}, match[2]));
      else if (/^https?:\/\//i.test(match[4])) nodes.push(React.createElement('a', {key:match.index, href:match[4], target:'_blank', rel:'noopener noreferrer'}, words(match[3],match.index,options)));
      else if (match[5]) {
        const source = (options.sources || []).find((item, index) => String(item.source_index || index + 1) === match[5]);
        if (source) {
          const id = String(source.id || source.source_index || (options.sources.indexOf(source) + 1));
          nodes.push(React.createElement('button', {key:match.index,type:'button',className:'agent-citation-marker',
            'aria-label':`View citation ${match[5]}: ${source.title || 'Source'}`,
            'aria-controls':options.idPrefix + '-sources',onClick:()=>options.onCitation?.(id)},match[5]));
        } else nodes.push(match[0]);
      } else nodes.push(match[3]);
      cursor = pattern.lastIndex;
    }
    if (cursor < text.length) nodes.push(plain(text.slice(cursor),cursor,options));
    return nodes;
  };
  const cells = line => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => cell.trim());
  function AnswerMarkdown({text, sources = [], idPrefix = 'answer', onCitation, animate=false, pencil=false}) {
    const claims=sources.flatMap(source=>source.claims || []);
    const renderInline = value => inline(value, {sources,idPrefix,onCitation,animate,pencil,claims});
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
          React.createElement('thead', null, React.createElement('tr', null, headers.map((cell,k) => React.createElement('th',{key:k},renderInline(cell))))),
          React.createElement('tbody', null, rows.map((row,r) => React.createElement('tr',{key:r},row.map((cell,k) => React.createElement('td',{key:k},renderInline(cell))))))
        ), {className:'answer-table'});continue;
      }
      const list = line.match(/^\s*(?:([-*])|\d+[.)])\s+(.+)$/);
      if (list) {
        const ordered=!list[1], items=[];
        while (i < lines.length) {
          const item=lines[i].match(ordered ? /^\s*\d+[.)]\s+(.+)$/ : /^\s*[-*]\s+(.+)$/);
          if (!item) break;
          items.push(React.createElement('li',{key:items.length},renderInline(item[1])));i++;
        }
        add(ordered?'ol':'ul',items);continue;
      }
      const heading=line.match(/^\s{0,3}#{1,6}\s+(.+)$/);
      if (heading) {add('h3',renderInline(heading[1]));i++;continue;}
      if (/^\s*>\s?/.test(line)) {add('blockquote',renderInline(line.replace(/^\s*>\s?/,'')));i++;continue;}
      add('p',renderInline(line));i++;
    }
    return React.createElement('div',{className:'answer-markdown'},blocks);
  }
  window.VellumUI={...window.VellumUI,AnswerMarkdown};
})();
