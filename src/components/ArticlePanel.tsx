"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";

interface Props {
  children: React.ReactNode;
  bgImage?: string | null;
  backLabel: string;
}

export function ArticlePanel({ children, bgImage: _bgImage, backLabel }: Props) {
  const router = useRouter();
  const [entered, setEntered] = useState(false);
  const [exiting, setExiting] = useState(false);

  useEffect(() => {
    const raf = requestAnimationFrame(() => setEntered(true));
    return () => cancelAnimationFrame(raf);
  }, []);

  const handleBack = useCallback(() => {
    if (exiting) return;
    setExiting(true);
    setTimeout(() => router.back(), 420);
  }, [exiting, router]);

  const isVisible = entered && !exiting;

  return (
    <>
      {/* ── Backdrop: blurs everything behind, very slight dark tint ── */}
      <div
        className={`fixed inset-0 z-40 transition-opacity duration-300 ${isVisible ? "opacity-100" : "opacity-0"}`}
        style={{
          background: "rgba(0, 0, 0, 0.18)",
          backdropFilter: "blur(8px)",
          WebkitBackdropFilter: "blur(8px)",
        }}
        onClick={handleBack}
      />

      {/* ── Centering wrapper — transparent, pointer-events-none ──
           Clicks on gaps (left / right / above the white page) pass through
           to the backdrop above and close the panel.                        ── */}
      <div
        className="fixed inset-x-0 bottom-0 z-50 flex justify-center pointer-events-none"
        style={{ top: "calc(3.5rem + 3rem)" }}
      >
        {/* White narrow page — slides from bottom */}
        <div
          className={`w-full max-w-3xl h-full flex flex-col bg-white rounded-t-2xl overflow-hidden shadow-2xl pointer-events-auto transition-transform duration-[420ms] ease-[cubic-bezier(0.32,0.72,0,1)] ${isVisible ? "translate-y-0" : "translate-y-full"}`}
        >
          {/* Back button — thin strip, same width as white page, ~1cm tall */}
          <div className="flex-none border-b border-stone-100 px-4 h-9 flex items-center">
            <button
              onClick={handleBack}
              className="flex items-center gap-1.5 text-xs font-medium text-stone-400 hover:text-stone-700 transition-colors group"
            >
              <span className="group-hover:-translate-x-0.5 transition-transform">←</span>
              <span>{backLabel}</span>
            </button>
          </div>

          {/* Scrollable white content */}
          <div className="flex-1 overflow-y-auto">
            {children}
          </div>
        </div>
      </div>
    </>
  );
}
