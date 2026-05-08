import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Suspense } from "react";
import { Press_Start_2P } from "next/font/google";
import Navigation from "@/components/Navigation";
import Footer from "@/components/Footer";
import JsonLd from "@/components/JsonLd";
import { SimulationProvider } from "@/lib/SimulationContext";
import "./globals.css";

const pixelFont = Press_Start_2P({
  weight: "400",
  subsets: ["latin"],
  variable: "--font-pixel",
  display: "swap",
  // Tailwind v4 inlines `--font-pixel` at build time, so next/font's preload
  // link is never consumed and the browser logs an "unused preload" warning.
  preload: false,
});

const SITE_URL = "https://livestreamtoagi.com";

export const metadata: Metadata = {
  title: {
    default: "Livestream to AGI",
    template: "%s | Livestream to AGI",
  },
  description:
    "A 24/7 livestreamed AI reality show — 9 agents, one pixel art world, infinite drama.",
  metadataBase: new URL(SITE_URL),
  openGraph: {
    siteName: "Livestream to AGI",
    type: "website",
    locale: "en_US",
  },
  twitter: {
    card: "summary_large_image",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <html lang="en" className={`h-full ${pixelFont.variable}`}>
      <body className="min-h-full flex flex-col bg-background text-foreground font-sans antialiased">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:top-2 focus:left-2 focus:rounded focus:bg-neon-cyan focus:px-4 focus:py-2 focus:text-background focus:font-medium"
        >
          Skip to main content
        </a>
        <JsonLd
          data={{
            "@context": "https://schema.org",
            "@type": "Organization",
            name: "Livestream to AGI",
            url: SITE_URL,
            description:
              "A 24/7 livestreamed AI reality show exploring multi-agent AI dynamics in public.",
          }}
        />
        <Suspense fallback={null}>
          <SimulationProvider>
            <Navigation />
            <main id="main-content" className="flex-1">{children}</main>
          </SimulationProvider>
        </Suspense>
        <Footer />
      </body>
    </html>
  );
}
