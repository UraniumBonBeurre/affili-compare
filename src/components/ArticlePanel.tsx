"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";

interface Props {
  children: React.ReactNode;
  bgImage?: string | null;
  backLabel: string;
  onClose?: () => void;
}

export function ArticlePanel({ children, bgImage: _bgImage, backLabel, onClose }: Props) {
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
    setTimeout(() => { if (onClose) onClose(); else router.back(); }, 420);
  }, [exiting, router, onClose]);

  const isVisible = entered && !exiting;

  return (
    <>
      {/* Blur backdrop — z-40 stays below navbar (z-[60]) so navbar remains readable */}
      <div
        className={`fixed inset-0 z-40 transition-opacity duration-300 ${isVisible ? "opacity-100" : "opacity-0"}`}
        style={{ backdropFilter: "blur(10px)", WebkitBackdropFilter: "blur(10px)", background: "rgba(15,10,5,0.25)" }}
        onClick={handleBack}
      />

      {/* Panel wrapper — starts just below the sticky navbar (h-14 = 3.5rem) */}
      <div
        className="fixed inset-x-0 bottom-0 z-50 flex justify-center pointer-events-none"
        style={{ top: "3.5rem" }}
      >
        {/* White sheet — slides from bottom */}
        <div
          className={`w-full max-w-5xl h-full flex flex-col bg-white rounded-t-2xl overflow-hidden shadow-2xl pointer-events-auto transition-transform duration-[420ms] ease-[cubic-bezier(0.32,0.72,0,1)] ${isVisible ? "translate-y-0" : "translate-y-full"}`}
        >
          {/* Drag handle + back button */}
          <div className="flex-none border-b border-stone-100 px-4 h-10 flex items-center gap-3">
            <div className="w-8 h-1 bg-stone-200 rounded-full mx-auto absolute left-1/2 -translate-x-1/2 top-2" />
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
