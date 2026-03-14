import Link from "next/link";

interface Props {
  id: string;
  name: string;
  icon: string;
  gradientFrom: string;
  gradientTo: string;
  locale: string;
}

export function CategoryCard({ id, name, icon, gradientFrom, gradientTo, locale }: Props) {
  return (
    <Link
      href={`/${locale}/${id}`}
      className="group relative aspect-[4/3] rounded-2xl overflow-hidden shadow-md hover:shadow-2xl transition-all duration-300 hover:-translate-y-1"
    >
      <div
        className="absolute inset-0 transition-all duration-300 group-hover:brightness-110"
        style={{ background: `linear-gradient(145deg, ${gradientFrom}, ${gradientTo})` }}
      />
      {/* Subtle shimmer overlay */}
      <div className="absolute inset-0 bg-gradient-to-br from-white/10 to-transparent" />

      {/* Content */}
      <div className="relative h-full flex flex-col items-center justify-center gap-2 p-4 text-center">
        <span className="text-4xl sm:text-5xl group-hover:scale-110 transition-transform duration-300 drop-shadow-lg select-none">
          {icon}
        </span>
        <span className="font-playfair font-semibold text-white text-sm sm:text-[15px] leading-tight drop-shadow-sm">
          {name}
        </span>
      </div>

      {/* Bottom hover indicator */}
      <div className="absolute bottom-0 inset-x-0 h-0.5 bg-white/30 scale-x-0 group-hover:scale-x-100 transition-transform duration-300 origin-left" />
    </Link>
  );
}
