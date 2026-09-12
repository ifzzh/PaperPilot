import { useMemo } from "react";
import katex from "katex";
import DOMPurify from "dompurify";
/** Native MathML avoids inline style attributes and external font requests. */
export function MathFormula({
  text,
  inline = false,
}: {
  text: string;
  inline?: boolean;
}) {
  const rendered = useMemo(() => {
    if (text.length > 32000) return null;
    const source = text
      .trim()
      .replace(/^\$\$([\s\S]*)\$\$$/, "$1")
      .replace(/^\\\[([\s\S]*)\\\]$/, "$1")
      .replace(/^\$([^$\n]*)\$$/, "$1")
      .replace(/^\\\(([\s\S]*)\\\)$/, "$1");
    try {
      return DOMPurify.sanitize(
        katex.renderToString(source, {
          output: "mathml",
          displayMode: !inline,
          throwOnError: true,
          trust: false,
          strict: "error",
          maxExpand: 1000,
          maxSize: 20,
          macros: {},
        }),
        {
          USE_PROFILES: { mathMl: true, html: true },
          FORBID_TAGS: ["a", "img", "style", "script", "iframe"],
          FORBID_ATTR: ["style"],
        },
      );
    } catch {
      return null;
    }
  }, [text, inline]);
  const Tag = inline ? "span" : "div";
  return rendered ? (
    <Tag
      className={inline ? "formula-inline" : "formula-mathml"}
      dangerouslySetInnerHTML={{ __html: rendered }}
    />
  ) : (
    <Tag className="formula-source">{text}</Tag>
  );
}

// Source offsets stay in the canonical UTF-16 text, never in generated MathML
// textContent (which also contains accessibility annotations).
export function AcademicText({ text }: { text: string }) {
  const pieces = useMemo(() => {
    const pattern =
      /\$\$[\s\S]*?\$\$|\$[^$\n]+\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)/g;
    const parts: { start: number; end: number; math: boolean; text: string }[] =
      [];
    let cursor = 0;
    for (const match of text.matchAll(pattern)) {
      if (match.index > cursor)
        parts.push({
          start: cursor,
          end: match.index,
          math: false,
          text: text.slice(cursor, match.index),
        });
      parts.push({
        start: match.index,
        end: match.index + match[0].length,
        math: true,
        text: match[0],
      });
      cursor = match.index + match[0].length;
    }
    if (cursor < text.length)
      parts.push({
        start: cursor,
        end: text.length,
        math: false,
        text: text.slice(cursor),
      });
    return parts;
  }, [text]);
  return (
    <>
      {pieces.map((p) => (
        <span
          key={p.start}
          data-source-start={p.start}
          data-source-end={p.end}
          data-source-math={p.math || undefined}
        >
          {p.math ? <MathFormula text={p.text} inline /> : p.text}
        </span>
      ))}
    </>
  );
}

export function sourceSelection(node: HTMLElement, range: Range, text: string) {
  function endpoint(container: Node, offset: number, ending: boolean): number {
    if (container === node) {
      const child = node.childNodes[offset];
      return child instanceof HTMLElement &&
        child.dataset.sourceStart !== undefined
        ? Number(child.dataset.sourceStart)
        : offset === 0
          ? 0
          : text.length;
    }
    const element =
      container instanceof Element ? container : container.parentElement;
    const segment = element?.closest<HTMLElement>("[data-source-start]");
    if (!segment || !node.contains(segment))
      throw Error("selection_outside_source");
    if (segment.dataset.sourceMath)
      return Number(
        ending ? segment.dataset.sourceEnd : segment.dataset.sourceStart,
      );
    const prefix = document.createRange();
    prefix.selectNodeContents(segment);
    prefix.setEnd(container, offset);
    return Number(segment.dataset.sourceStart) + prefix.toString().length;
  }
  const start = endpoint(range.startContainer, range.startOffset, false);
  const end = endpoint(range.endContainer, range.endOffset, true);
  if (start < 0 || end < start || end > text.length)
    throw Error("invalid_source_selection");
  return { start, end, text: text.slice(start, end) };
}
