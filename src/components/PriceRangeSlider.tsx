"use client";

import { useCallback } from "react";
import type { Locale } from "@/types/database";

interface Props {
  min: number;
  max: number;
  value: [number, number];
  onChange: (range: [number, number]) => void;
  locale: Locale;
}

function fmt(n: number, locale: Locale) {
  return locale === "en" ? `€${n}` : `${n} €`;
}

export function PriceRangeSlider({ min, max, value, onChange, locale }: Props) {
  const [lo, hi] = value;

  const handleLo = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const v = Math.min(Number(e.target.value), hi - 1);
      onChange([v, hi]);
    },
    [hi, onChange],
  );

  const handleHi = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const v = Math.max(Number(e.target.value), lo + 1);
      onChange([lo, v]);
    },
    [lo, onChange],
  );

  // Percentage positions for the filled track
  const loP = ((lo - min) / (max - min)) * 100;
  const hiP = ((hi - min) / (max - min)) * 100;

  return (
    <div className="flex flex-col gap-1 min-w-[180px]">
      <div className="flex items-center justify-between text-xs font-semibold text-stone-600">
        <span>{fmt(lo, locale)}</span>
        <span className="text-stone-400 text-[10px] uppercase tracking-wide">–</span>
        <span>{fmt(hi, locale)}</span>
      </div>

      {/* Slider track container */}
      <div className="relative h-5 flex items-center">
        {/* Background track */}
        <div className="absolute inset-x-0 h-1.5 rounded-full bg-stone-200" />
        {/* Filled range */}
        <div
          className="absolute h-1.5 rounded-full bg-amber-400"
          style={{ left: `${loP}%`, right: `${100 - hiP}%` }}
        />
        {/* Low thumb */}
        <input
          type="range"
          min={min}
          max={max}
          value={lo}
          onChange={handleLo}
          className="absolute inset-0 w-full appearance-none bg-transparent [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-amber-500 [&::-webkit-slider-thumb]:shadow-md [&::-webkit-slider-thumb]:cursor-pointer [&::-webkit-slider-thumb]:hover:scale-110 [&::-webkit-slider-thumb]:transition-transform [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-white [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-amber-500 [&::-moz-range-thumb]:cursor-pointer"
          style={{ zIndex: lo > max - (max - min) * 0.1 ? 5 : 3 }}
        />
        {/* High thumb */}
        <input
          type="range"
          min={min}
          max={max}
          value={hi}
          onChange={handleHi}
          className="absolute inset-0 w-full appearance-none bg-transparent [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-amber-500 [&::-webkit-slider-thumb]:shadow-md [&::-webkit-slider-thumb]:cursor-pointer [&::-webkit-slider-thumb]:hover:scale-110 [&::-webkit-slider-thumb]:transition-transform [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-white [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-amber-500 [&::-moz-range-thumb]:cursor-pointer"
          style={{ zIndex: 4 }}
        />
      </div>
    </div>
  );
}
