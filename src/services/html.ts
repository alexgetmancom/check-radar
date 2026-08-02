export type HtmlToken = {
  tag: string | undefined;
  attrs: Record<string, string>;
  text: string;
};

function decodeHtml(value: string): string {
  return value
    .replaceAll("&nbsp;", "\u00a0")
    .replaceAll("&amp;", "&")
    .replaceAll("&quot;", '"')
    .replaceAll("&#39;", "'")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">");
}

export function parseHtmlTokens(html: string): HtmlToken[] {
  const tokens: HtmlToken[] = [];
  const regex = /<([a-zA-Z0-9]+)([^>]*)>([^<]*)/g;
  for (const match of html.matchAll(regex)) {
    const tag = match[1];
    const rawAttrs = match[2] ?? "";
    const text = decodeHtml((match[3] ?? "").trim());
    if (!tag || !text) continue;
    const attrs: Record<string, string> = {};
    const classMatch = rawAttrs.match(/class\s*=\s*["']([^"']*)["']/i);
    if (classMatch?.[1]) attrs.class = classMatch[1];
    tokens.push({ tag, attrs, text });
  }
  return tokens;
}
