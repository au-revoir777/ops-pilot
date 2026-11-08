import { GeistSans } from "geist/font/sans";
import type { Metadata } from "next";
import localFont from "next/font/local";
import Script from "next/script";
import { AppShell } from "@/components/layout/app-shell";
import { DEFAULT_PALETTE, paletteBootScript } from "@/lib/themes";
import "./globals.css";
import { Providers } from "./providers";

const jetbrainsMono = localFont({
  src: "../node_modules/@fontsource-variable/jetbrains-mono/files/jetbrains-mono-latin-wght-normal.woff2",
  variable: "--font-jetbrains-mono",
  display: "swap",
  weight: "100 800",
});

export const metadata: Metadata = {
  title: { default: "OpsPilot", template: "%s · OpsPilot" },
  description: "AI SRE copilot: auditable incident investigations over live telemetry.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      data-theme={DEFAULT_PALETTE}
      className={`${GeistSans.variable} ${jetbrainsMono.variable}`}
      suppressHydrationWarning
    >
      <head>
        {/* Applies the saved palette before first paint (no flash). next-themes does the same for dark mode. */}
        <Script id="palette-boot" strategy="beforeInteractive">
          {paletteBootScript}
        </Script>
      </head>
      <body>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
