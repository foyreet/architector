'use strict';
// Marked supplies Markdown tokens only. Model-provided HTML never enters the DOM.
window.ChatMarkdown = source => {
  const root = document.createElement('div'); root.className = 'codex-markdown';
  const decode = value => String(value || '').replace(/&(?:#[0-9]+|#x[0-9a-f]+|[a-z][a-z0-9]+);/gi,
    entity => new DOMParser().parseFromString(entity, 'text/html').body.textContent);
  const text = value => document.createTextNode(decode(value));
  const linkURL = value => {
    try {
      const url = new URL(decode(value));
      return ['https:', 'http:', 'mailto:'].includes(url.protocol) ? url.href : null;
    } catch { return null; }
  };
  function render(tokens, parent, depth = 0) {
    for (const token of tokens || []) {
      if (depth > 32) { parent.append(document.createTextNode(token.raw || token.text || '')); continue; }
      let element;
      const children = target => render(token.tokens, target, depth + 1);
      switch (token.type) {
        case 'space': case 'def': continue;
        case 'paragraph': element = document.createElement('p'); children(element); break;
        case 'heading': element = document.createElement('h' + Math.min(6, token.depth + 2)); children(element); break;
        case 'strong': case 'em': case 'del': element = document.createElement(token.type); children(element); break;
        case 'text':
          if (token.tokens) children(parent); else parent.append(text(token.text));
          continue;
        case 'escape': parent.append(text(token.text)); continue;
        case 'html': parent.append(document.createTextNode(token.raw)); continue;
        case 'image': parent.append(text(token.text)); continue;
        case 'codespan': element = document.createElement('code'); element.textContent = token.text; break;
        case 'code': {
          element = document.createElement('pre'); element.tabIndex = 0;
          element.setAttribute('aria-label', 'Блок кода');
          const code = document.createElement('code'); code.textContent = token.text;
          element.append(code); break;
        }
        case 'br': case 'hr': element = document.createElement(token.type); break;
        case 'blockquote': element = document.createElement('blockquote'); children(element); break;
        case 'link': {
          const href = linkURL(token.href);
          if (!href) { children(parent); continue; }
          element = document.createElement('a'); element.href = href;
          element.target = '_blank'; element.rel = 'noopener noreferrer';
          if (token.title) element.title = decode(token.title);
          children(element); break;
        }
        case 'list':
          element = document.createElement(token.ordered ? 'ol' : 'ul');
          if (token.ordered && Number.isInteger(token.start)) element.start = token.start;
          for (const item of token.items) {
            const li = document.createElement('li');
            if (item.task) li.append(document.createTextNode(item.checked ? '☑ ' : '☐ '));
            render(item.tokens, li, depth + 1); element.append(li);
          }
          break;
        case 'table': {
          element = document.createElement('div'); element.className = 'codex-markdown-table';
          element.tabIndex = 0; element.setAttribute('role', 'region'); element.setAttribute('aria-label', 'Таблица');
          const table = document.createElement('table'), head = document.createElement('thead'), body = document.createElement('tbody');
          function row(cells, heading) {
            const tr = document.createElement('tr');
            cells.forEach((cell, index) => {
              const td = document.createElement(heading ? 'th' : 'td');
              if (heading) td.scope = 'col';
              if (['left', 'right', 'center'].includes(token.align[index])) td.style.textAlign = token.align[index];
              render(cell.tokens, td, depth + 1); tr.append(td);
            });
            return tr;
          }
          head.append(row(token.header, true));
          token.rows.forEach(cells => body.append(row(cells, false)));
          table.append(head, body); element.append(table); break;
        }
        default: parent.append(document.createTextNode(token.raw || token.text || '')); continue;
      }
      parent.append(element);
    }
  }
  try { render(window.marked.lexer(String(source || ''), {gfm: true}), root); }
  catch { root.classList.add('codex-markdown-fallback'); root.textContent = String(source || ''); }
  return root;
};

