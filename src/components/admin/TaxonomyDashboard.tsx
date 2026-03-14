"use client";

import { useState, useEffect, useRef } from "react";
import type { SiteCategory, SiteNiche, ProductTypeItem, NicheProductTypesMap } from "@/lib/site-categories";

const fmt = (n: number) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, "\u00a0");
const inp: React.CSSProperties = { fontSize: 12, border: "1px solid #d1d5db", borderRadius: 4, padding: "2px 6px", minWidth: 0, fontFamily: "inherit" };

// ── Types ─────────────────────────────────────────────────────────────────────

type TypeCounts = Record<string, number>;
type NicheStats = { total: number; types: TypeCounts };
type CatStats   = { total: number; niches: Record<string, NicheStats> };
type StatsMap   = Record<string, CatStats>;

interface ProductItem {
  id: string;
  name: string;
  brand: string | null;
  description: string | null;
  price: number | null;
  affiliate_url: string | null;
}

interface Suggestion {
  category:     { id: string; name: string };
  niche:        { slug: string; name: string };
  product_type: { id: string; name_fr: string };
}

type AltPath = {
  category:     { id: string; name: string };
  niche:        { slug: string; name: string };
  product_type: { id: string; name_fr: string };
};

type MerchantStat = { key: string; name: string; total: number; classified: number; has_embedding: number };
type StatsData = {
  total: number; active: number; classified: number; unclassified: number;
  has_embedding: number; needs_embedding: number; inactive: number;
  merchants: MerchantStat[];
};

type BrowseProduct = {
  id: string; name: string; brand: string; merchant: string;
  price: number | null; llm_category: string | null; llm_niche: string | null;
  active: boolean | null; has_embedding: boolean;
};

interface PendingItem {
  product: { id: string; name: string; brand: string; description: string };
  current: { category_id: string; niche_slug: string; type_id: string };
  alts:    AltPath[];
}

interface VerifyProgress {
  ok:     number;
  moved:  number;
  unsure: number;
  total:  number;
  done:   number;
}

interface VerifySummary {
  ok:     number;
  moved:  number;
  unsure: number;
  total:  number;
}

interface Props {
  categories:        SiteCategory[];
  nicheProductTypes: NicheProductTypesMap;
  stats:             StatsMap;
  total:             number;
  classified:        number;
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function putCats(cats: SiteCategory[]) {
  await fetch("/api/admin/taxonomy/categories", {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ categories: cats }),
  });
}

async function putNpt(npt: NicheProductTypesMap) {
  await fetch("/api/admin/taxonomy/niche-product-types", {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(npt),
  });
}

// ── Badge ─────────────────────────────────────────────────────────────────────

function Badge({ count }: { count: number }) {
  const bg = count > 20 ? "#16a34a" : count > 0 ? "#ca8a04" : "#dc2626";
  return (
    <span style={{ display: "inline-block", minWidth: 32, padding: "1px 8px", borderRadius: 9999, fontSize: 12, fontWeight: 700, color: "#fff", background: bg, textAlign: "center" }}>
      {count}
    </span>
  );
}

// ── Btn (icône action, stopPropagation) ──────────────────────────────────────

function Btn({ label, title, color = "#9ca3af", onClick }: {
  label: string; title: string; color?: string;
  onClick: (e: React.MouseEvent) => void;
}) {
  return (
    <button
      onClick={(e) => { e.stopPropagation(); onClick(e); }}
      title={title}
      style={{ background: "none", border: "none", cursor: "pointer", padding: "1px 5px", fontSize: 13, color, lineHeight: 1, flexShrink: 0 }}
    >
      {label}
    </button>
  );
}

// ── ProductItemRow ────────────────────────────────────────────────────────────

