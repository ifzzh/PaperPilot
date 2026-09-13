import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { AcademicText } from "./MathFormula";

describe("MinerU scientific notation", () => {
  it("renders only exact superscript/subscript notation and keeps canonical offsets", () => {
    const text = "Author<sup>\\*,†</sup>, H<sub>2</sub>O";
    const markup = renderToStaticMarkup(<AcademicText text={text} />);
    expect(markup).toContain("<sup>*,†</sup>");
    expect(markup).toContain("<sub>2</sub>");
    expect(markup).toContain('data-source-start="6" data-source-end="21" data-source-math="true"');
    expect(markup).not.toContain("&lt;sup&gt;");
  });
  it("does not interpret attributes, links, arbitrary HTML or nested tags", () => {
    const markup = renderToStaticMarkup(<AcademicText text={'<sup onclick="alert(1)">x</sup><img src=x><sub><script>x</script></sub>'} />);
    expect(markup).not.toContain("<sup");
    expect(markup).not.toContain("<sub");
    expect(markup).not.toContain("<img");
    expect(markup).not.toContain("<script");
    expect(markup).toContain("&lt;sup onclick=");
  });
});
