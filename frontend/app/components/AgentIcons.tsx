"use client";

import { Compass, CaretDoubleRight, Target } from "@phosphor-icons/react";

/** Shared icon family for the three agents, sourced from Phosphor (one
 * family, one stroke weight) instead of hand-rolled SVG paths. Metaphors:
 * direction/planning, forward motion, staying on target — not the
 * brain/bolt/shield cliché trio. */

interface AgentIconProps {
  size?: number;
  className?: string;
}

export function ArchitectIcon({ size = 26, className = "" }: AgentIconProps) {
  return <Compass size={size} weight="regular" className={className} />;
}

export function ExecutorIcon({ size = 26, className = "" }: AgentIconProps) {
  return <CaretDoubleRight size={size} weight="regular" className={className} />;
}

export function BodyguardIcon({ size = 26, className = "" }: AgentIconProps) {
  return <Target size={size} weight="regular" className={className} />;
}