function ProductItemRow({ product, catId, nicheSlug, typeId, isEven }: {
  product: ProductItem; catId: string; nicheSlug: string; typeId: string; isEven: boolean;
}) {
  const [loading, setLoading]       = useState(false);
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null);
  const [error, setError]           = useState<string | null>(null);

  async function askReclassify() {
    setLoading(true); setSuggestion(null); setError(null);
    try {
      const res = await fetch("/api/admin/products/reclassify", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: product.name, brand: product.brand, description: product.description }),
      });
      const data = await res.json();
      if (data.error) { setError(data.error); } else { setSuggestion(data); }
    } catch { setError("Erreur réseau"); }
    setLoading(false);
  }

  async function applyReclassify() {
    if (!suggestion) return;
    const res = await fetch("/api/admin/products", {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: product.id, llm_category: suggestion.category.id, llm_niche: suggestion.niche.slug, llm_product_type: suggestion.product_type.id }),
    });
    const data = await res.json();
    if (data.error) { setError(data.error); return; }
    window.location.reload();
  }

  const isSamePlace = suggestion &&
    suggestion.category.id === catId &&
    suggestion.niche.slug  === nicheSlug &&
    suggestion.product_type.id === typeId;

  return (
    <div style={{ background: isEven ? "#fff" : "#fafafa", borderTop: !isEven ? "none" : "1px solid #f3f4f6" }}>
      {/* Main row */}
      <div style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "6px 10px" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 500, color: "#111827", overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis" }}>
            {product.name}
            {product.brand && <span style={{ fontWeight: 400, color: "#6b7280", marginLeft: 8 }}>{product.brand}</span>}
            {product.price != null && <span style={{ color: "#059669", marginLeft: 8, fontWeight: 600 }}>{product.price} €</span>}
          </div>
          {product.description && (
            <div style={{ fontSize: 11, color: "#9ca3af", marginTop: 1, overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" } as React.CSSProperties}>
              {product.description.slice(0, 300)}
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 4, flexShrink: 0, alignItems: "center" }}>
          <button
            onClick={askReclassify}
            disabled={loading}
            title="Demander à Gemini de recatégoriser ce produit"
            style={{ fontSize: 13, background: "none", border: "1px solid #d1d5db", borderRadius: 4, cursor: loading ? "wait" : "pointer", padding: "1px 6px", color: loading ? "#9ca3af" : "#6b7280" }}
          >
            {loading ? "…" : "↻"}
          </button>
          {product.affiliate_url && (
            <a href={product.affiliate_url} target="_blank" rel="noopener noreferrer"
              style={{ fontSize: 11, color: "#2563eb", textDecoration: "none", padding: "2px 8px", border: "1px solid #bfdbfe", borderRadius: 4, whiteSpace: "nowrap" }}>
              Voir →
            </a>
          )}
        </div>
      </div>
      {/* Error */}
      {error && (
        <div style={{ padding: "4px 10px 6px", fontSize: 11, color: "#dc2626" }}>{error}</div>
      )}
      {/* Suggestion panel */}
      {suggestion && (
        <div style={{ margin: "0 10px 8px", padding: "8px 12px", border: `1px solid ${isSamePlace ? "#d1d5db" : "#86efac"}`, borderRadius: 6, background: isSamePlace ? "#f9fafb" : "#f0fdf4" }}>
          {isSamePlace ? (
            <div style={{ fontSize: 12, color: "#6b7280" }}>
              ✓ Gemini confirme l'emplacement actuel : <strong>{suggestion.category.name}</strong> › <strong>{suggestion.niche.name}</strong> › <strong>{suggestion.product_type.name_fr}</strong>
              <button onClick={() => setSuggestion(null)} style={{ marginLeft: 10, fontSize: 11, background: "none", border: "none", color: "#9ca3af", cursor: "pointer" }}>✕</button>
            </div>
          ) : (
            <>
              <div style={{ fontSize: 12, color: "#374151", marginBottom: 6 }}>
                <span style={{ color: "#9ca3af" }}>Actuel :</span> <span style={{ fontFamily: "monospace", fontSize: 11 }}>{catId} › {nicheSlug} › {typeId}</span>
              </div>
              <div style={{ fontSize: 12, color: "#111827", marginBottom: 8 }}>
                <span style={{ color: "#16a34a", fontWeight: 600 }}>Gemini suggère :</span>{" "}
                <strong>{suggestion.category.name}</strong>
                {" › "}
                <strong>{suggestion.niche.name}</strong>
                {" › "}
                <strong>{suggestion.product_type.name_fr}</strong>
                <span style={{ color: "#9ca3af", fontSize: 11, marginLeft: 6 }}>({suggestion.category.id} › {suggestion.niche.slug} › {suggestion.product_type.id})</span>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button onClick={applyReclassify}
                  style={{ fontSize: 12, background: "#16a34a", color: "#fff", border: "none", borderRadius: 4, padding: "3px 12px", cursor: "pointer", fontWeight: 600 }}>
                  ✓ Valider
                </button>
                <button onClick={() => setSuggestion(null)}
                  style={{ fontSize: 12, background: "none", color: "#dc2626", border: "1px solid #fca5a5", borderRadius: 4, padding: "3px 12px", cursor: "pointer" }}>
                  ✕ Ignorer
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── ProductList ───────────────────────────────────────────────────────────────

function ProductList({ catId, nicheSlug, typeId }: { catId: string; nicheSlug: string; typeId: string }) {
  const [items, setItems] = useState<ProductItem[] | null>(null);

  useEffect(() => {
    fetch(`/api/admin/products?category=${encodeURIComponent(catId)}&niche=${encodeURIComponent(nicheSlug)}&type=${encodeURIComponent(typeId)}`)
      .then(r => r.json())
      .then(setItems)
      .catch(() => setItems([]));
  }, [catId, nicheSlug, typeId]);

  if (!items) return <div style={{ padding: "8px 0 8px 56px", fontSize: 12, color: "#9ca3af" }}>Chargement…</div>;
  if (!items.length) return <div style={{ padding: "8px 0 8px 56px", fontSize: 12, color: "#9ca3af" }}>Aucun produit trouvé</div>;

  return (
    <div style={{ margin: "2px 8px 4px 56px", border: "1px solid #f3f4f6", borderRadius: 6, overflow: "hidden" }}>
      {items.map((p, i) => (
        <ProductItemRow
          key={p.id}
          product={p}
          catId={catId}
          nicheSlug={nicheSlug}
          typeId={typeId}
          isEven={i % 2 === 0}
        />
      ))}
    </div>
  );
}

// ── TypeRow ───────────────────────────────────────────────────────────────────

function TypeRow({ type, count, catId, nicheSlug, onEdit, onDelete }: {
  type: ProductTypeItem; count: number; catId: string; nicheSlug: string;
  onEdit: (updated: ProductTypeItem) => void;
  onDelete: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [f, setF] = useState(type);

  if (editing) return (
    <div style={{ display: "flex", gap: 4, alignItems: "center", padding: "3px 4px 3px 40px", background: "#fffbeb" }}>
      <input style={{ ...inp, width: 130 }} placeholder="id" value={f.id} onChange={e => setF(v => ({ ...v, id: e.target.value }))} />
      <input style={{ ...inp, width: 130 }} placeholder="Nom FR" value={f.name_fr} onChange={e => setF(v => ({ ...v, name_fr: e.target.value }))} />
      <input style={{ ...inp, flex: 1 }} placeholder="Nom EN" value={f.name_en} onChange={e => setF(v => ({ ...v, name_en: e.target.value }))} />
      <Btn label="✓" title="Sauvegarder" color="#16a34a" onClick={() => { onEdit(f); setEditing(false); }} />
      <Btn label="✕" title="Annuler" color="#dc2626" onClick={() => { setF(type); setEditing(false); }} />
    </div>
  );

  return (
    <div>
      <div onClick={() => setOpen(v => !v)} style={{ display: "flex", alignItems: "center", gap: 8, padding: "3px 4px 3px 40px", cursor: "pointer" }}>
        <span style={{ fontSize: 10, color: "#9ca3af", width: 10, flexShrink: 0 }}>{open ? "▾" : "▸"}</span>
        <span style={{ fontSize: 12, color: "#374151", flex: 1 }}>{type.name_fr}</span>
        <span style={{ fontSize: 11, color: "#9ca3af", fontFamily: "monospace" }}>({type.id})</span>
        <Badge count={count} />
        <Btn label="✎" title="Modifier" onClick={() => { setF(type); setEditing(true); }} />
        <Btn label="✕" title="Supprimer" color="#dc2626" onClick={onDelete} />
      </div>
      {open && <ProductList catId={catId} nicheSlug={nicheSlug} typeId={type.id} />}
    </div>
  );
}

// ── NicheRow ──────────────────────────────────────────────────────────────────

function NicheRow({ niche, types, stats, catId, onEdit, onDelete, onAddType, onEditType, onDeleteType }: {
  niche: SiteNiche; types: ProductTypeItem[]; stats: NicheStats | undefined; catId: string;
  onEdit: (updated: SiteNiche) => void;
  onDelete: () => void;
  onAddType: (t: ProductTypeItem) => void;
  onEditType: (oldId: string, t: ProductTypeItem) => void;
  onDeleteType: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [f, setF] = useState(niche);
  const [newT, setNewT] = useState<ProductTypeItem>({ id: "", name_fr: "", name_en: "" });
  const count = stats?.total ?? 0;

  if (editing) return (
    <div style={{ display: "flex", gap: 4, alignItems: "center", padding: "4px 4px 4px 16px", background: "#fffbeb" }}>
      <input style={{ ...inp, width: 130 }} placeholder="slug" value={f.slug} onChange={e => setF(v => ({ ...v, slug: e.target.value }))} />
      <input style={{ ...inp, width: 130 }} placeholder="Nom FR" value={f.name} onChange={e => setF(v => ({ ...v, name: e.target.value }))} />
      <input style={{ ...inp, flex: 1 }} placeholder="Nom EN" value={f.name_en} onChange={e => setF(v => ({ ...v, name_en: e.target.value }))} />
      <Btn label="✓" title="Sauvegarder" color="#16a34a" onClick={() => { onEdit(f); setEditing(false); }} />
      <Btn label="✕" title="Annuler" color="#dc2626" onClick={() => { setF(niche); setEditing(false); }} />
    </div>
  );

  return (
    <div>
      <div onClick={() => setOpen(v => !v)} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 4px 5px 16px", cursor: "pointer", userSelect: "none" }}>
        <span style={{ fontSize: 11, color: "#9ca3af", width: 12, flexShrink: 0 }}>{open ? "▾" : "▸"}</span>
        <span style={{ fontSize: 13, color: "#374151", flex: 1 }}>{niche.name}</span>
        <span style={{ fontSize: 11, color: "#9ca3af", fontFamily: "monospace" }}>({niche.slug})</span>
        <span style={{ fontSize: 11, color: "#9ca3af" }}>{types.length} types</span>
        <Badge count={count} />
        <Btn label="✎" title="Modifier la niche" onClick={() => { setF(niche); setEditing(true); }} />
        <Btn label="✕" title="Supprimer la niche" color="#dc2626" onClick={onDelete} />
      </div>
      {open && (
        <div style={{ borderLeft: "2px solid #e5e7eb", marginLeft: 24 }}>
          {types.map(t => (
            <TypeRow
              key={t.id}
              type={t}
              count={stats?.types[t.id] ?? 0}
              catId={catId}
              nicheSlug={niche.slug}
              onEdit={(updated) => onEditType(t.id, updated)}
              onDelete={() => onDeleteType(t.id)}
            />
          ))}
          {addOpen ? (
            <div style={{ display: "flex", gap: 4, alignItems: "center", padding: "3px 4px 3px 40px", background: "#f0fdf4" }}>
              <input style={{ ...inp, width: 120 }} placeholder="id" value={newT.id} onChange={e => setNewT(v => ({ ...v, id: e.target.value }))} />
              <input style={{ ...inp, width: 120 }} placeholder="Nom FR" value={newT.name_fr} onChange={e => setNewT(v => ({ ...v, name_fr: e.target.value }))} />
              <input style={{ ...inp, flex: 1 }} placeholder="Nom EN" value={newT.name_en} onChange={e => setNewT(v => ({ ...v, name_en: e.target.value }))} />
              <Btn label="✓" title="Ajouter" color="#16a34a" onClick={() => {
                if (newT.id && newT.name_fr) { onAddType(newT); setNewT({ id: "", name_fr: "", name_en: "" }); setAddOpen(false); }
              }} />
              <Btn label="✕" title="Annuler" color="#dc2626" onClick={() => setAddOpen(false)} />
            </div>
          ) : (
            <button onClick={(e) => { e.stopPropagation(); setAddOpen(true); }}
              style={{ background: "none", border: "none", cursor: "pointer", fontSize: 11, color: "#16a34a", padding: "3px 0 3px 40px", display: "block" }}>
              + Ajouter un type de produit
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── CategoryRow ───────────────────────────────────────────────────────────────

function CategoryRow({ cat, stats, npt, onEdit, onDelete, onAddNiche, onEditNiche, onDeleteNiche, onAddType, onEditType, onDeleteType }: {
  cat: SiteCategory; stats: CatStats | undefined; npt: NicheProductTypesMap;
  onEdit: (patch: Pick<SiteCategory, "id" | "name" | "name_en" | "icon">) => void;
  onDelete: () => void;
  onAddNiche: (n: SiteNiche) => void;
  onEditNiche: (oldSlug: string, n: SiteNiche) => void;
  onDeleteNiche: (slug: string) => void;
  onAddType: (nicheSlug: string, t: ProductTypeItem) => void;
  onEditType: (nicheSlug: string, oldId: string, t: ProductTypeItem) => void;
  onDeleteType: (nicheSlug: string, id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [f, setF] = useState({ id: cat.id, name: cat.name, name_en: cat.name_en, icon: cat.icon });
  const [newN, setNewN] = useState<SiteNiche>({ slug: "", name: "", name_en: "" });
  const count = stats?.total ?? 0;
  const totalTypes = cat.niches.reduce((s, n) => s + (npt[n.slug]?.length ?? 0), 0);

  if (editing) return (
    <div style={{ marginBottom: 4, border: "1px solid #fbbf24", borderRadius: 8, background: "#fffbeb", padding: "10px 12px", display: "flex", gap: 6, alignItems: "center" }}>
      <input style={{ ...inp, width: 38 }} placeholder="🏷" value={f.icon} onChange={e => setF(v => ({ ...v, icon: e.target.value }))} />
      <input style={{ ...inp, width: 140 }} placeholder="id" value={f.id} onChange={e => setF(v => ({ ...v, id: e.target.value }))} />
      <input style={{ ...inp, width: 150 }} placeholder="Nom FR" value={f.name} onChange={e => setF(v => ({ ...v, name: e.target.value }))} />
      <input style={{ ...inp, flex: 1 }} placeholder="Nom EN" value={f.name_en} onChange={e => setF(v => ({ ...v, name_en: e.target.value }))} />
      <Btn label="✓" title="Sauvegarder" color="#16a34a" onClick={() => { onEdit(f); setF(f); setEditing(false); }} />
      <Btn label="✕" title="Annuler" color="#dc2626" onClick={() => { setF({ id: cat.id, name: cat.name, name_en: cat.name_en, icon: cat.icon }); setEditing(false); }} />
    </div>
  );

  return (
    <div style={{ marginBottom: 4, border: "1px solid #e5e7eb", borderRadius: 8, background: "#fff" }}>
      <div onClick={() => setOpen(v => !v)} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px 10px 16px", cursor: "pointer", userSelect: "none", borderRadius: 8 }}>
        <span style={{ fontSize: 18 }}>{cat.icon}</span>
        <span style={{ fontWeight: 600, fontSize: 15, color: "#111827", flex: 1 }}>{cat.name}</span>
        <span style={{ fontSize: 11, color: "#9ca3af" }}>{cat.niches.length} niches · {totalTypes} types</span>
        <span style={{ fontSize: 11, color: "#9ca3af", fontFamily: "monospace" }}>({cat.id})</span>
        <Badge count={count} />
        <Btn label="✎" title="Modifier la catégorie" onClick={() => { setF({ id: cat.id, name: cat.name, name_en: cat.name_en, icon: cat.icon }); setEditing(true); }} />
        <Btn label="✕" title="Supprimer la catégorie" color="#dc2626" onClick={onDelete} />
        <span style={{ fontSize: 12, color: "#9ca3af" }}>{open ? "▲" : "▼"}</span>
      </div>
      {open && (
        <div style={{ borderTop: "1px solid #f3f4f6", padding: "4px 0 8px" }}>
          {cat.niches.map(n => (
            <NicheRow
              key={n.slug}
              niche={n}
              types={npt[n.slug] ?? []}
              stats={stats?.niches[n.slug]}
              catId={cat.id}
              onEdit={(updated) => onEditNiche(n.slug, updated)}
              onDelete={() => onDeleteNiche(n.slug)}
              onAddType={(t) => onAddType(n.slug, t)}
              onEditType={(oldId, t) => onEditType(n.slug, oldId, t)}
              onDeleteType={(id) => onDeleteType(n.slug, id)}
            />
          ))}
          {addOpen ? (
            <div style={{ display: "flex", gap: 4, alignItems: "center", padding: "4px 4px 4px 16px", background: "#f0fdf4" }}>
              <input style={{ ...inp, width: 130 }} placeholder="slug" value={newN.slug} onChange={e => setNewN(v => ({ ...v, slug: e.target.value }))} />
              <input style={{ ...inp, width: 130 }} placeholder="Nom FR" value={newN.name} onChange={e => setNewN(v => ({ ...v, name: e.target.value }))} />
              <input style={{ ...inp, flex: 1 }} placeholder="Nom EN" value={newN.name_en} onChange={e => setNewN(v => ({ ...v, name_en: e.target.value }))} />
              <Btn label="✓" title="Ajouter" color="#16a34a" onClick={() => {
                if (newN.slug && newN.name) { onAddNiche(newN); setNewN({ slug: "", name: "", name_en: "" }); setAddOpen(false); }
              }} />
              <Btn label="✕" title="Annuler" color="#dc2626" onClick={() => setAddOpen(false)} />
            </div>
          ) : (
            <button onClick={(e) => { e.stopPropagation(); setAddOpen(true); }}
              style={{ background: "none", border: "none", cursor: "pointer", fontSize: 11, color: "#16a34a", padding: "2px 0 2px 16px", display: "block" }}>
              + Ajouter une niche
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── ProductSearch ─────────────────────────────────────────────────────────────

type SearchResult = {
  id: string;
  name: string;
  brand: string | null;
  llm_category: string | null;
  llm_niche: string | null;
  llm_product_type: string | null;
};

function ProductSearch({ categories, npt }: { categories: SiteCategory[]; npt: NicheProductTypesMap }) {
  const [query, setQuery]     = useState("");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function lookupNames(r: SearchResult) {
    const catObj   = categories.find(c => c.id === r.llm_category);
    const nicheObj = catObj?.niches.find(n => n.slug === r.llm_niche);
    const typeObj  = npt[r.llm_niche ?? ""]?.find(t => t.id === r.llm_product_type);
    return {
      catName:   catObj?.name   ?? r.llm_category   ?? "—",
      nicheName: nicheObj?.name ?? r.llm_niche       ?? "—",
      typeName:  typeObj?.name_fr ?? r.llm_product_type ?? "—",
    };
  }

  function doSearch(q: string) {
    if (q.length < 2) { setResults(null); setLoading(false); return; }
    setLoading(true);
    fetch(`/api/admin/product-search?q=${encodeURIComponent(q)}`)
      .then(r => r.json())
      .then(data => { setResults(data); setLoading(false); })
      .catch(() => { setResults([]); setLoading(false); });
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const q = e.target.value;
    setQuery(q);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => doSearch(q), 300);
  }

  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ position: "relative" }}>
        <input
          type="text"
          value={query}
          onChange={handleChange}
          placeholder="Rechercher un produit par nom…"
          style={{ width: "100%", padding: "8px 12px 8px 34px", fontSize: 13, border: "1px solid #d1d5db", borderRadius: 8, outline: "none", boxSizing: "border-box", background: "#fff", fontFamily: "inherit" }}
        />
        <span style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "#9ca3af", pointerEvents: "none" }}>🔍</span>
        {loading && <span style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", fontSize: 11, color: "#9ca3af" }}>…</span>}
      </div>
      {results && results.length === 0 && !loading && (
        <div style={{ padding: "6px 4px", fontSize: 12, color: "#9ca3af" }}>Aucun résultat pour « {query} »</div>
      )}
      {results && results.length > 0 && (
        <div style={{ marginTop: 6, border: "1px solid #e5e7eb", borderRadius: 8, overflow: "hidden", background: "#fff" }}>
          {results.map((r, i) => {
            const { catName, nicheName, typeName } = lookupNames(r);
            return (
              <div key={r.id} style={{ padding: "8px 12px", borderTop: i > 0 ? "1px solid #f3f4f6" : "none" }}>
                <div style={{ fontSize: 13, fontWeight: 500, color: "#111827" }}>
                  {r.name}
                  {r.brand && <span style={{ fontWeight: 400, color: "#6b7280", marginLeft: 6 }}>{r.brand}</span>}
                </div>
                {r.llm_category ? (
                  <div style={{ fontSize: 11, color: "#6b7280", marginTop: 2 }}>
                    <span style={{ color: "#374151", fontWeight: 500 }}>{catName}</span>
                    <span style={{ color: "#d1d5db" }}> › </span>
                    <span style={{ color: "#374151" }}>{nicheName}</span>
                    <span style={{ color: "#d1d5db" }}> › </span>
                    <span style={{ color: "#374151" }}>{typeName}</span>
                    <span style={{ color: "#d1d5db", marginLeft: 8, fontFamily: "monospace", fontSize: 10 }}>
                      {r.llm_category} › {r.llm_niche} › {r.llm_product_type}
                    </span>
                  </div>
                ) : (
                  <div style={{ fontSize: 11, color: "#dc2626", marginTop: 2 }}>Non classifié</div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── VerifyPanel ───────────────────────────────────────────────────────────────

function VerifyPanel() {
  const [status,   setStatus]   = useState<"idle" | "running" | "done" | "error">("idle");
  const [logs,     setLogs]     = useState<string[]>([]);
  const [progress, setProgress] = useState<VerifyProgress | null>(null);
  const [summary,  setSummary]  = useState<VerifySummary | null>(null);
  const [pending,  setPending]  = useState<PendingItem[]>([]);
  const [pendingCount, setPendingCount] = useState<number | null>(null);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    fetch("/api/admin/verify-pending")
      .then(r => r.json())
      .then((d: PendingItem[]) => { setPendingCount(d.length); if (d.length) setPending(d); });
  }, []);

  function startVerify() {
    setStatus("running");
    setLogs([]);
    setProgress(null);
    setSummary(null);

    const es = new EventSource("/api/admin/verify-run");
    esRef.current = es;
    es.onmessage = (e) => {
      const data: { log?: string; err?: string; exit?: number } = JSON.parse(e.data);

      if (data.log) {
        const line = data.log.trim();
        if (!line) return;
        if (line.startsWith("PROGRESS:")) {
          try { setProgress(JSON.parse(line.slice(9))); } catch { /* ignore */ }
        } else if (line.startsWith("DONE:")) {
          try { setSummary(JSON.parse(line.slice(5))); } catch { /* ignore */ }
        } else {
          setLogs(prev => [...prev.slice(-60), line]);
        }
      }

      if (data.err) {
        setLogs(prev => [...prev.slice(-60), `⚠ ${data.err!.trim()}`]);
      }

      if (data.exit !== undefined) {
        es.close(); esRef.current = null;
        setStatus(data.exit === 0 ? "done" : "error");
        fetch("/api/admin/verify-pending")
          .then(r => r.json())
          .then((d: PendingItem[]) => { setPending(d); setPendingCount(d.length); });
      }
    };
    es.onerror = () => { es.close(); esRef.current = null; setStatus("error"); };
  }

  function cancelVerify() {
    esRef.current?.close();
    esRef.current = null;
    setStatus("idle");
    setProgress(null);
    setLogs([]);
  }

  async function applyPending(item: PendingItem, alt: AltPath) {
    const res = await fetch("/api/admin/verify-pending", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        productId:   item.product.id,
        category:    alt.category.id,
        niche:       alt.niche.slug,
        productType: alt.product_type.id,
      }),
    });
    if ((await res.json()).ok) {
      setPending(prev => prev.filter(p => p.product.id !== item.product.id));
      setPendingCount(prev => Math.max(0, (prev ?? 1) - 1));
    }
  }

  async function clearAllPending() {
    if (!confirm("Effacer tous les cas en attente ?")) return;
    await fetch("/api/admin/verify-pending", { method: "DELETE" });
    setPending([]); setPendingCount(0);
  }

  const pct = progress && progress.total > 0
    ? Math.round(100 * progress.done / progress.total)
    : 0;

  return (
    <div style={{ marginTop: 28, border: "1px solid #e5e7eb", borderRadius: 10, overflow: "hidden", background: "#fff" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 16px", borderBottom: "1px solid #f3f4f6", background: "#f9fafb" }}>
        <span style={{ fontSize: 16, fontWeight: 700, color: "#111827" }}>Vérification LLM</span>
        {pendingCount !== null && pendingCount > 0 && (
          <span style={{ fontSize: 11, background: "#fef3c7", color: "#92400e", borderRadius: 9999, padding: "1px 8px", fontWeight: 600 }}>
            {pendingCount} en attente
          </span>
        )}
        <span style={{ marginLeft: "auto", fontSize: 12, color: "#6b7280" }}>
          {status === "idle"    && "Inactif"}
          {status === "running" && "En cours…"}
          {status === "done"    && "Terminé"}
          {status === "error"   && "Erreur"}
        </span>
        <button
          onClick={startVerify}
          disabled={status === "running"}
          style={{
            fontSize: 12, fontWeight: 600, padding: "4px 14px", borderRadius: 5,
            border: "none", cursor: status === "running" ? "wait" : "pointer",
            background: status === "running" ? "#e5e7eb" : "#2563eb",
            color: status === "running" ? "#9ca3af" : "#fff",
          }}
        >
          {status === "running" ? "Vérification en cours…" : "▶ Lancer la vérification"}
        </button>
        {status === "running" && (
          <button onClick={cancelVerify} style={{ fontSize: 12, fontWeight: 600, padding: "4px 12px", borderRadius: 5, border: "1px solid #fca5a5", background: "none", color: "#dc2626", cursor: "pointer" }}>
            ✕ Annuler
          </button>
        )}
      </div>

      {/* Barre de progression colorée */}
      {progress && (
        <div style={{ padding: "10px 16px", borderBottom: "1px solid #f3f4f6" }}>
          <div style={{ display: "flex", gap: 16, fontSize: 11, marginBottom: 6, alignItems: "center" }}>
            <span style={{ color: "#6b7280" }}>{pct}% — {fmt(progress.done)}/{fmt(progress.total)} produits</span>
            <span style={{ color: "#16a34a", fontWeight: 600 }}>✓ {progress.ok} confirmés</span>
            <span style={{ color: "#ea580c", fontWeight: 600 }}>↻ {progress.moved} déplacés</span>
            <span style={{ color: "#dc2626", fontWeight: 600 }}>? {progress.unsure} à choisir</span>
          </div>
          <div style={{ display: "flex", height: 10, borderRadius: 5, overflow: "hidden", background: "#f3f4f6" }}>
            {progress.total > 0 && (
              <>
                <div style={{ width: `${100 * progress.ok     / progress.total}%`, background: "#16a34a", transition: "width 0.4s ease" }} />
                <div style={{ width: `${100 * progress.moved  / progress.total}%`, background: "#ea580c", transition: "width 0.4s ease" }} />
                <div style={{ width: `${100 * progress.unsure / progress.total}%`, background: "#dc2626", transition: "width 0.4s ease" }} />
              </>
            )}
          </div>
        </div>
      )}

      {/* Summary */}
      {summary && (
        <div style={{ display: "flex", gap: 20, padding: "10px 16px", borderBottom: "1px solid #f3f4f6", background: "#f0fdf4", fontSize: 13 }}>
          <span><strong style={{ color: "#16a34a" }}>{summary.ok}</strong> confirmés ({Math.round(100 * summary.ok / Math.max(summary.total, 1))}%)</span>
          <span><strong style={{ color: "#ea580c" }}>{summary.moved}</strong> déplacés automatiquement</span>
          <span><strong style={{ color: "#dc2626" }}>{summary.unsure}</strong> incertains (choix manuel)</span>
          <span style={{ marginLeft: "auto", color: "#6b7280" }}>{summary.total} produits vérifiés</span>
        </div>
      )}

      {/* Live logs (last 8 lines) */}
      {logs.length > 0 && (
        <div style={{ padding: "8px 16px", borderBottom: "1px solid #f3f4f6", background: "#000", maxHeight: 120, overflowY: "auto" }}>
          {logs.slice(-8).map((line, i) => (
            <div key={i} style={{ fontFamily: "monospace", fontSize: 11, color: "#86efac", lineHeight: 1.5 }}>{line}</div>
          ))}
        </div>
      )}

      {/* Pending items for manual review */}
      {pending.length > 0 && (
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 16px", borderBottom: "1px solid #f3f4f6", background: "#fffbeb" }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: "#92400e" }}>
              {pending.length} produit{pending.length > 1 ? "s" : ""} nécessitent un choix manuel
            </span>
            <button onClick={clearAllPending} style={{ marginLeft: "auto", fontSize: 11, color: "#dc2626", background: "none", border: "1px solid #fca5a5", borderRadius: 4, padding: "2px 8px", cursor: "pointer" }}>
              Tout effacer
            </button>
          </div>
          {pending.map(item => (
            <div key={item.product.id} style={{ borderBottom: "1px solid #f3f4f6", padding: "10px 16px" }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#111827", marginBottom: 2 }}>
                {item.product.name}
                {item.product.brand && <span style={{ fontWeight: 400, color: "#6b7280", marginLeft: 6 }}>{item.product.brand}</span>}
              </div>
              {item.product.description && (
                <div style={{ fontSize: 11, color: "#9ca3af", marginBottom: 6 }}>
                  {item.product.description.slice(0, 200)}
                </div>
              )}
              <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 6 }}>
                Actuel : <span style={{ fontFamily: "monospace" }}>{item.current.category_id} › {item.current.niche_slug} › {item.current.type_id}</span>
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {item.alts.map((alt, j) => (
                  <button
                    key={j}
                    onClick={() => applyPending(item, alt)}
                    style={{
                      fontSize: 11, padding: "4px 10px", borderRadius: 5, cursor: "pointer",
                      border: "1px solid #bfdbfe", background: "#eff6ff", color: "#1e40af",
                    }}
                  >
                    {alt.category.name} › {alt.niche.name} › {alt.product_type.name_fr}
                    <span style={{ color: "#93c5fd", marginLeft: 4 }}>({alt.category.id} › {alt.niche.slug} › {alt.product_type.id})</span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {status === "idle" && pending.length === 0 && (
        <div style={{ padding: "16px", fontSize: 12, color: "#9ca3af", textAlign: "center" }}>
          Lance la vérification pour que le LLM contrôle l&apos;ensemble des classifications.
        </div>
      )}
    </div>
  );
}

// ── Stats live ────────────────────────────────────────────────────────────────

function useStats(tick: number) {
  const [data, setData] = useState<StatsData | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    setLoading(true);
    fetch("/api/admin/stats")
      .then(r => r.json())
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [tick]);
  return { data, loading };
}

function StatsPanel({ data: d, loading }: { data: StatsData | null; loading: boolean }) {
  const [merchantsOpen, setMerchantsOpen] = useState(false);
  const pct = (a: number, b: number) => b > 0 ? Math.round(a / b * 100) : 0;

  const card = (label: string, val: number | undefined, sub: string, bg: string, color: string) => (
    <div style={{ flex: 1, minWidth: 130, background: bg, borderRadius: 8, padding: "10px 14px", border: `1px solid ${color}22` }}>
      <div style={{ fontSize: 22, fontWeight: 700, color }}>{fmt(val ?? 0)}</div>
      <div style={{ fontSize: 12, fontWeight: 600, color: "#374151", marginTop: 2 }}>{label}</div>
      {sub && <div style={{ fontSize: 11, color: "#6b7280", marginTop: 1 }}>{sub}</div>}
    </div>
  );

  if (loading && !d) return (
    <div style={{ padding: "12px 16px", color: "#9ca3af", fontSize: 13 }}>Chargement des stats…</div>
  );

  const active = d?.active ?? 0;
  const classifiedPct = pct(d?.classified ?? 0, active);
  const embPct        = pct(d?.has_embedding ?? 0, active);

  return (
    <div style={{ marginBottom: 20, border: "1px solid #e5e7eb", borderRadius: 10, overflow: "hidden", background: "#fff" }}>
      <div style={{ padding: "10px 16px", background: "#f9fafb", borderBottom: "1px solid #f3f4f6", display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 15, fontWeight: 700, color: "#111827", flex: 1 }}>Base de données produits</span>
        {loading && <span style={{ fontSize: 11, color: "#9ca3af" }}>↺</span>}
      </div>

      {/* Metric cards */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", padding: "12px 14px" }}>
        {card("Actifs",          d?.active,          `${d?.inactive ?? 0} inactifs`,                "#eff6ff", "#1d4ed8")}
        {card("Classifiés",      d?.classified,       `${classifiedPct}% des actifs`, classifiedPct >= 90 ? "#f0fdf4" : "#fefce8", classifiedPct >= 90 ? "#16a34a" : "#ca8a04")}
        {card("Non-classés",     d?.unclassified,     "à classer",                    (d?.unclassified ?? 0) > 0 ? "#fef2f2" : "#f0fdf4", (d?.unclassified ?? 0) > 0 ? "#dc2626" : "#16a34a")}
        {card("Sans embedding",  d?.needs_embedding,  `${embPct}% ont l'embedding`,   (d?.needs_embedding ?? 0) > 0 ? "#fffbeb" : "#f0fdf4", (d?.needs_embedding ?? 0) > 0 ? "#d97706" : "#16a34a")}
      </div>

      {/* Merchants table (collapsible) */}
      <div style={{ borderTop: "1px solid #f3f4f6" }}>
        <div onClick={() => setMerchantsOpen(v => !v)}
          style={{ padding: "8px 16px", cursor: "pointer", userSelect: "none", display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "#6b7280" }}>
          <span style={{ fontWeight: 600, color: "#374151" }}>Par marchand</span>
          <span style={{ flex: 1 }} />
          <span>{merchantsOpen ? "▲" : "▼"}</span>
        </div>
        {merchantsOpen && d?.merchants && (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ background: "#f9fafb", borderBottom: "1px solid #e5e7eb" }}>
                  {["Marchand", "Total", "Classifiés", "Embedding"].map(h => (
                    <th key={h} style={{ padding: "6px 14px", textAlign: "left", fontWeight: 600, color: "#374151" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {d.merchants.map((m, i) => (
                  <tr key={m.key} style={{ background: i % 2 === 0 ? "#fff" : "#f9fafb", borderBottom: "1px solid #f3f4f6" }}>
                    <td style={{ padding: "5px 14px", fontWeight: 500, color: "#111827" }}>{m.name}</td>
                    <td style={{ padding: "5px 14px", color: "#374151" }}>{fmt(m.total)}</td>
                    <td style={{ padding: "5px 14px", color: pct(m.classified, m.total) >= 90 ? "#16a34a" : "#ca8a04" }}>
                      {fmt(m.classified)} <span style={{ color: "#9ca3af" }}>({pct(m.classified, m.total)}%)</span>
                    </td>
                    <td style={{ padding: "5px 14px", color: pct(m.has_embedding, m.total) >= 80 ? "#16a34a" : "#d97706" }}>
                      {fmt(m.has_embedding)} <span style={{ color: "#9ca3af" }}>({pct(m.has_embedding, m.total)}%)</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

// ── ProductsBrowser ────────────────────────────────────────────────────────────

function ProductsBrowser({ tick, merchants }: { tick: number; merchants: MerchantStat[] }) {
  const [open, setOpen]               = useState(false);
  const [page, setPage]               = useState(0);
  const [merchant, setMerchant]       = useState("");
  const [unclassified, setUnclassified] = useState(false);
  const [noEmbedding, setNoEmbedding] = useState(false);
  const [products, setProducts]       = useState<BrowseProduct[]>([]);
  const [hasMore, setHasMore]         = useState(false);
  const [loading, setLoading]         = useState(false);
  const fetchTick = `${tick}-${page}-${merchant}-${unclassified}-${noEmbedding}`;

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    const qs = new URLSearchParams({ page: String(page) });
    if (merchant)    qs.set("merchant", merchant);
    if (unclassified) qs.set("unclassified", "1");
    if (noEmbedding)  qs.set("no_embedding", "1");
    fetch(`/api/admin/products-browse?${qs}`)
      .then(r => r.json())
      .then(d => { setProducts(d.products ?? []); setHasMore(d.has_more ?? false); })
      .catch(() => {})
      .finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchTick, open]);

  // Reset page when filters change
  const resetPage = () => setPage(0);

  return (
    <div style={{ marginBottom: 20, border: "1px solid #e5e7eb", borderRadius: 10, overflow: "hidden", background: "#fff" }}>
      <div onClick={() => setOpen(v => !v)}
        style={{ padding: "10px 16px", background: "#f9fafb", borderBottom: open ? "1px solid #f3f4f6" : "none", cursor: "pointer", userSelect: "none", display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 15, fontWeight: 700, color: "#111827", flex: 1 }}>Parcourir les produits</span>
        {loading && <span style={{ fontSize: 11, color: "#9ca3af" }}>↺</span>}
        <span style={{ fontSize: 12, color: "#9ca3af" }}>{open ? "▲" : "▼"}</span>
      </div>

      {open && (
        <>
          {/* Filters */}
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", padding: "10px 14px", borderBottom: "1px solid #f3f4f6", alignItems: "center" }}>
            <label style={{ fontSize: 11, color: "#6b7280", fontWeight: 500, display: "flex", flexDirection: "column", gap: 3 }}>
              Marchand
              <select value={merchant} onChange={e => { setMerchant(e.target.value); resetPage(); }} style={{ ...inp, minWidth: 140 }}>
                <option value="">Tous</option>
                {merchants.map(m => <option key={m.key} value={m.key}>{m.name}</option>)}
              </select>
            </label>
            <label style={{ fontSize: 11, color: "#6b7280", fontWeight: 500, display: "flex", alignItems: "center", gap: 6, marginTop: 12 }}>
              <input type="checkbox" checked={unclassified} onChange={e => { setUnclassified(e.target.checked); resetPage(); }} />
              Non-classés seulement
            </label>
            <label style={{ fontSize: 11, color: "#6b7280", fontWeight: 500, display: "flex", alignItems: "center", gap: 6, marginTop: 12 }}>
              <input type="checkbox" checked={noEmbedding} onChange={e => { setNoEmbedding(e.target.checked); resetPage(); }} />
              Sans embedding
            </label>
          </div>

          {/* Table */}
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ background: "#f9fafb", borderBottom: "1px solid #e5e7eb" }}>
                  {["Nom", "Marque", "Marchand", "Prix", "Catégorie · Niche", "Emb."].map(h => (
                    <th key={h} style={{ padding: "6px 12px", textAlign: "left", fontWeight: 600, color: "#374151", whiteSpace: "nowrap" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {products.length === 0 && !loading && (
                  <tr><td colSpan={6} style={{ padding: "16px", textAlign: "center", color: "#9ca3af" }}>Aucun produit</td></tr>
                )}
                {products.map((p, i) => (
                  <tr key={p.id} style={{ background: i % 2 === 0 ? "#fff" : "#f9fafb", borderBottom: "1px solid #f3f4f6" }}>
                    <td style={{ padding: "5px 12px", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#111827" }} title={p.name}>{p.name}</td>
                    <td style={{ padding: "5px 12px", color: "#374151" }}>{p.brand}</td>
                    <td style={{ padding: "5px 12px", color: "#374151" }}>{p.merchant}</td>
                    <td style={{ padding: "5px 12px", color: "#374151", whiteSpace: "nowrap" }}>{p.price != null ? `${p.price} €` : "—"}</td>
                    <td style={{ padding: "5px 12px", color: p.llm_category ? "#374151" : "#dc2626", fontStyle: p.llm_category ? "normal" : "italic" }}>
                      {p.llm_category ? `${p.llm_category} · ${p.llm_niche}` : "non classé"}
                    </td>
                    <td style={{ padding: "5px 12px", textAlign: "center" }}>
                      <span style={{ color: p.has_embedding ? "#16a34a" : "#9ca3af" }}>{p.has_embedding ? "✓" : "·"}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div style={{ display: "flex", gap: 8, padding: "8px 14px", alignItems: "center", borderTop: "1px solid #f3f4f6" }}>
            <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
              style={{ ...inp, cursor: page === 0 ? "not-allowed" : "pointer", opacity: page === 0 ? 0.4 : 1, padding: "3px 10px" }}>← Préc.</button>
            <span style={{ fontSize: 12, color: "#6b7280" }}>Page {page + 1}</span>
            <button onClick={() => setPage(p => p + 1)} disabled={!hasMore}
              style={{ ...inp, cursor: hasMore ? "pointer" : "not-allowed", opacity: hasMore ? 1 : 0.4, padding: "3px 10px" }}>Suiv. →</button>
          </div>
        </>
      )}
    </div>
  );
}

// ── RunPanel ──────────────────────────────────────────────────────────────────

type FieldDef =
  | { type: "checkbox"; key: string; label: string; defaultVal?: boolean }
  | { type: "text";     key: string; label: string; placeholder?: string }
  | { type: "number";   key: string; label: string; defaultVal?: number; min?: number; max?: number }
  | { type: "select";   key: string; label: string; options: { val: string; label: string }[] };

function RunPanel({ title, icon, script, fields, accentColor, onDone }: {
  title:       string;
  icon:        string;
  script:      string;
  fields:      FieldDef[];
  accentColor: string;
  onDone?:     () => void;
}) {
  const [open,   setOpen]   = useState(false);
  const [status, setStatus] = useState<"idle" | "running" | "done" | "error">("idle");
  const [logs,   setLogs]   = useState<string[]>([]);
  const logRef = useRef<HTMLDivElement>(null);
  const esRef  = useRef<EventSource | null>(null);

  const [values, setValues] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    for (const f of fields) {
      if (f.type === "checkbox") init[f.key] = f.defaultVal ? "1" : "0";
      if (f.type === "number")   init[f.key] = f.defaultVal != null ? String(f.defaultVal) : "";
      if (f.type === "select")   init[f.key] = f.options[0]?.val ?? "";
      if (f.type === "text")     init[f.key] = "";
    }
    return init;
  });

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs]);

  function startRun() {
    const qs = new URLSearchParams({ script });
    for (const [k, v] of Object.entries(values)) {
      if (v !== "" && v !== "0") qs.set(k, v);
    }
    setStatus("running"); setLogs([]);
    const es = new EventSource(`/api/admin/run-script?${qs}`);
    esRef.current = es;
    es.onmessage = (e) => {
      const d: { log?: string; err?: string; exit?: number } = JSON.parse(e.data);
      if (d.log !== undefined) { const l = d.log.trim(); if (l) setLogs(p => [...p.slice(-120), l]); }
      if (d.err !== undefined) { const l = d.err.trim(); if (l) setLogs(p => [...p.slice(-120), `⚠ ${l}`]); }
      if (d.exit !== undefined) {
        es.close(); esRef.current = null;
        setStatus(d.exit === 0 ? "done" : "error");
        if (d.exit === 0) onDone?.();
      }
    };
    es.onerror = () => { es.close(); esRef.current = null; setStatus("error"); };
  }

  function cancel() {
    esRef.current?.close(); esRef.current = null;
    setStatus("idle"); setLogs([]);
  }

  const statusLabel = { idle: "", running: "⟳ en cours…", done: "✓ terminé", error: "✗ erreur" }[status];
  const statusColor = { idle: "#9ca3af", running: "#2563eb", done: "#16a34a", error: "#dc2626" }[status];

  return (
    <div style={{ border: "1px solid #e5e7eb", borderRadius: 8, background: "#fff", marginBottom: 6 }}>
      {/* Header row */}
      <div onClick={() => setOpen(v => !v)}
        style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", cursor: "pointer", userSelect: "none" }}>
        <span style={{ fontSize: 18 }}>{icon}</span>
        <span style={{ fontWeight: 600, fontSize: 14, color: "#111827", flex: 1 }}>{title}</span>
        {statusLabel && <span style={{ fontSize: 11, fontWeight: 600, color: statusColor }}>{statusLabel}</span>}
        <div style={{ display: "flex", gap: 6 }} onClick={e => e.stopPropagation()}>
          {status === "running" ? (
            <button onClick={cancel}
              style={{ fontSize: 11, padding: "3px 10px", border: "1px solid #fca5a5", borderRadius: 4, background: "none", color: "#dc2626", cursor: "pointer" }}>
              ✕ Annuler
            </button>
          ) : (
            <button onClick={startRun}
              style={{ fontSize: 12, fontWeight: 600, padding: "4px 14px", borderRadius: 5, border: "none", cursor: "pointer", background: accentColor, color: "#fff" }}>
              ▶ Lancer
            </button>
          )}
        </div>
        <span style={{ fontSize: 12, color: "#9ca3af" }}>{open ? "▲" : "▼"}</span>
      </div>

      {open && (
        <div style={{ borderTop: "1px solid #f3f4f6" }}>
          {/* Form */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12, padding: "10px 14px 12px", alignItems: "flex-end" }}>
            {fields.map(f => (
              <label key={f.key} style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 11, color: "#6b7280", fontWeight: 500 }}>
                {f.label}
                {f.type === "checkbox" ? (
                  <input type="checkbox" checked={values[f.key] === "1"}
                    onChange={e => setValues(v => ({ ...v, [f.key]: e.target.checked ? "1" : "0" }))}
                    style={{ width: 16, height: 16, marginTop: 2 }} />
                ) : f.type === "select" ? (
                  <select value={values[f.key]} onChange={e => setValues(v => ({ ...v, [f.key]: e.target.value }))}
                    style={{ ...inp, minWidth: 160 }}>
                    {f.options.map(o => <option key={o.val} value={o.val}>{o.label}</option>)}
                  </select>
                ) : f.type === "number" ? (
                  <input type="number" value={values[f.key]} min={f.min} max={f.max}
                    onChange={e => setValues(v => ({ ...v, [f.key]: e.target.value }))}
                    style={{ ...inp, width: 90 }} />
                ) : (
                  <input type="text" value={values[f.key]} placeholder={f.placeholder}
                    onChange={e => setValues(v => ({ ...v, [f.key]: e.target.value }))}
                    style={{ ...inp, width: 140 }} />
                )}
              </label>
            ))}
          </div>

          {/* Log terminal */}
          {logs.length > 0 && (
            <div ref={logRef}
              style={{ background: "#111827", padding: "8px 14px", maxHeight: 220, overflowY: "auto", borderTop: "1px solid #1f2937" }}>
              {logs.slice(-60).map((l, i) => (
                <div key={i} style={{ fontFamily: "monospace", fontSize: 11, lineHeight: 1.6,
                  color: l.startsWith("⚠") ? "#fbbf24" : l.startsWith("$") ? "#93c5fd" : "#86efac" }}>
                  {l}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── OperationsPanel ───────────────────────────────────────────────────────────

function OperationsPanel({ onDone }: { onDone: () => void }) {
  return (
    <div style={{ marginTop: 28, border: "1px solid #e5e7eb", borderRadius: 10, overflow: "hidden", background: "#fff" }}>
      <div style={{ padding: "12px 16px", background: "#f9fafb", borderBottom: "1px solid #f3f4f6" }}>
        <span style={{ fontSize: 16, fontWeight: 700, color: "#111827" }}>Opérations</span>
        <span style={{ fontSize: 12, color: "#9ca3af", marginLeft: 10 }}>Import → Classifier → Embeddings → Liens → Articles</span>
      </div>
      <div style={{ padding: "10px 10px 4px" }}>

        <RunPanel title="Import produits" icon="⬇" script="import" accentColor="#0891b2" onDone={onDone}
          fields={[
            { type: "select",   key: "mode",           label: "Mode",            options: [{ val: "update", label: "Update (incrémental)" }, { val: "reset_and_fill", label: "Reset & Fill" }] },
            { type: "number",   key: "count",          label: "Count (reset)",   defaultVal: 500, min: 1 },
            { type: "number",   key: "limit",          label: "Limite (update)", min: 1 },
            { type: "text",     key: "merchant",       label: "Merchant",        placeholder: "ex: fnac" },
            { type: "checkbox", key: "force_download", label: "Force DL" },
          ]}
        />

        <RunPanel title="Classification LLM" icon="🤖" script="classify" accentColor="#7c3aed" onDone={onDone}
          fields={[
            { type: "checkbox", key: "force",      label: "Tout re-classifier" },
            { type: "number",   key: "batch_size", label: "Batch size",        defaultVal: 500, min: 1 },
            { type: "number",   key: "limit",      label: "Limite produits",   min: 1 },
            { type: "text",     key: "merchant",   label: "Merchant",          placeholder: "ex: fnac" },
          ]}
        />

        <RunPanel title="Embeddings" icon="🔢" script="embeddings" accentColor="#059669" onDone={onDone}
          fields={[
            { type: "checkbox", key: "force", label: "Tout re-générer" },
            { type: "number",   key: "limit", label: "Limite produits", min: 1 },
          ]}
        />

        <RunPanel title="Validation des liens" icon="🔗" script="check-links" accentColor="#ea580c" onDone={onDone}
          fields={[
            { type: "checkbox", key: "dry_run",  label: "Dry run" },
            { type: "number",   key: "workers",  label: "Workers", defaultVal: 20, min: 1, max: 50 },
            { type: "text",     key: "merchant", label: "Merchant", placeholder: "ex: fnac" },
          ]}
        />

        <RunPanel title="Générer des articles" icon="✍️" script="generate-articles" accentColor="#8b5cf6" onDone={onDone}
          fields={[
            { type: "number",   key: "count",            label: "Nb articles",    defaultVal: 1,  min: 1 },
            { type: "number",   key: "nb_produits",      label: "Produits/art.",  defaultVal: 5,  min: 3, max: 10 },
            { type: "number",   key: "nb_variantes_pins",label: "Variantes pins", defaultVal: 2,  min: 1, max: 3 },
            { type: "text",     key: "niche",            label: "Niche (opt.)",   placeholder: "ex: gaming_setup" },
            { type: "select",   key: "publish",          label: "Destination",    options: [{ val: "local", label: "Local (output/)" }, { val: "pinterest", label: "Pinterest" }] },
          ]}
        />

      </div>
    </div>
  );
}

// ── TaxonomyDashboard ─────────────────────────────────────────────────────────

export default function TaxonomyDashboard({ categories, nicheProductTypes, stats, total, classified }: Props) {
  const [cats, setCats] = useState<SiteCategory[]>(categories);
  const [npt,  setNpt]  = useState<NicheProductTypesMap>(nicheProductTypes);
  const [addCatOpen, setAddCatOpen] = useState(false);
  const [newCat, setNewCat] = useState({ id: "", name: "", name_en: "", icon: "" });
  const [refreshTick, setRefreshTick] = useState(0);
  const { data: statsData, loading: statsLoading } = useStats(refreshTick);

  // Auto-refresh stats every 30s
  useEffect(() => {
    const id = setInterval(() => setRefreshTick(t => t + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  function handleOpDone() {
    setRefreshTick(t => t + 1);
  }

  const totalTypes   = Object.values(npt).reduce((s, arr) => s + arr.length, 0);
  const uniqueTypeIds = new Set(Object.values(npt).flatMap(arr => arr.map(t => t.id))).size;

  // ── Category mutations ──────────────────────────────────────────────────────
  function editCat(oldId: string, patch: Pick<SiteCategory, "id" | "name" | "name_en" | "icon">) {
    const updated = cats.map(c => c.id === oldId ? { ...c, ...patch } : c);
    setCats(updated); putCats(updated);
  }
  function deleteCat(id: string) {
    if (!confirm(`Supprimer la catégorie « ${id} » ?`)) return;
    const updated = cats.filter(c => c.id !== id);
    setCats(updated); putCats(updated);
  }
  function addCat() {
    if (!newCat.id || !newCat.name) return;
    const cat: SiteCategory = { ...newCat, gradient_from: "", gradient_to: "", niches: [] };
    const updated = [...cats, cat];
    setCats(updated); putCats(updated);
    setNewCat({ id: "", name: "", name_en: "", icon: "" }); setAddCatOpen(false);
  }

  // ── Niche mutations ─────────────────────────────────────────────────────────
  function editNiche(catId: string, oldSlug: string, updated: SiteNiche) {
    const newCats = cats.map(c => c.id !== catId ? c : { ...c, niches: c.niches.map(n => n.slug === oldSlug ? updated : n) });
    setCats(newCats); putCats(newCats);
    if (updated.slug !== oldSlug) {
      const newNpt: NicheProductTypesMap = {};
      newCats.flatMap(c => c.niches).forEach(n => {
        newNpt[n.slug] = n.slug === updated.slug ? (npt[oldSlug] ?? []) : (npt[n.slug] ?? []);
      });
      setNpt(newNpt); putNpt(newNpt);
    }
  }
  function deleteNiche(catId: string, slug: string) {
    if (!confirm(`Supprimer la niche « ${slug} » ?`)) return;
    const newCats = cats.map(c => c.id !== catId ? c : { ...c, niches: c.niches.filter(n => n.slug !== slug) });
    const newNpt = { ...npt };
    delete newNpt[slug];
    setCats(newCats); putCats(newCats);
    setNpt(newNpt); putNpt(newNpt);
  }
  function addNiche(catId: string, niche: SiteNiche) {
    const newCats = cats.map(c => c.id !== catId ? c : { ...c, niches: [...c.niches, niche] });
    setCats(newCats); putCats(newCats);
    if (!npt[niche.slug]) {
      const newNpt = { ...npt, [niche.slug]: [] };
      setNpt(newNpt); putNpt(newNpt);
    }
  }

  // ── Product type mutations ──────────────────────────────────────────────────
  function editType(nicheSlug: string, oldId: string, updated: ProductTypeItem) {
    const newNpt = { ...npt, [nicheSlug]: (npt[nicheSlug] ?? []).map(t => t.id === oldId ? updated : t) };
    setNpt(newNpt); putNpt(newNpt);
  }
  function deleteType(nicheSlug: string, id: string) {
    const newNpt = { ...npt, [nicheSlug]: (npt[nicheSlug] ?? []).filter(t => t.id !== id) };
    setNpt(newNpt); putNpt(newNpt);
  }
  function addType(nicheSlug: string, t: ProductTypeItem) {
    const newNpt = { ...npt, [nicheSlug]: [...(npt[nicheSlug] ?? []), t] };
    setNpt(newNpt); putNpt(newNpt);
  }

  return (
    <div style={{ minHeight: "100vh", background: "#f9fafb", fontFamily: "system-ui, sans-serif" }}>
    <div style={{ maxWidth: 960, margin: "0 auto", padding: "32px 16px" }}>

      {/* Header */}
      <div style={{ marginBottom: 24, display: "flex", alignItems: "flex-start", gap: 12 }}>
        <div style={{ flex: 1 }}>
          <h1 style={{ fontSize: 24, fontWeight: 700, color: "#111827", margin: "0 0 6px" }}>
            Taxonomie des produits
          </h1>
          <div style={{ fontSize: 14, color: "#6b7280" }}>
            <strong style={{ color: "#111827" }}>{fmt(statsData?.classified ?? classified)}</strong> classifiés
            {" / "}
            <strong style={{ color: "#111827" }}>{fmt(statsData?.active ?? total)}</strong> actifs
            {" · "}
            {cats.length} catégories · {cats.reduce((s, c) => s + c.niches.length, 0)} niches
            {" · "}
            {totalTypes} types ({uniqueTypeIds} uniques)
          </div>
        </div>
        <button onClick={() => setRefreshTick(t => t + 1)}
          style={{ fontSize: 13, padding: "6px 14px", border: "1px solid #d1d5db", borderRadius: 6, background: "#fff", cursor: "pointer", color: "#374151" }}>
          {statsLoading ? "↺ …" : "↺ Actualiser"}
        </button>
      </div>

      {/* Legend */}
      <div style={{ display: "flex", gap: 16, marginBottom: 20, fontSize: 12, color: "#6b7280" }}>
        <span><Badge count={25} /> &gt; 20</span>
        <span><Badge count={10} /> 1-20</span>
        <span><Badge count={0} /> 0</span>
        <span style={{ marginLeft: "auto", fontSize: 11, color: "#9ca3af" }}>
          ✎ renommer · ✕ supprimer · clic pour déplier
        </span>
      </div>

      {/* Search */}
      <ProductSearch categories={cats} npt={npt} />

      {/* Tree */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {cats.map(cat => (
          <CategoryRow
            key={cat.id}
            cat={cat}
            stats={stats[cat.id]}
            npt={npt}
            onEdit={(patch) => editCat(cat.id, patch)}
            onDelete={() => deleteCat(cat.id)}
            onAddNiche={(n) => addNiche(cat.id, n)}
            onEditNiche={(oldSlug, n) => editNiche(cat.id, oldSlug, n)}
            onDeleteNiche={(slug) => deleteNiche(cat.id, slug)}
            onAddType={(nicheSlug, t) => addType(nicheSlug, t)}
            onEditType={(nicheSlug, oldId, t) => editType(nicheSlug, oldId, t)}
            onDeleteType={(nicheSlug, id) => deleteType(nicheSlug, id)}
          />
        ))}
      </div>

      {/* Add category */}
      <div style={{ marginTop: 12 }}>
        {addCatOpen ? (
          <div style={{ display: "flex", gap: 6, alignItems: "center", padding: "10px 12px", border: "1px dashed #86efac", borderRadius: 8, background: "#f0fdf4" }}>
            <input style={{ ...inp, width: 38 }} placeholder="🏷" value={newCat.icon} onChange={e => setNewCat(v => ({ ...v, icon: e.target.value }))} />
            <input style={{ ...inp, width: 140 }} placeholder="id (ex: sport)" value={newCat.id} onChange={e => setNewCat(v => ({ ...v, id: e.target.value }))} />
            <input style={{ ...inp, width: 150 }} placeholder="Nom FR" value={newCat.name} onChange={e => setNewCat(v => ({ ...v, name: e.target.value }))} />
            <input style={{ ...inp, flex: 1 }} placeholder="Nom EN" value={newCat.name_en} onChange={e => setNewCat(v => ({ ...v, name_en: e.target.value }))} />
            <Btn label="✓ Ajouter" title="Créer la catégorie" color="#16a34a" onClick={addCat} />
            <Btn label="✕" title="Annuler" color="#dc2626" onClick={() => setAddCatOpen(false)} />
          </div>
        ) : (
          <button onClick={() => setAddCatOpen(true)}
            style={{ width: "100%", background: "none", border: "1px dashed #86efac", borderRadius: 8, padding: "8px 20px", cursor: "pointer", fontSize: 13, color: "#16a34a" }}>
            + Ajouter une catégorie
          </button>
        )}
      </div>

      {/* Stats panel */}
      <StatsPanel data={statsData} loading={statsLoading} />

      {/* Products browser */}
      <ProductsBrowser tick={refreshTick} merchants={statsData?.merchants ?? []} />

      {/* Verify panel */}
      <VerifyPanel />

      {/* Operations panel */}
      <OperationsPanel onDone={handleOpDone} />

    </div>
    </div>
  );
}
