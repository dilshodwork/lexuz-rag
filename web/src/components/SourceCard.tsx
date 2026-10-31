import { useState } from "react";
import { Icon } from "../icons";
import { niceTitle } from "../render";
import type { Source } from "../types";

const stCls = (s: string) => (s === "amalda" ? "st-on" : (s || "").includes("kuchini") ? "st-lost" : "st-off");
const stLabel = (s: string) => (s || "").replace(/'/g, "ʻ");
const fmtD = (d: string | null) => (d ? d.split("-").reverse().join(".") : "");

export function SourceCard({ s, id, hl }: { s: Source; id: string; hl: boolean }) {
  const [open, setOpen] = useState(false);
  const head = s.article_number
    ? <><span className="art">{s.article_number}-modda</span>{s.article_title ? `. ${s.article_title}` : ""}</>
    : <span className="art">{(s.heading || "").split(" > ").slice(-1)[0] || "Hujjat matni"}</span>;
  return (
    <article className={`card${open ? " open" : ""}${hl ? " hl" : ""}`} id={id}>
      <div className="c-top">
        <span className="c-n">{s.n}</span>
        <span className={`st ${stCls(s.status)}`}>{stLabel(s.status)}</span>
        <span>{s.doc_type}</span>
        {s.last_edition_date && <span className="c-date num">tahrir {fmtD(s.last_edition_date)}</span>}
      </div>
      <h3>{head}</h3>
      <p className="c-doc">{niceTitle(s.doc_title)}{s.doc_number ? ` · ${s.doc_number}` : ""}</p>
      {s.chapter && <p className="c-chap">{s.chapter.replace(/\n/g, " ")}</p>}
      <p className="c-text">{s.text}</p>
      <div className="c-foot">
        <button className="more" onClick={() => setOpen(!open)} aria-expanded={open}>
          <span>{open ? "Yigʻish" : "Toʻliq oʻqish"}</span><Icon name="down" />
        </button>
        <a className="lex press" href={s.source_url} target="_blank" rel="noopener noreferrer">
          lex.uz’da ochish<Icon name="ext" />
        </a>
      </div>
    </article>
  );
}

export function SkeletonCards() {
  return (
    <>
      {[0, 1, 2].map((i) => (
        <div className="card sk-card" key={i} aria-hidden="true">
          <div className="sk" style={{ width: "46%" }} />
          <div className="sk" style={{ width: "88%", height: 17 }} />
          <div className="sk" style={{ width: "64%" }} />
          <div className="sk" style={{ width: "94%" }} />
          <div className="sk" style={{ width: "78%" }} />
        </div>
      ))}
    </>
  );
}
