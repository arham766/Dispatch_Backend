import type { Metadata } from "next";
import { seasonSans, signifier, abcMono } from "@/fonts/fonts";
import { AuthProvider } from "@/lib/useAuth";
import "./globals.css";

export const metadata: Metadata = {
  title: "Dispatch",
  description: "The screen an engineer opens after the phone call.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${seasonSans.variable} ${signifier.variable} ${abcMono.variable} h-full antialiased`}
    >
      <body className="min-h-full">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
