/**
 * script-generator.ts
 *
 * Dùng Gemini API để tự động viết script.json hợp lệ theo ScriptSchema
 * từ:
 *   - Nội dung bài viết đã fetch (ArticleContent)
 *   - Hoặc keyword thuần (AI tự chọn angle)
 *
 * Cấu hình env:
 *   GEMINI_API_KEY    — Google AI Studio key (bắt buộc)
 *   GEMINI_MODEL      — default: gemini-2.0-flash (nhanh, rẻ)
 *   SCRIPT_LANGUAGE   — "vi" | "en" (default: "vi")
 *   SCRIPT_CHANNEL    — tên kênh xuất hiện trong outro (default: "Quẹp Làm IT")
 *   SCRIPT_STYLE      — "news" | "edu" | "tech" (default: "tech")
 */

import { writeFile, mkdir } from "node:fs/promises";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { log } from "./utils/logger.js";
import { ScriptSchema, type Script } from "./render/script-schema.js";
import type { ArticleContent } from "./content-sourcer.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

// ── Config ───────────────────────────────────────────────────────────────────

function getGeminiKey(): string {
  const key = process.env.GEMINI_API_KEY;
  if (!key) throw new Error("Missing GEMINI_API_KEY in .env.local");
  return key;
}

const GEMINI_MODEL = process.env.GEMINI_MODEL ?? "gemini-2.0-flash";
const SCRIPT_LANGUAGE = process.env.SCRIPT_LANGUAGE ?? "vi";
const SCRIPT_CHANNEL = process.env.SCRIPT_CHANNEL ?? "Quẹp Làm IT";
const SCRIPT_STYLE = process.env.SCRIPT_STYLE ?? "tech";

// ── Template catalogue (mirrors script-schema templates) ─────────────────────

/**
 * Mô tả template cho AI — giúp AI chọn đúng template và điền đúng field.
 */
const TEMPLATE_GUIDE = `
Available templates and their required fields (pick the most fitting for each scene):

1. hook     — Opening scene. Fields: { headline (max 40 chars), subhead? (max 40), kenBurns: "zoom-in"|"zoom-out"|"pan-left"|"pan-right" }
2. stat-hero — Big number/stat. Fields: { value (max 20, e.g. "87%"), label (max 40), context? (max 50) }
3. comparison — Two-side contrast. Fields: { left: {label, value, color:"cyan"}, right: {label, value, color:"purple", winner?:boolean} }
4. feature-list — Bullet list. Fields: { title (max 40), bullets (1-4 items, each max 50 chars), icon? }
5. callout  — Bold statement / quote. Fields: { statement (max 80 chars), tag? (max 20) }
6. outro    — Closing CTA. Fields: { ctaTop (max 30, e.g. "Theo dõi để biết thêm!"), channelName (max 30), source (max 40, credit the news source) }

Rules:
- scenes[0] MUST use "hook"
- scenes[last] MUST use "outro"
- 5–8 scenes total (aim for 6-7)
- voiceText per scene: 30-90 words (Vietnamese) — total ~400-500 words for 60-70s video
- No hashtags or emojis in voiceText (pure spoken narration)
- id format: "scene-1", "scene-2", ... (sequential)
`.trim();

// ── Prompt builders ───────────────────────────────────────────────────────────

function buildPromptFromArticle(article: ArticleContent, voiceId: string): string {
  const langInstruction = SCRIPT_LANGUAGE === "vi"
    ? "Write ALL voiceText in natural, conversational Vietnamese (Tiếng Việt). UI text (headline, label, bullets, etc.) can be Vietnamese too."
    : "Write ALL voiceText in English.";

  return `
You are an AI video script writer for short-form vertical videos (TikTok/YouTube Shorts, 60-70 seconds).
${langInstruction}

## Source Article
URL: ${article.url}
Domain: ${article.domain}
Title: ${article.title}
Body:
${article.bodyText.slice(0, 5000)}

## Task
Write a compelling, factual video script based on this article. Style: ${SCRIPT_STYLE}.

${TEMPLATE_GUIDE}

## Output Format
Return ONLY valid JSON matching this exact structure (no markdown, no explanation):

{
  "version": "1.0",
  "metadata": {
    "title": "<SEO-optimized video title, max 60 chars>",
    "source": {
      "url": "${article.url}",
      "domain": "${article.domain}",
      "image": ${article.imageUrl ? `"${article.imageUrl}"` : "null"}
    },
    "channel": "${SCRIPT_CHANNEL}"
  },
  "voice": {
    "provider": "lucylab",
    "voiceId": "${voiceId}",
    "speed": 1.0
  },
  "scenes": [
    // ... 5-8 scenes
  ]
}
`.trim();
}

