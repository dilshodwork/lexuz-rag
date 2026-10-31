import type { Filters, Source, Stats } from "./types";

export type AskHandlers = {
  onSources: (d: { sources: Source[]; no_answer: boolean }) => void;
  onDelta: (text: string) => void;
  onDone: (d: { no_answer: boolean; model: string | null; ms: number }) => void;
  onError: (d: { code: string; message: string }) => void;
};

/** POST /api/ask ni SSE oqim sifatida o'qiydi: sources -> delta... -> done | error */
export async function askStream(question: string, filters: Filters, signal: AbortSignal, h: AskHandlers) {
  let res: Response;
  try {
    res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ question, filters }),
      signal,
    });
  } catch (e) {
    if (signal.aborted) return;
    h.onError({ code: "network", message: "Server bilan aloqa yoʻq. Server ishga tushganini tekshirib, qayta urinib koʻring." });
    return;
  }
  if (!res.ok || !res.body) {
    h.onError({ code: "server", message: `Server xato qaytardi (${res.status}). Qayta urinib koʻring.` });
    return;
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  let finished = false;
  const handle = (block: string) => {
    let ev = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) ev = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
    }
    if (!data.length) return;
    const d = JSON.parse(data.join("\n"));
    if (ev === "sources") h.onSources(d);
    else if (ev === "delta") h.onDelta(d.text);
    else if (ev === "done") { finished = true; h.onDone(d); }
    else if (ev === "error") { finished = true; h.onError(d); }
  };
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i: number;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        handle(buf.slice(0, i));
        buf = buf.slice(i + 2);
      }
    }
  } catch (e) {
    if (signal.aborted) return;
    h.onError({ code: "network", message: "Aloqa uzilib qoldi. Qayta urinib koʻring." });
    return;
  }
  if (!finished && !signal.aborted) h.onError({ code: "server", message: "Javob oxirigacha kelmadi. Qayta urinib koʻring." });
}

export async function getStats(): Promise<Stats | null> {
  try {
    const r = await fetch("/api/stats");
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}
