import type { Metadata } from "next";
import { AuthProvider } from "@/lib/useAuth";
import "./globals.css";

export const metadata: Metadata = {
  title: "Shotgun — On-Call Copilot",
  description:
    "A voice-driven on-call copilot that triages, fixes, and proves the fix in a Kiro → Kane closed loop.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
