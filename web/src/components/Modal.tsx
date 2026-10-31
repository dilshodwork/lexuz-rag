import type { ReactNode } from "react";
import { Icon } from "../icons";

/* Desktop dialog (mobil ko'rinishda xuddi shu kontent iOS varag'ida ochiladi) */
export function Modal({ open, title, label, onClose, children }: {
  open: boolean; title: ReactNode; label: string; onClose: () => void; children: ReactNode;
}) {
  return (
    <div className={`modal-wrap${open ? " open" : ""}`} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      aria-hidden={!open}>
      <section className="modal" role="dialog" aria-modal="true" aria-label={label}>
        <div className="sh-head">
          <h2>{title}</h2>
          <button className="sh-close press" onClick={onClose} aria-label="Yopish"><Icon name="close" /></button>
        </div>
        <div className="modal-body">{open && children}</div>
      </section>
    </div>
  );
}
