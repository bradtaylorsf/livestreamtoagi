import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Press_Start_2P } from "next/font/google";
import Navigation from "@/components/Navigation";
import "./globals.css";

const pixelFont = Press_Start_2P({
  weight: "400",
  subsets: ["latin"],
  variable: "--font-pixel",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Livestream to AGI",
  description:
    "A 24/7 livestreamed AI reality show — 9 agents, one pixel art world, infinite drama.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <html lang="en" className={`h-full ${pixelFont.variable}`}>
      <body className="min-h-full flex flex-col bg-background text-foreground font-sans antialiased">
        <Navigation />
        <main className="flex-1">{children}</main>
      </body>
    </html>
  );
}
