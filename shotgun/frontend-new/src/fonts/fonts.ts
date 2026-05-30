import localFont from "next/font/local";
import { Geist_Mono } from "next/font/google";

// Season Sans (DP Trial) — primary brand sans-serif.
export const seasonSans = localFont({
  src: [
    { path: "./season-sans/SeasonSans-Light.woff2", weight: "300", style: "normal" },
    { path: "./season-sans/SeasonSans-Regular.woff2", weight: "400", style: "normal" },
    { path: "./season-sans/SeasonSans-Medium.woff2", weight: "500", style: "normal" },
    { path: "./season-sans/SeasonSans-Bold.woff2", weight: "700", style: "normal" },
    { path: "./season-sans/SeasonSans-Heavy.woff2", weight: "800", style: "normal" },
  ],
  variable: "--font-season-sans",
  display: "swap",
});

// Kept around for the landing display.
export const signifier = localFont({
  src: [
    { path: "./signifier/Signifier-Light.otf", weight: "300", style: "normal" },
    { path: "./signifier/Signifier-Regular.otf", weight: "400", style: "normal" },
    { path: "./signifier/Signifier-Medium.otf", weight: "500", style: "normal" },
    { path: "./signifier/Signifier-Bold.otf", weight: "700", style: "normal" },
  ],
  variable: "--font-signifier",
  display: "swap",
});

// ABC Mono substitute.
export const abcMono = Geist_Mono({
  variable: "--font-abc-mono",
  subsets: ["latin"],
});
