// Keep model output as Markdown source; never append tokens to rendered HTML.
(function (root) {
  'use strict';
  const MarkdownIt = typeof module === 'object' && module.exports
    ? require('./markdown-it.min.js') : root.markdownit;
  const parser = new MarkdownIt({ html: false, breaks: true, linkify: true });
  const sources = new WeakMap();

  parser.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
    tokens[index].attrSet('target', '_blank');
    tokens[index].attrSet('rel', 'noopener noreferrer');
    return renderer.renderToken(tokens, index, options);
  };
  // Show image references as links so a response cannot fetch remote images.
  parser.renderer.rules.image = (tokens, index, options, env, renderer) => {
    const token = tokens[index];
    const label = renderer.renderInlineAsText(token.children || [], options, env) || 'Image';
    const href = parser.utils.escapeHtml(token.attrGet('src') || '');
    return `<a href="${href}" target="_blank" rel="noopener noreferrer">${parser.utils.escapeHtml(label)}</a>`;
  };
  // Only web, email, and relative links may be opened from model output.
  const validateLink = parser.validateLink.bind(parser);
  parser.validateLink = url => validateLink(url) && !/^(?!(?:https?|mailto):)[a-z][a-z\d+.-]*:/i.test(url);
  parser.renderer.rules.table_open = (tokens, index, options, env, renderer) =>
    '<div class="markdown-table" role="region" aria-label="Table" tabindex="0">' + renderer.renderToken(tokens, index, options);
  parser.renderer.rules.table_close = () => '</table></div>\n';

  const chatMarkdown = {
    render(source) { return parser.render(source || ''); },
    set(bubble, source) {
      sources.set(bubble, source || '');
      bubble.innerHTML = this.render(source);
    },
    append(bubble, token) {
      this.set(bubble, (sources.get(bubble) || '') + (token || ''));
    },
  };
  if (typeof module === 'object' && module.exports) module.exports = chatMarkdown;
  else root.ChatMarkdown = chatMarkdown;
})(globalThis);
