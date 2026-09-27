// Run with: node --test tests/chat-markdown.test.cjs
const assert = require('node:assert/strict');
const test = require('node:test');
const markdown = require('../questchain/static/chat-markdown.js');

test('renders prose, nested lists, blockquotes, links and tables', () => {
  const html = markdown.render(`# Overview

**Bold**, *italic*, ~~old~~, and [docs](https://example.com/docs).
Second line.

1. First
   - Nested
2. Second

> Quoted text

| Agent | Role |
| --- | --- |
| Talos | Builder |
`);
  for (const fragment of ['<h1>Overview</h1>', '<strong>Bold</strong>', '<em>italic</em>', '<s>old</s>',
    '<ol>', '<ul>', '<blockquote>', '<table>', '<th>Agent</th>', '<td>Builder</td>', '<br>',
    'href="https://example.com/docs" target="_blank" rel="noopener noreferrer"']) {
    assert.ok(html.includes(fragment), fragment);
  }
});

test('preserves whitespace and literal markup inside inline and fenced code', () => {
  const html = markdown.render('Use `<tag>`:\n\n```python\nif x < 2:\n    print("**literal**")\n```');
  assert.ok(html.includes('<code>&lt;tag&gt;</code>'));
  assert.ok(html.includes('<pre><code class="language-python">if x &lt; 2:\n    print(&quot;**literal**&quot;)\n</code></pre>'));
  assert.ok(!html.includes('<strong>literal</strong>'));
});

test('renders raw HTML as text and rejects executable link schemes', () => {
  const html = markdown.render('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n<svg onload=alert(1)></svg>');
  assert.ok(html.includes('&lt;script&gt;'));
  assert.doesNotMatch(html, /<(?:script|img|svg)\b/i);
  for (const url of ['javascript:alert(1)', 'JaVaScRiPt:alert(1)', 'java&#x73;cript:alert(1)',
    'javascript&#58;alert(1)', 'vbscript:alert(1)', 'data:text/html,hello', 'file:///tmp/test',
    'data:image/png;base64,AAAA', 'custom:open']) {
    assert.doesNotMatch(markdown.render(`[click](${url})`), /<a\b/, url);
    assert.doesNotMatch(markdown.render(`![image](${url})`), /<(?:a|img)\b/, url);
  }
});

test('image references become escaped links without automatically loading resources', () => {
  const html = markdown.render('![<img onerror=alert(1)>](https://example.com/image.png)');
  assert.ok(html.includes('href="https://example.com/image.png"'));
  assert.ok(html.includes('&lt;img onerror=alert(1)&gt;'));
  assert.doesNotMatch(html, /<img\b/i);
});

test('split streaming tokens render identically to completion and restored history', () => {
  const source = '# Heading\n\n**Bold** and [link](https://example.com).\n\n```html\n<div>text</div>\n```\n';
  const streaming = {};
  for (const char of source) markdown.append(streaming, char);
  const expected = markdown.render(source);
  assert.equal(streaming.innerHTML, expected);
  markdown.set(streaming, source); // Completion replaces rather than repeats the stream.
  assert.equal(streaming.innerHTML, expected);
  const restored = {};
  const split = source.indexOf('text');
  markdown.set(restored, source.slice(0, split)); // Reconnected during an open code fence.
  markdown.append(restored, source.slice(split));
  assert.equal(restored.innerHTML, expected);
  const completedHistory = {};
  markdown.set(completedHistory, source);
  assert.equal(completedHistory.innerHTML, expected);
});

test('interleaved messages keep separate Markdown source', () => {
  const first = {}, second = {};
  markdown.append(first, '**First');
  markdown.append(second, '`Second');
  markdown.append(first, '**');
  markdown.append(second, '`');
  assert.equal(first.innerHTML, '<p><strong>First</strong></p>\n');
  assert.equal(second.innerHTML, '<p><code>Second</code></p>\n');
  markdown.set(first, '');
  markdown.append(first, 'Replacement');
  assert.equal(first.innerHTML, '<p>Replacement</p>\n');
});
