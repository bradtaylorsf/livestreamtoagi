export class BudgetTicker {
  private element: HTMLDivElement;
  private valueElement: HTMLSpanElement;

  constructor() {
    this.element = document.createElement("div");
    this.element.className = "overlay-budget";

    const label = document.createElement("span");
    label.className = "overlay-label";
    label.textContent = "Daily:";
    this.element.appendChild(label);

    this.valueElement = document.createElement("span");
    this.valueElement.className = "overlay-value";
    this.valueElement.textContent = " $0.00 / $150.00";
    this.element.appendChild(this.valueElement);
  }

  getElement(): HTMLDivElement {
    return this.element;
  }

  update(totalSpent: number, dailyLimit: number): void {
    this.valueElement.textContent = ` $${totalSpent.toFixed(2)} / $${dailyLimit.toFixed(2)}`;

    // Warn when spending exceeds 80% of limit
    if (totalSpent / dailyLimit >= 0.8) {
      this.element.classList.add("budget-warning");
    } else {
      this.element.classList.remove("budget-warning");
    }
  }
}
