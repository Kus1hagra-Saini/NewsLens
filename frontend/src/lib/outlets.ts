/**
 * Static directory of the 15 Indian news publications NewsLens tracks.
 *
 * The slug / name / website fields mirror
 * `backend/src/ingestion/outlets.yaml` so this file stays in sync with
 * ingestion. The `description` field is a short, factual one- or
 * two-sentence editorial note — used only on the `/outlets` directory
 * page. The `rating` field is the publication-level, third-party
 * category from Media Bias/Fact Check, preserved verbatim; NewsLens
 * does NOT generate these labels and does not apply them to any
 * individual article.
 *
 * Keep this list small and additive. If a 16th outlet is added to
 * the ingestion registry, add a matching row here — otherwise the
 * directory just omits it, which is fine.
 */

export type OutletRating = "Left-Center" | "Right-Center" | "Least Biased";

export interface OutletDirectoryEntry {
  slug: string;
  name: string;
  website: string;
  description: string;
  /** External publication-level rating (MBFC). Never an article-level score. */
  rating: OutletRating;
}

export const OUTLET_DIRECTORY: OutletDirectoryEntry[] = [
  {
    slug: "the-hindu",
    name: "The Hindu",
    website: "https://www.thehindu.com",
    description:
      "Chennai-headquartered national English daily with a long tradition of restrained, policy-focused reporting.",
    rating: "Left-Center",
  },
  {
    slug: "times-of-india",
    name: "Times of India",
    website: "https://timesofindia.indiatimes.com",
    description:
      "India's largest-circulation English daily, part of the Times Group, with wide coverage of national and metro news.",
    rating: "Right-Center",
  },
  {
    slug: "indian-express",
    name: "Indian Express",
    website: "https://indianexpress.com",
    description:
      "National daily known for investigative reporting and in-depth political coverage from New Delhi.",
    rating: "Left-Center",
  },
  {
    slug: "ndtv",
    name: "NDTV",
    website: "https://www.ndtv.com",
    description:
      "Delhi-based broadcaster and news website with a strong presence in television and digital reporting.",
    rating: "Right-Center",
  },
  {
    slug: "hindustan-times",
    name: "Hindustan Times",
    website: "https://www.hindustantimes.com",
    description:
      "Delhi-based English daily owned by HT Media, covering national, political and lifestyle news.",
    rating: "Left-Center",
  },
  {
    slug: "india-today",
    name: "India Today",
    website: "https://www.indiatoday.in",
    description:
      "Weekly magazine and digital news site from the India Today Group, with a mix of politics, business and current affairs.",
    rating: "Right-Center",
  },
  {
    slug: "theprint",
    name: "ThePrint",
    website: "https://theprint.in",
    description:
      "Digital-first publication focused on politics, policy and defence, with opinion and reportage from Indian journalists.",
    rating: "Right-Center",
  },
  {
    slug: "livemint",
    name: "LiveMint",
    website: "https://www.livemint.com",
    description:
      "Business and economy news site published by HT Media, covering markets, companies and policy.",
    rating: "Least Biased",
  },
  {
    slug: "economic-times",
    name: "Economic Times",
    website: "https://economictimes.indiatimes.com",
    description:
      "India's leading English-language business daily, part of the Times Group, with heavy focus on markets and corporates.",
    rating: "Right-Center",
  },
  {
    slug: "news18",
    name: "News18",
    website: "https://www.news18.com",
    description:
      "Network18-owned broadcaster and news website covering national, political and regional news in English and Indian languages.",
    rating: "Right-Center",
  },
  {
    slug: "the-wire",
    name: "The Wire",
    website: "https://thewire.in",
    description:
      "Non-profit digital publication focused on long-form political reporting, analysis and investigative journalism.",
    rating: "Left-Center",
  },
  {
    slug: "scroll-in",
    name: "Scroll.in",
    website: "https://scroll.in",
    description:
      "Digital-first magazine covering politics, culture and public affairs, with an emphasis on reportage and commentary.",
    rating: "Left-Center",
  },
  {
    slug: "tribune-india",
    name: "Tribune India",
    website: "https://www.tribuneindia.com",
    description:
      "Chandigarh-based English daily with strong coverage of Punjab, Haryana and Himachal Pradesh alongside national news.",
    rating: "Right-Center",
  },
  {
    slug: "business-standard",
    name: "Business Standard",
    website: "https://www.business-standard.com",
    description:
      "Business and economy daily focused on companies, finance and policy reporting.",
    rating: "Right-Center",
  },
  {
    slug: "financial-express",
    name: "Financial Express",
    website: "https://www.financialexpress.com",
    description:
      "Indian Express Group business daily, covering markets, economy and corporate news.",
    rating: "Right-Center",
  },
];

/**
 * Short, non-prescriptive helper text for each rating, shown as a
 * one-line hint on cards. The wording deliberately avoids any
 * suggestion that NewsLens is making a political claim.
 */
export const OUTLET_RATING_HELPER: Record<OutletRating, string> = {
  "Left-Center":
    "External rating. Leans slightly toward progressive editorial positions overall.",
  "Right-Center":
    "External rating. Leans slightly toward conservative editorial positions overall.",
  "Least Biased":
    "External rating. Minimal detectable lean in overall editorial positions.",
};
