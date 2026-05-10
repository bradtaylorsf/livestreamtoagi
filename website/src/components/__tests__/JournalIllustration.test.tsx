import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  getJournalIllustrationStatus,
  JournalIllustrationFrame,
} from "@/components/JournalIllustration";

describe("JournalIllustration", () => {
  it("renders a journal illustration image when an image URL is available", () => {
    const html = renderToStaticMarkup(
      <JournalIllustrationFrame
        imageUrl="https://example.com/journals/vera.png"
        label="Daily journal illustration"
        status="image"
      />,
    );

    expect(html).toContain('data-illustration-status="image"');
    expect(html).toContain("<img");
    expect(html).toContain('src="https://example.com/journals/vera.png"');
    expect(html).toContain('alt="Daily journal illustration"');
    expect(html).not.toContain("Text-only journal");
  });

  it("renders a neutral text-only state when no image URL is present", () => {
    const status = getJournalIllustrationStatus(null, false);
    const html = renderToStaticMarkup(
      <JournalIllustrationFrame
        imageUrl={null}
        label="Daily journal illustration"
        status={status}
      />,
    );

    expect(status).toBe("missing");
    expect(html).toContain('data-illustration-status="missing"');
    expect(html).toContain("Text-only journal");
    expect(html).not.toContain("<img");
    expect(html).not.toContain("error");
  });

  it("renders an unavailable fallback after an image load failure", () => {
    const status = getJournalIllustrationStatus("https://example.com/broken.png", true);
    const html = renderToStaticMarkup(
      <JournalIllustrationFrame
        imageUrl="https://example.com/broken.png"
        label="Daily journal illustration"
        status={status}
      />,
    );

    expect(status).toBe("failed");
    expect(html).toContain('data-illustration-status="failed"');
    expect(html).toContain("Illustration unavailable");
    expect(html).not.toContain("<img");
    expect(html).not.toContain("text-red");
  });
});
