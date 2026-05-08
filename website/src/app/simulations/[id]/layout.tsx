"use client";

import { use } from "react";
import { SimulationProvider } from "@/lib/SimulationContext";

interface Props {
  params: Promise<{ id: string }>;
  children: React.ReactNode;
}

export default function SimulationScopedLayout({ params, children }: Props) {
  const { id } = use(params);
  return (
    <SimulationProvider routeSimulationId={id}>{children}</SimulationProvider>
  );
}
