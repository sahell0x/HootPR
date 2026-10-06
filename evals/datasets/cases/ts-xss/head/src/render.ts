export function renderComment(el: HTMLElement, text: string): void {
  el.innerHTML = `<p class="comment">${text}</p>`;
}
