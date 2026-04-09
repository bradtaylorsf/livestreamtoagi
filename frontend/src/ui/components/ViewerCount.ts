export class ViewerCount {
  private element: HTMLDivElement;
  private valueElement: HTMLSpanElement;

  constructor() {
    this.element = document.createElement("div");
    this.element.className = "overlay-viewers";

    const icon = document.createElement("span");
    icon.className = "overlay-icon";
    icon.textContent = ">>>";
    this.element.appendChild(icon);

    this.valueElement = document.createElement("span");
    this.valueElement.className = "overlay-value";
    this.valueElement.textContent = " 0 viewers";
    this.element.appendChild(this.valueElement);
  }

  getElement(): HTMLDivElement {
    return this.element;
  }

  update(count: number): void {
    this.valueElement.textContent = ` ${count} viewer${count !== 1 ? "s" : ""}`;
  }
}
