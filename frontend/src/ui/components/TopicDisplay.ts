export class TopicDisplay {
  private element: HTMLDivElement;
  private valueElement: HTMLSpanElement;

  constructor() {
    this.element = document.createElement("div");
    this.element.className = "overlay-topic";

    const label = document.createElement("span");
    label.className = "overlay-label";
    label.textContent = "Topic:";
    this.element.appendChild(label);

    this.valueElement = document.createElement("span");
    this.valueElement.className = "overlay-value";
    this.valueElement.textContent = " --";
    this.element.appendChild(this.valueElement);
  }

  getElement(): HTMLDivElement {
    return this.element;
  }

  update(topic: string): void {
    this.valueElement.textContent = ` ${topic}`;
  }
}
