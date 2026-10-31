import { useLayoutEffect, useRef, type ReactNode } from "react";
import { Icon } from "../icons";

export type SheetPos = "large" | "medium" | "closed";
const MEDIUM = 0.42; // medium holatda varaq balandligining shu qismi ekrandan pastda

/* iOS varag'i: ikki detent (large / medium), sudrash, tezlik bilan otish.
   large holatda orqa sahifa karta bo'lib kichrayadi (body.card-mode, App boshqaradi). */
export function Sheet(props: {
  id: string;
  className?: string;
  label: string;
  title: ReactNode;
  sub?: ReactNode;
  pos: SheetPos;
  onPos: (p: SheetPos) => void;
  bodyRef?: React.Ref<HTMLDivElement>;
  children: ReactNode;
}) {
  const el = useRef<HTMLElement>(null);
  const body = useRef<HTMLDivElement | null>(null);
  const drag = useRef<{ y0: number; t0: number; base: number } | null>(null);

  const place = (pos: SheetPos) => {
    const s = el.current!;
    const H = s.getBoundingClientRect().height;
    const y = pos === "large" ? 0 : pos === "medium" ? H * MEDIUM : H + 40;
    s.style.transform = `translateY(${y}px)`;
    // medium holatda pastki kartalar ham o'qilishi uchun
    if (body.current) body.current.style.paddingBottom = pos === "medium" ? `${Math.round(H * MEDIUM + 24)}px` : "";
  };
  useLayoutEffect(() => {
    place(props.pos);
    const r = () => place(props.pos);
    addEventListener("resize", r);
    return () => removeEventListener("resize", r);
  }, [props.pos]); // eslint-disable-line react-hooks/exhaustive-deps

  const down = (e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest("button")) return;
    const m = new DOMMatrix(getComputedStyle(el.current!).transform);
    drag.current = { y0: e.clientY, t0: performance.now(), base: m.m42 };
    el.current!.classList.add("drag");
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const move = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    let y = d.base + e.clientY - d.y0;
    if (y < 0) y = y / 4; // yuqoriga rezina qarshilik
    el.current!.style.transform = `translateY(${y}px)`;
    document.body.classList.toggle("card-mode", y < el.current!.getBoundingClientRect().height * 0.2);
  };
  const up = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    drag.current = null;
    el.current!.classList.remove("drag");
    const dy = e.clientY - d.y0, v = dy / Math.max(performance.now() - d.t0, 1), y = d.base + dy;
    const H = el.current!.getBoundingClientRect().height;
    const order: SheetPos[] = ["large", "medium", "closed"];
    const cur = order.indexOf(props.pos);
    let pos: SheetPos;
    if (Math.abs(dy) < 4) pos = props.pos;
    else if (Math.abs(v) > 0.6) pos = order[Math.max(0, Math.min(2, cur + (v > 0 ? 1 : -1)))];
    else pos = ([["large", 0], ["medium", H * MEDIUM], ["closed", H]] as [SheetPos, number][])
      .sort((a, b) => Math.abs(a[1] - y) - Math.abs(b[1] - y))[0][0];
    if (pos === props.pos) place(pos);
    props.onPos(pos);
  };

  return (
    <section className={`sheet ${props.className || ""}`} id={props.id} ref={el} aria-label={props.label}
      aria-hidden={props.pos === "closed"} role="dialog">
      <div className="grab" onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}>
        <div className="sh-head">
          <h2>{props.title}</h2>
          <button className="sh-close press" onClick={() => props.onPos("closed")} aria-label="Yopish"><Icon name="close" /></button>
        </div>
        {props.sub}
      </div>
      <div className="sh-body" ref={(n) => {
        body.current = n;
        if (typeof props.bodyRef === "function") props.bodyRef(n);
        else if (props.bodyRef) (props.bodyRef as React.MutableRefObject<HTMLDivElement | null>).current = n;
      }}>{props.children}</div>
    </section>
  );
}