function buildPromptFromKeyword(keyword: string, voiceId: string): string {
  const langInstruction = SCRIPT_LANGUAGE === "vi"
    ? "Write ALL voiceText in natural, conversational Vietnamese (Tiếng Việt)."
    : "Write ALL voiceText in English.";

  return `
You are an AI video script writer for short-form vertical videos (TikTok/YouTube Shorts, 60-70 seconds).
${langInstruction}

## Topic
Keyword/topic: "${keyword}"
Style: ${SCRIPT_STYLE}

Research the most interesting, factual, and engaging angle for this topic.
Focus on surprising facts, statistics, or comparisons that will hook viewers.

${TEMPLATE_GUIDE}

## Output Format
Return ONLY valid JSON (no markdown, no explanation):

{
  "version": "1.0",
  "metadata": {
    "title": "<SEO-optimized video title, max 60 chars>",
    "source": {
      "url": "https://www.google.com/search?q=${encodeURIComponent(keyword)}",
      "domain": "research",
      "image": null
    },
    "channel": "${SCRIPT_CHANNEL}"
  },
  "voice": {
    "provider": "lucylab",
    "voiceId": "${voiceId}",
    "speed": 1.0
  },
  "scenes": [
    // ... 5-8 scenes
  ]
}
`.trim();
}

// ── Gemini API call ──────────────────────────────────────────────────────────

async function callGemini(prompt: string): Promise<string> {
  const apiKey = getGeminiKey();
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${apiKey}`;

  const body = {
    contents: [{ parts: [{ text: prompt }] }],
    generationConfig: {
      temperature: 0.7,
      topP: 0.9,
      maxOutputTokens: 4096,
      responseMimeType: "application/json",
    },
    safetySettings: [
      { category: "HARM_CATEGORY_HATE_SPEECH", threshold: "BLOCK_NONE" },
      { category: "HARM_CATEGORY_DANGEROUS_CONTENT", threshold: "BLOCK_NONE" },
    ],
  };

  log.info(`[script-gen] Calling Gemini (${GEMINI_MODEL})...`);

  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const err = await res.text().catch(() => "");
    throw new Error(`Gemini API error ${res.status}: ${err.slice(0, 300)}`);
  }

  const data = await res.json() as {
    candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }>;
    error?: { message: string };
  };

  if (data.error) throw new Error(`Gemini error: ${data.error.message}`);

  const text = data.candidates?.[0]?.content?.parts?.[0]?.text ?? "";
  if (!text) throw new Error("Gemini returned empty response");

  return text;
}

// ── JSON extraction + validation ─────────────────────────────────────────────

function extractJson(raw: string): unknown {
  // Remove potential markdown code fences
  const cleaned = raw
    .replace(/^```(?:json)?\s*/i, "")
    .replace(/\s*```\s*$/, "")
    .trim();

  // Remove JS-style comments (// ...) that AI sometimes injects
  const noComments = cleaned.replace(/\/\/[^\n]*/g, "");

  return JSON.parse(noComments);
}

// ── Public API ───────────────────────────────────────────────────────────────

export interface GenerateOptions {
  /** LucyLab voice ID — substituted into the script */
  voiceId: string;
  /** Max retries if Gemini returns invalid JSON or fails schema validation */
  maxRetries?: number;
}

/**
 * Generate a valid script.json from a pre-fetched article.
 */
export async function generateScriptFromArticle(
  article: ArticleContent,
  options: GenerateOptions
): Promise<Script> {
  const { voiceId, maxRetries = 2 } = options;
  const prompt = buildPromptFromArticle(article, voiceId);

  for (let attempt = 1; attempt <= maxRetries + 1; attempt++) {
    try {
      const raw = await callGemini(prompt);
      const parsed = extractJson(raw);
      const script = ScriptSchema.parse(parsed);
      log.info(`[script-gen] Script validated: ${script.scenes.length} scenes — "${script.metadata.title}"`);
      return script;
    } catch (err) {
      if (attempt > maxRetries) throw err;
      log.warn(`[script-gen] Attempt ${attempt} failed: ${(err as Error).message} — retrying...`);
      await new Promise((r) => setTimeout(r, 1000 * attempt));
    }
  }
  throw new Error("Unreachable");
}

/**
 * Generate a valid script.json from a keyword/topic (no article URL needed).
 */
export async function generateScriptFromKeyword(
  keyword: string,
  options: GenerateOptions
): Promise<Script> {
  const { voiceId, maxRetries = 2 } = options;
  const prompt = buildPromptFromKeyword(keyword, voiceId);

  for (let attempt = 1; attempt <= maxRetries + 1; attempt++) {
    try {
      const raw = await callGemini(prompt);
      const parsed = extractJson(raw);
      const script = ScriptSchema.parse(parsed);
      log.info(`[script-gen] Keyword script validated: "${script.metadata.title}"`);
      return script;
    } catch (err) {
      if (attempt > maxRetries) throw err;
      log.warn(`[script-gen] Attempt ${attempt} failed: ${(err as Error).message} — retrying...`);
      await new Promise((r) => setTimeout(r, 1000 * attempt));
    }
  }
  throw new Error("Unreachable");
}

/**
 * Save a generated script to disk and return the path.
 * Creates <outputDir>/script.json.
 */
export async function saveScript(script: Script, outputDir: string): Promise<string> {
  await mkdir(outputDir, { recursive: true });
  const scriptPath = join(outputDir, "script.json");
  await writeFile(scriptPath, JSON.stringify(script, null, 2), "utf8");
  log.info(`[script-gen] Saved: ${scriptPath}`);
  return scriptPath;
}

/**
 * Slugify a title for use as a directory name.
 */
export function titleToSlug(title: string): string {
  return title
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60)
    || `video-${Date.now()}`;
}
