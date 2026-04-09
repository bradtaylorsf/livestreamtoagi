export class AGIProgressBar {
  private element: HTMLDivElement;
  private fillElement: HTMLDivElement;
  private labelElement: HTMLSpanElement;

  constructor() {
    this.element = document.createElement("div");
    this.element.className = "overlay-agi";

    this.labelElement = document.createElement("span");
    this.labelElement.className = "overlay-label";
    this.labelElement.textContent = "AGI Progress: 0%";
    this.element.appendChild(this.labelElement);

    const track = document.createElement("div");
    track.className = "agi-track";
    this.element.appendChild(track);

    this.fillElement = document.createElement("div");
    this.fillElement.className = "agi-fill";
    this.fillElement.style.width = "0%";
    track.appendChild(this.fillElement);
  }

  getElement(): HTMLDivElement {
    return this.element;
  }

  update(percent: number, categories: number): void {
    const clamped = Math.max(0, Math.min(100, percent));
    this.fillElement.style.width = `${clamped}%`;
    this.labelElement.textContent = `AGI Progress: ${clamped.toFixed(0)}% across ${categories} categories`;
  }
}
