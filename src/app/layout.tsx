import type { Metadata } from "next";
import { Bebas_Neue, Literata } from "next/font/google";
import { Nav } from "@/components/Nav";
import "./globals.css";

const display = Bebas_Neue({
  weight: "400",
  subsets: ["latin"],
  variable: "--font-display",
});

const body = Literata({
  subsets: ["latin"],
  variable: "--font-body",
});

export const metadata: Metadata = {
  title: "Spielfeld — Bundesliga forecasts",
  description:
    "Walk-forward LightGBM Bundesliga match forecasts with feature ablation, calibration, and player-impact what-ifs.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${display.variable} ${body.variable} antialiased`}>
        <Nav />
        <main>{children}</main>
      </body>
    </html>
  );
}
