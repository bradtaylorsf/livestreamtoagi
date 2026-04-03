"use client";

interface Tab {
  id: string;
  label: string;
}

interface Props {
  tabs: Tab[];
  activeTab: string;
  onTabChange: (id: string) => void;
}

export default function TabNav({ tabs, activeTab, onTabChange }: Props) {
  return (
    <div className="flex gap-1 border-b border-border">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onTabChange(tab.id)}
          className={`px-4 py-2 text-sm transition-colors border-b-2 -mb-px ${
            activeTab === tab.id
              ? "border-neon-cyan text-neon-cyan"
              : "border-transparent text-foreground/50 hover:text-foreground/70"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
