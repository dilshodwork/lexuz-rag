import { Icon } from "../icons";
import type { Trust } from "../types";

export const TRUST_LABEL = { high: "Yuqori", medium: "Oʻrta", low: "Past" } as const;

/** Javob tepasidagi "Ishonch: Yuqori" belgisi. Bosilganda izoh paneli ochiladi (TrustPanel). */
export function TrustBadge({ trust, open, onToggle }: { trust: Trust | "pending" | "error" | undefined; open: boolean; onToggle: () => void }) {
  if (!trust || trust === "error") return null;
  if (trust === "pending") {
    return <span className="trust tone-wait" role="status"><span className="dot" />Tekshirilmoqda…</span>;
  }
  if (!trust.level) return null;
  return (
    <button className={`trust press lv-${trust.level}${open ? " on" : ""}`} onClick={onToggle} aria-expanded={open}>
      <span className="dot" />Ishonch: {TRUST_LABEL[trust.level]}
    </button>
  );
}

const quote = (s: string) => {
  const t = s.replace(/\*\*/g, "").replace(/\[\d+(?:\s*[,;]\s*\d+)*\]/g, "").replace(/\s+/g, " ").trim();
  return t.length > 110 ? t.slice(0, 108).trimEnd() + "…" : t;
};

export function TrustPanel({ trust, text, simple, onFocus }: { trust: Trust; text: string; simple: boolean; onFocus: (i: number) => void }) {
  const weak = trust.claims.map((c, i) => ({ ...c, i })).filter((c) => !c.ok);
  return (
    <div className={`trust-panel lv-${trust.level}`}>
      <div className="tp-head">
        <span className="tp-ic"><Icon name="shield" /></span>
        <div>
          <b>Ishonch: {trust.level ? TRUST_LABEL[trust.level] : "—"}</b>
          <p className="num">{trust.checked} ta daʼvo tekshirildi · {trust.supported} tasining manbada asosi bor</p>
        </div>
      </div>
      {weak.length > 0 ? (
        <ul className="tp-list">
          {weak.map((c) => (
            <li key={c.i}>
              <button onClick={() => onFocus(c.i)}>
                <span className="tp-q">“{quote(text.slice(c.start, c.end))}”</span>
                <span className="tp-why">{c.reasons.join("; ")}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : <p className="tp-ok">Asossiz koʻringan gap topilmadi.</p>}
      <p className="tp-note">Avtomatik tekshiruv: raqam va muddatlar, soʻzlar hamda maʼno oʻxshashligi iqtibos qilingan modda bilan solishtiriladi. Qoʻshimcha AI soʻrovi yuborilmaydi.{simple ? " Sodda javobdagi misol va maslahatlar tekshirilmaydi." : ""} Asl matnni lex.uz’da oʻqing.</p>
    </div>
  );
}
