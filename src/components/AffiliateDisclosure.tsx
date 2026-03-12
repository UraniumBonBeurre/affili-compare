import { Info } from "lucide-react";
import { useTranslations } from "next-intl";

export function AffiliateDisclosure() {
  const t = useTranslations("site");
  return (
    <div className="w-full bg-amber-50 border-b border-amber-200 px-4 py-2">
      <p className="max-w-5xl mx-auto flex items-start gap-2 text-xs text-amber-800">
        <Info className="w-4 h-4 shrink-0 mt-0.5" />
        {t("affiliateDisclosure")}
      </p>
    </div>
  );
}
