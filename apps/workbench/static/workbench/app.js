const resizeTextarea = (textarea) => {
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(textarea.scrollHeight, 210)}px`;
};

document.querySelectorAll("textarea").forEach((textarea) => {
  resizeTextarea(textarea);
  textarea.addEventListener("input", () => resizeTextarea(textarea));
});

document.querySelectorAll("[data-loading-form]").forEach((form) => {
  form.addEventListener("submit", () => {
    form.setAttribute("aria-busy", "true");
    const button = form.querySelector("button[type='submit']");
    if (!button) return;
    button.disabled = true;
    const label = button.dataset.loadingLabel;
    if (label) button.querySelector("span").textContent = label;
  });
});

const tabs = [...document.querySelectorAll("[data-tab]")];
tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    tabs.forEach((candidate) => {
      const selected = candidate === tab;
      candidate.setAttribute("aria-selected", String(selected));
      document.getElementById(candidate.dataset.tab).hidden = !selected;
    });
  });
});

const thread = document.getElementById("thread");
if (thread) thread.scrollTop = thread.scrollHeight;
