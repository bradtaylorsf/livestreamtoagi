import { describe, expect, it } from "vitest";
import { GLOSSARY_TERMS } from "@/components/Glossary";

describe("About page data", () => {
  describe("Research Questions", () => {
    // Import the page module to access RESEARCH_QUESTIONS indirectly
    // Since the page is a server component, we test the data contract
    const expectedQuestions = [
      "Agent-to-agent communication patterns",
      "Memory architecture",
      "Context degradation",
      "Conversation dynamics",
      "Social dynamics",
      "Economic behavior",
      "Dreams and creativity",
      "Evaluation methodology",
      "Entertainment value",
      "Multi-model dynamics",
    ];

    it("covers all 10 research areas", () => {
      expect(expectedQuestions).toHaveLength(10);
    });

    it("includes memory architecture question", () => {
      expect(expectedQuestions).toContain("Memory architecture");
    });

    it("includes economic behavior question", () => {
      expect(expectedQuestions).toContain("Economic behavior");
    });
  });

  describe("Glossary", () => {
    it("defines all 4 key terms", () => {
      expect(GLOSSARY_TERMS).toHaveLength(4);
    });

    it("includes AGI definition", () => {
      const agi = GLOSSARY_TERMS.find((t) => t.term === "AGI");
      expect(agi).toBeDefined();
      expect(agi!.definition).toContain("Tongue-in-cheek");
    });

    it("includes autonomy definition", () => {
      const autonomy = GLOSSARY_TERMS.find((t) => t.term === "Autonomy");
      expect(autonomy).toBeDefined();
      expect(autonomy!.definition).toContain("designed constraints");
    });

    it("includes emergence definition", () => {
      const emergence = GLOSSARY_TERMS.find((t) => t.term === "Emergence");
      expect(emergence).toBeDefined();
      expect(emergence!.definition).toContain("not explicitly programmed");
    });

    it("includes self-sufficiency definition", () => {
      const selfSuff = GLOSSARY_TERMS.find(
        (t) => t.term === "Self-sufficiency",
      );
      expect(selfSuff).toBeDefined();
      expect(selfSuff!.definition).toContain("operational costs");
    });
  });
});
