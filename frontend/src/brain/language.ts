// The reply-language rule (feature 005, research R-07), the same as brain/assistant/language.py:
// IDs (P003, S004), digits and punctuation are ignored; more Arabic letters than Latin means
// Arabic, more Latin means English; no letters or a tie keeps the previous language.
import type { Language } from "../api/brainTypes";

const IDS = /(?<![A-Za-z0-9])[PS]\d{3,}(?!\d)/g;
const ARABIC_NOT_LETTERS = /[٠-٩۰-۹،؛؟٪-٭]/g;
const ARABIC = /[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]/g;
const LATIN = /[A-Za-z]/g;

export function detectLanguage(text: string, previous: Language | null = null): Language {
  const clean = text.replace(IDS, " ").replace(ARABIC_NOT_LETTERS, "");
  const arabic = (clean.match(ARABIC) ?? []).length;
  const latin = (clean.match(LATIN) ?? []).length;
  if (arabic > latin) return "ar";
  if (latin > arabic) return "en";
  return previous ?? "en";
}

/** `dir` and `lang` for a block of generated (or the manager's) text (FR-001a). */
export function textDirection(language: Language): { dir: "rtl" | "ltr"; lang: Language } {
  return { dir: language === "ar" ? "rtl" : "ltr", lang: language };
}
