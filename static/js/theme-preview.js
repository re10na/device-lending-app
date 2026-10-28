(() => {
  const choices = Array.from(document.querySelectorAll("[data-theme-choice]"));
  const body = document.body;
  let selectedTheme = "auto";

  const themeForCurrentTime = () => {
    const hour = new Date().getHours();
    if (hour < 11) return "morning";
    if (hour < 17) return "day";
    return "evening";
  };

  const applyTheme = () => {
    const theme = selectedTheme === "auto" ? themeForCurrentTime() : selectedTheme;
    body.dataset.theme = theme;
    for (const choice of choices) {
      choice.setAttribute("aria-pressed", String(choice.dataset.themeChoice === selectedTheme));
    }
  };

  for (const choice of choices) {
    choice.addEventListener("click", () => {
      selectedTheme = choice.dataset.themeChoice;
      applyTheme();
    });
  }

  applyTheme();
  window.setInterval(() => {
    if (selectedTheme === "auto") applyTheme();
  }, 60_000);
})();
