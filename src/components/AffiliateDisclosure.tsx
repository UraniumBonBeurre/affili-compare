"use client";
import { useState } from "react";

export function AffiliateDisclosure() {
  const [closed, setClosed] = useState(false);
  if (closed) return null;
  return (
    <div className="w-full bg-white/60 backdrop-blur-sm border-b border-stone-200/40 px-4 py-2 flex items-center justify-between gap-4">
      <p className="text-[11px] text-stone-400 max-w-3xl">
        Ce site contient des liens affiliés. Commission sans surcoût pour vous.
      </p>
      <button
        onClick={() => setClosed(true)}
        className="text-stone-400 hover:text-stone-600 transition-colors text-xs shrink-0"
        aria-label="Fermer"
      >
        ✕
      </button>
    </div>
  );
}
