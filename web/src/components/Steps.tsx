import { useEffect, useState } from "react";
import { Icon } from "../icons";
import type { Step } from "../types";

const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const sec = (ms: number) => (ms / 1000).toFixed(1).replace(".", ",");

/* Qidiruv bosqichlari (Perplexity uslubi). Server bosqichlari bir zumda kelishi mumkin (o'z kaliti yo'lida
   hammasi birga), shuning uchun ekranda bittadan ochiladi: har biri kamida ~260 ms ko'rinadi. */
function useReveal(n: number, live: boolean) {
  const [shown, setShown] = useState(() => (live && !reduced() ? 0 : n));
  useEffect(() => {
    if (shown >= n) return;
    const id = setTimeout(() => setShown((s) => Math.min(n, s + 1)), shown === 0 ? 60 : 260);
    return () => clearTimeout(id);
  }, [shown, n]);
  return Math.min(shown, n);
}

function Row({ s, active }: { s: Step; active: boolean }) {
  return (
    <li className={`step${active ? " run" : " ok"}`}>
      <span className="s-ic" aria-hidden="true">{active ? <span className="spin" /> : <Icon name="check" />}</span>
      <span className="s-txt">
        <span className="s-label">{s.label}</span>
        {s.detail && <span className="s-detail">{s.detail}</span>}
      </span>
    </li>
  );
}

/** live=true: javob tayyorlanmoqda (ro'yxat ochiq). Tugagach "5 bosqich · 12,4 s" satriga yig'iladi. */
export function Steps({ steps, live, totalMs }: { steps: Step[]; live: boolean; totalMs?: number }) {
  const shown = useReveal(steps.length, live);
  const [open, setOpen] = useState(false);
  const list = steps.slice(0, shown);
  // oxirgi ko'ringan bosqich hali tugamagan yoki keyingisi hali ochilmagan bo'lsa - u "ishlayapti"
  const last = list[list.length - 1];
  const activeIdx = live && last && (last.state === "run" || shown < steps.length) ? list.length - 1 : -1;
  const collapsed = !live && shown >= steps.length;
  const total = totalMs ?? steps.reduce((a, s) => a + (s.ms || 0), 0);
  return (
    <div className={`steps${collapsed ? " done" : ""}${open ? " open" : ""}`}>
      {collapsed && (
        <button className="steps-sum press" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          <span className="s-ic ok"><Icon name="check" /></span>
          <span className="num">{steps.length} bosqich · {sec(total)} s</span>
          <Icon name="down" className="i chev" />
        </button>
      )}
      <div className="steps-body">
        <ol className="steps-list" aria-live="polite">
          {list.map((s, i) => <Row key={s.key} s={s} active={i === activeIdx} />)}
        </ol>
      </div>
    </div>
  );
}
