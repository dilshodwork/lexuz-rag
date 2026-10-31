import { Icon } from "../icons";
import { LANG_PREFS } from "../store";
import { DOC_TYPES, type Filters, type LangPref } from "../types";

/* Mobil varaq va desktop popover uchun bitta filtr shakli (o'zgarish darhol qo'llanadi) */
export function FilterForm({ f, onChange, onClose, lang, onLang, xray, onXray }: {
  f: Filters; onChange: (f: Filters) => void; onClose: () => void; lang: LangPref; onLang: (l: LangPref) => void;
  xray: boolean; onXray: (v: boolean) => void;
}) {
  const li = LANG_PREFS.findIndex((x) => x.v === lang);
  const toggleType = (t: string) => {
    const has = f.doc_types.includes(t);
    if (has && f.doc_types.length === 1) return; // kamida bitta tur qolsin
    onChange({ ...f, doc_types: has ? f.doc_types.filter((x) => x !== t) : DOC_TYPES.filter((x) => x === t || f.doc_types.includes(x)) });
  };
  return (
    <>
      <div className="grp-label">Hujjat holati</div>
      <div className="seg" data-v={f.only_active ? 0 : 1} role="radiogroup" aria-label="Hujjat holati">
        <span className="thumb" />
        <button role="radio" aria-checked={f.only_active} onClick={() => onChange({ ...f, only_active: true })}>Faqat amaldagi</button>
        <button role="radio" aria-checked={!f.only_active} onClick={() => onChange({ ...f, only_active: false })}>Barchasi</button>
      </div>
      <div className="grp-label">Hujjat turi</div>
      <div className="grp">
        {DOC_TYPES.map((t) => (
          <button key={t} className={`row${f.doc_types.includes(t) ? " on" : ""}`} role="checkbox"
            aria-checked={f.doc_types.includes(t)} onClick={() => toggleType(t)}>
            {t}<Icon name="check" className="i chk" />
          </button>
        ))}
      </div>
      <div className="grp-label">Qoʻshimcha</div>
      <div className="grp">
        <div className="row">
          <div className="txt">Oʻzgartirish qonunlari<small>Boshqa qonunga tuzatish kiritgan hujjatlar</small></div>
          <button className={`sw${f.include_amending ? " on" : ""}`} role="switch" aria-checked={f.include_amending}
            aria-label="Oʻzgartirish qonunlari" onClick={() => onChange({ ...f, include_amending: !f.include_amending })} />
        </div>
      </div>
      {!f.only_active && <p className="f-hint">Kuchini yoʻqotgan va amalda boʻlmagan hujjatlar ham qidiriladi.</p>}
      <div className="grp-label">Javob tili</div>
      <div className="seg seg4" data-v={li} role="radiogroup" aria-label="Javob tili">
        <span className="thumb" />
        {LANG_PREFS.map((x) => (
          <button key={x.v} role="radio" aria-checked={lang === x.v} onClick={() => onLang(x.v)}>{x.label}</button>
        ))}
      </div>
      <p className="f-hint">{lang === "auto" ? "Javob savol yozilgan tilda: lotin, kirill yoki rus. Manbalar asl oʻzbekcha qoladi." : "Javob har doim shu tilda. Manbalar asl oʻzbekcha qoladi."}</p>
      <div className="grp-label">Shaffoflik</div>
      <div className="grp">
        <div className="row">
          <div className="txt">X-ray rejimi<small>Har javobda RAG ichi: dense / BM25 / RRF, prompt, vaqtlar</small></div>
          <button className={`sw${xray ? " on" : ""}`} role="switch" aria-checked={xray} aria-label="X-ray rejimi" onClick={() => onXray(!xray)} />
        </div>
      </div>
      <p className="f-hint">Qoʻshimcha AI soʻrovi yuborilmaydi. Oʻchiq boʻlsa ham har javobdagi “Ichini koʻrish” ishlaydi.</p>
      <button className="primary press" onClick={onClose}>Qoʻllash</button>
    </>
  );
}
