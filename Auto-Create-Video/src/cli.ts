#!/usr/bin/env node
/**
 * cli.ts — Điểm vào chính của pipeline
 *
 * Modes:
 *   npm run pipeline -- <path/to/script.json>
 *       → Chạy pipeline từ script.json có sẵn (giữ nguyên hành vi cũ)
 *
 *   npm run pipeline -- --url <article-url> [--out <output-dir>]
 *       → Tự động: fetch bài viết → AI viết script → chạy pipeline
 *
 *   npm run pipeline -- --keyword <"chủ đề"> [--out <output-dir>]
 *       → Tự động: AI viết script từ keyword → chạy pipeline
 *
 *   npm run pipeline -- --rss [--keyword <filter>] [--out <output-dir>]
 *       → Tự động: lấy bài trending từ RSS → chọn bài đầu → AI viết script → pipeline
 */

import { config } from "dotenv";
config({ path: ".env.local" });

import { join } from "node:path";
import { runPipeline } from "./pipeline.js";
import { log } from "./utils/logger.js";
import { loadConfig } from "./config.js";
import {
  fetchArticleFromUrl,
  fetchGoogleNewsByKeyword,
  fetchVnTrending,
  fetchCustomFeeds,
} from "./content-sourcer.js";
import {
  generateScriptFromArticle,
  generateScriptFromKeyword,
  saveScript,
  titleToSlug,
} from "./script-generator.js";

// ── Helpers ───────────────────────────────────────────────────────────────────

function parseArgs(argv: string[]): Record<string, string | boolean> {
  const args: Record<string, string | boolean> = {};
  for (let i = 0; i < argv.length; i++) {
    if (argv[i].startsWith("--")) {
      const key = argv[i].slice(2);
      const next = argv[i + 1];
      if (next && !next.startsWith("--")) {
        args[key] = next;
        i++;
      } else {
        args[key] = true;
      }
    } else if (!argv[i].startsWith("-")) {
      // positional: first positional = script path (legacy mode)
      if (!args["_script"]) args["_script"] = argv[i];
    }
  }
  return args;
}

function getDefaultOutDir(title: string): string {
  const slug = titleToSlug(title);
  const date = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  return join(process.cwd(), "output", `${date}-${slug}`);
}

// ── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  const args = parseArgs(process.argv.slice(2));

  // ── Mode 1: Legacy — chạy từ script.json có sẵn ────────────────────────────
  if (args["_script"]) {
    const scriptPath = args["_script"] as string;
    log.info("Mode: run existing script.json");
    await runPipeline(scriptPath);
    return;
  }

  // ── Modes 2/3/4 cần Gemini API key ─────────────────────────────────────────
  if (!process.env.GEMINI_API_KEY) {
    console.error(
      "Error: GEMINI_API_KEY is required for --url / --keyword / --rss modes.\n" +
      "Add it to .env.local:\n  GEMINI_API_KEY=AIza..."
    );
    process.exit(2);
  }

  const cfg = loadConfig();
  const voiceId = cfg.ttsProvider === "lucylab"
    ? (cfg.lucylabVoiceId ?? "")
    : (cfg.elevenlabsVoiceId ?? "");
  const genOptions = { voiceId, maxRetries: 2 };

  // ── Mode 2: --url <article-url> ─────────────────────────────────────────────
  if (args["url"]) {
    const url = args["url"] as string;
    log.info(`Mode: generate script from URL → ${url}`);

    const article = await fetchArticleFromUrl(url);
    if (!article.title) throw new Error("Could not extract article title — check the URL");

    const script = await generateScriptFromArticle(article, genOptions);
    const outDir = (args["out"] as string | undefined) ?? getDefaultOutDir(script.metadata.title);
    const scriptPath = await saveScript(script, outDir);

    log.info(`Script saved → ${scriptPath}`);
    await runPipeline(scriptPath);
    return;
  }

  // ── Mode 3: --keyword <"chủ đề"> ────────────────────────────────────────────
  if (args["keyword"] && !args["rss"]) {
    const keyword = args["keyword"] as string;
    log.info(`Mode: generate script from keyword → "${keyword}"`);

    const script = await generateScriptFromKeyword(keyword, genOptions);
    const outDir = (args["out"] as string | undefined) ?? getDefaultOutDir(script.metadata.title);
    const scriptPath = await saveScript(script, outDir);

    log.info(`Script saved → ${scriptPath}`);
    await runPipeline(scriptPath);
    return;
  }

  // ── Mode 4: --rss [--keyword <filter>] ──────────────────────────────────────
  if (args["rss"]) {
    const keyword = args["keyword"] as string | undefined;
    log.info(keyword
      ? `Mode: RSS feed → keyword filter "${keyword}"`
      : "Mode: RSS feed → VN trending"
    );

    // Ưu tiên custom feeds, rồi đến Google News
    const customItems = await fetchCustomFeeds(5);
    let items = customItems.length > 0 ? customItems :
      (keyword ? await fetchGoogleNewsByKeyword(keyword) : await fetchVnTrending(5));

    if (items.length === 0) {
      throw new Error("No RSS items found. Check CUSTOM_RSS_FEEDS or internet connection.");
    }

    // Lấy bài đầu tiên (mới nhất / most relevant)
    const picked = items[0];
    log.info(`[rss] Picked: "${picked.title}" → ${picked.url}`);

    // Fetch full article content
    let script;
    try {
      const article = await fetchArticleFromUrl(picked.url);
      // Dùng ảnh từ RSS nếu article không có
      if (!article.imageUrl && picked.imageUrl) {
        (article as { imageUrl: string | null }).imageUrl = picked.imageUrl;
      }
      script = await generateScriptFromArticle(article, genOptions);
    } catch (err) {
      log.warn(`[rss] Could not fetch full article (${(err as Error).message}), falling back to description`);
      // Fallback: dùng title + description từ RSS
      const article = {
        url: picked.url,
        domain: new URL(picked.url).hostname.replace(/^www\./, ""),
        title: picked.title,
        bodyText: `${picked.title}\n\n${picked.description}`,
        imageUrl: picked.imageUrl,
        publishedAt: picked.publishedAt,
      };
      script = await generateScriptFromArticle(article, genOptions);
    }

    const outDir = (args["out"] as string | undefined) ?? getDefaultOutDir(script.metadata.title);
    const scriptPath = await saveScript(script, outDir);

    log.info(`Script saved → ${scriptPath}`);
    await runPipeline(scriptPath);
    return;
  }

  // ── No mode matched ──────────────────────────────────────────────────────────
  console.error(
    "Usage:\n" +
    "  npm run pipeline -- <path/to/script.json>         # run from existing script\n" +
    "  npm run pipeline -- --url <article-url>            # generate from article URL\n" +
    "  npm run pipeline -- --keyword <\"chủ đề\">          # generate from keyword\n" +
    "  npm run pipeline -- --rss [--keyword <filter>]     # pick from RSS feed\n" +
    "\nOptional:\n" +
    "  --out <directory>    custom output directory"
  );
  process.exit(2);
}

main().catch((e) => {
  log.error("Pipeline failed", e);
  process.exit(1);
});
