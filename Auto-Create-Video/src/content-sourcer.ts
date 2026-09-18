/**
 * content-sourcer.ts
 *
 * Thu thập nội dung từ:
 *  1. URL bài viết trực tiếp  → trả về ArticleContent
 *  2. RSS feed                 → trả về danh sách ArticleContent
 *  3. Keyword (Google News RSS) → trả về danh sách ArticleContent theo trending
 */

import { log } from "./utils/logger.js";

export interface ArticleContent {
  url: string;
  domain: string;
  title: string;
  /** Plain-text body (stripped HTML). Empty string nếu không extract được. */
  bodyText: string;
  /** URL của og:image hoặc first img src — dùng làm background */
  imageUrl: string | null;
  publishedAt: string | null;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function extractDomain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** Bỏ thẻ HTML, decode entities cơ bản, normalize whitespace */
function stripHtml(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/<style[\s\S]*?<\/style>/gi, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s{2,}/g, " ")
    .trim();
}

/** Extract og:image hoặc first <img src> từ HTML raw */
function extractImage(html: string): string | null {
  const ogMatch = html.match(/<meta[^>]+property=["']og:image["'][^>]+content=["']([^"']+)["']/i)
    ?? html.match(/<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:image["']/i);
  if (ogMatch?.[1]) return ogMatch[1];

  const imgMatch = html.match(/<img[^>]+src=["']([^"']+)["']/i);
  return imgMatch?.[1] ?? null;
}

/** Extract og:title hoặc <title> */
function extractTitle(html: string): string {
  const ogTitle = html.match(/<meta[^>]+property=["']og:title["'][^>]+content=["']([^"']+)["']/i)
    ?? html.match(/<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:title["']/i);
  if (ogTitle?.[1]) return stripHtml(ogTitle[1]);

  const titleTag = html.match(/<title[^>]*>([^<]+)<\/title>/i);
  return titleTag?.[1]?.trim() ?? "";
}

/** Extract article body text — ưu tiên <article>, <main>, fallback <body> */
function extractBody(html: string): string {
  const articleMatch = html.match(/<article[^>]*>([\s\S]*?)<\/article>/i)
    ?? html.match(/<main[^>]*>([\s\S]*?)<\/main>/i)
    ?? html.match(/<div[^>]+(?:class|id)=["'][^"']*(?:content|article|post|entry|story)[^"']*["'][^>]*>([\s\S]*?)<\/div>/i);

  const raw = articleMatch?.[1] ?? html;
  const text = stripHtml(raw);
  // Giữ tối đa 8000 ký tự — đủ cho Gemini/GPT prompt
  return text.slice(0, 8000);
}

// ── Fetch article from URL ────────────────────────────────────────────────────

export async function fetchArticleFromUrl(url: string): Promise<ArticleContent> {
  log.info(`[sourcer] Fetching article: ${url}`);

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);

  let html: string;
  try {
    const res = await fetch(url, {
      signal: controller.signal,
      headers: {
        "User-Agent": "Mozilla/5.0 (compatible; AIVideoCreator/2.0; +https://github.com)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "vi,en;q=0.9",
      },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`);
    html = await res.text();
  } finally {
    clearTimeout(timeout);
  }

  const title = extractTitle(html);
  const bodyText = extractBody(html);
  const imageUrl = extractImage(html);
  const domain = extractDomain(url);

  // Extract publish date from og:published_time or article:published_time
  const dateMatch = html.match(
    /<meta[^>]+(?:property|name)=["'](?:article:published_time|og:published_time)["'][^>]+content=["']([^"']+)["']/i
  );
  const publishedAt = dateMatch?.[1] ?? null;

  log.info(`[sourcer] Extracted: "${title.slice(0, 60)}" (${bodyText.length} chars)`);

  return { url, domain, title, bodyText, imageUrl, publishedAt };
}

// ── RSS feed reader ───────────────────────────────────────────────────────────

export interface RssItem {
  url: string;
  title: string;
  description: string;
  publishedAt: string | null;
  imageUrl: string | null;
}

export async function fetchRssFeed(feedUrl: string, limit = 10): Promise<RssItem[]> {
  log.info(`[sourcer] Fetching RSS: ${feedUrl}`);

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);

  let xml: string;
  try {
    const res = await fetch(feedUrl, {
      signal: controller.signal,
      headers: { "User-Agent": "AIVideoCreator/2.0 RSS Reader" },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    xml = await res.text();
  } finally {
    clearTimeout(timeout);
  }

  // Simple XML parser (no external dep) — handles RSS 2.0 and Atom
  const items: RssItem[] = [];
  const itemRegex = /<(?:item|entry)[\s>]([\s\S]*?)<\/(?:item|entry)>/gi;
  let match: RegExpExecArray | null;

  while ((match = itemRegex.exec(xml)) !== null && items.length < limit) {
    const block = match[1];

    const titleMatch = block.match(/<title[^>]*>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?<\/title>/i);
    const title = stripHtml(titleMatch?.[1]?.trim() ?? "");
    if (!title) continue;

    const linkMatch = block.match(/<link[^>]*href=["']([^"']+)["']/i)
      ?? block.match(/<link[^>]*>(https?:\/\/[^<]+)<\/link>/i)
      ?? block.match(/<guid[^>]*>(https?:\/\/[^<]+)<\/guid>/i);
    const url = linkMatch?.[1]?.trim() ?? "";
    if (!url) continue;

    const descMatch = block.match(/<description[^>]*>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?<\/description>/i)
      ?? block.match(/<summary[^>]*>([\s\S]*?)<\/summary>/i);
    const description = stripHtml(descMatch?.[1]?.trim() ?? "").slice(0, 500);

    const dateMatch = block.match(/<(?:pubDate|published|updated)[^>]*>([^<]+)<\/(?:pubDate|published|updated)>/i);
    const publishedAt = dateMatch?.[1]?.trim() ?? null;

    const enclosureMatch = block.match(/<enclosure[^>]+url=["']([^"']+)["'][^>]+type=["']image\//i)
      ?? block.match(/<media:thumbnail[^>]+url=["']([^"']+)["']/i);
    const imageUrl = enclosureMatch?.[1] ?? extractImage(block) ?? null;

    items.push({ url, title, description, publishedAt, imageUrl });
  }

  log.info(`[sourcer] RSS: ${items.length} items from ${feedUrl}`);
  return items;
}

// ── Google News RSS by keyword ────────────────────────────────────────────────

/**
 * Tìm bài viết trending theo keyword qua Google News RSS.
 * Không cần API key — public endpoint.
 */
export async function fetchGoogleNewsByKeyword(
  keyword: string,
  lang = "vi",
  limit = 5
): Promise<RssItem[]> {
  const q = encodeURIComponent(keyword);
  const feedUrl = `https://news.google.com/rss/search?q=${q}&hl=${lang}&gl=VN&ceid=VN:${lang}`;
  return fetchRssFeed(feedUrl, limit);
}

/**
 * Lấy tin trending Việt Nam (không cần keyword)
 */
export async function fetchVnTrending(limit = 5): Promise<RssItem[]> {
  const feedUrl = "https://news.google.com/rss?hl=vi&gl=VN&ceid=VN:vi";
  return fetchRssFeed(feedUrl, limit);
}

/**
 * Custom RSS feeds được cấu hình trong .env.local
 * VD: CUSTOM_RSS_FEEDS=https://vnexpress.net/rss/tin-moi-nhat.rss,https://tuoitre.vn/rss/tin-moi-nhat.rss
 */
export async function fetchCustomFeeds(limit = 5): Promise<RssItem[]> {
  const feedUrls = (process.env.CUSTOM_RSS_FEEDS ?? "")
    .split(",")
    .map((u) => u.trim())
    .filter(Boolean);

  if (feedUrls.length === 0) return [];

  const results = await Promise.allSettled(
    feedUrls.map((url) => fetchRssFeed(url, limit))
  );

  const items: RssItem[] = [];
  for (const r of results) {
    if (r.status === "fulfilled") items.push(...r.value);
  }

  // Sort by publishedAt desc, deduplicate by URL
  const seen = new Set<string>();
  return items
    .sort((a, b) => {
      const ta = a.publishedAt ? new Date(a.publishedAt).getTime() : 0;
      const tb = b.publishedAt ? new Date(b.publishedAt).getTime() : 0;
      return tb - ta;
    })
    .filter((it) => {
      if (seen.has(it.url)) return false;
      seen.add(it.url);
      return true;
    })
    .slice(0, limit);
}
