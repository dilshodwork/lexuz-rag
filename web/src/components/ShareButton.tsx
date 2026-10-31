import { useEffect, useRef, useState } from "react";
import { Icon } from "../icons";
import { copyText, downloadBlob, makeCard, shareText, telegramShareUrl, whatsappShareUrl } from "../share";
import { haptic, inTelegram, openShareLink } from "../telegram";
import type { Source } from "../types";

type Item = { q: string; text: string; sources: Source[] };

/* "Ulashish": telefonda tizim oynasi (navigator.share: matn + rasm-kartochka, Web Share Level 2 bo'lsa),
   kompyuterda va Telegram Mini App ichida - kichik menyu: Telegram, WhatsApp, matnni nusxalash, rasmni yuklab olish. */
export function ShareButton({ item, onHud }: { item: Item; onHud: (m: string) => void }) {
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const card = useRef<Promise<Blob> | null>(null);
  const key = useRef("");
  const box = useRef<HTMLDivElement>(null);

  // rasm oldindan tayyorlanadi: navigator.share foydalanuvchi bosgan zahoti chaqirilishi kerak (iOS Safari)
  const getCard = () => {
    const k = item.q + item.text;
    if (!card.current || key.current !== k) {
      key.current = k;
      card.current = makeCard(item);
    }
    return card.current;
  };
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);
  useEffect(() => {
    if (!open) return;
    getCard().then((b) => setPreview(URL.createObjectURL(b))).catch(() => setPreview(null));
    const out = (e: MouseEvent | TouchEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    addEventListener("mousedown", out);
    addEventListener("touchstart", out);
    addEventListener("keydown", esc);
    return () => { removeEventListener("mousedown", out); removeEventListener("touchstart", out); removeEventListener("keydown", esc); };
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const nativeOk = () => !inTelegram && typeof navigator.share === "function" && matchMedia("(pointer: coarse)").matches;

  const onClick = async () => {
    haptic();
    if (!nativeOk()) { setOpen((o) => !o); return; }
    const text = shareText(item);
    try {
      const blob = await getCard();
      const file = new File([blob], "dalil-javob.png", { type: "image/png" });
      if (navigator.canShare?.({ files: [file] })) await navigator.share({ title: "Dalil", text, files: [file] });
      else await navigator.share({ title: "Dalil", text, url: location.origin });
    } catch (e) {
      if ((e as Error)?.name === "AbortError") return; // foydalanuvchi oynani yopdi
      setOpen(true); // tizim oynasi ishlamadi - menyu
    }
  };

  const act = async (what: "tg" | "wa" | "copy" | "img") => {
    setOpen(false);
    if (what === "tg") openShareLink(telegramShareUrl(item));
    else if (what === "wa") openShareLink(whatsappShareUrl(item));
    else if (what === "copy") { await copyText(shareText(item)); onHud("Matn nusxalandi"); }
    else { downloadBlob(await getCard()); onHud("Rasm yuklab olindi"); }
  };

  return (
    <div className="share-wrap" ref={box} onPointerDown={() => { getCard(); }}>
      <button className={`cbtn press${open ? " on" : ""}`} onClick={onClick} aria-label="Ulashish" title="Ulashish" aria-haspopup="menu" aria-expanded={open}>
        <Icon name="share" />
      </button>
      <div className={`share-pop glass${open ? " open" : ""}`} role="menu" aria-label="Ulashish" aria-hidden={!open}>
        <div className="sp-card">
          <span className="sp-thumb">{preview && <img src={preview} alt="Rasm-kartochka" />}</span>
          <span className="sp-txt"><b>Rasm-kartochka</b><small>Savol, javob va manbalar · 1080×1350</small></span>
        </div>
        <button role="menuitem" tabIndex={open ? 0 : -1} onClick={() => act("tg")}><span className="sp-ic tg"><Icon name="plane" /></span>Telegram</button>
        <button role="menuitem" tabIndex={open ? 0 : -1} onClick={() => act("wa")}><span className="sp-ic wa"><Icon name="chat" /></span>WhatsApp</button>
        <button role="menuitem" tabIndex={open ? 0 : -1} onClick={() => act("copy")}><span className="sp-ic"><Icon name="copy" /></span>Matnni nusxalash</button>
        <button role="menuitem" tabIndex={open ? 0 : -1} onClick={() => act("img")}><span className="sp-ic"><Icon name="image" /></span>Rasmni yuklab olish</button>
      </div>
    </div>
  );
}
