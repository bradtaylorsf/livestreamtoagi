import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Press_Start_2P } from "next/font/google";
import Navigation from "@/components/Navigation";
import Footer from "@/components/Footer";
import JsonLd from "@/components/JsonLd";
import "./globals.css";

const pixelFont = Press_Start_2P({
  weight: "400",
  subsets: ["latin"],
  variable: "--font-pixel",
  display: "swap",
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
        <Navigation />
        <main className="flex-1">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
