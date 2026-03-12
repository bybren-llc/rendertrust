// Copyright (c) 2025 Words To Film By, Inc.
// Licensed under the MIT License. See LICENSE-MIT for details.

import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RenderTrust Community - Node Operator Leaderboard",
  description:
    "View top node operators, network statistics, and join the RenderTrust community powering distributed computation.",
  openGraph: {
    title: "RenderTrust Community",
    description:
      "The trusted network for distributed computation. See our top node operators and network stats.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen flex flex-col">{children}</body>
    </html>
  );
}
