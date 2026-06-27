// Dark mode toggle — persists to localStorage
(function () {
  var btn = document.getElementById("theme-toggle");
  if (!btn) return;

  function apply(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
    btn.textContent = theme === "dark" ? "☀" : "☾";
    btn.title = theme === "dark" ? "Switch to light mode" : "Switch to dark mode";
  }

  apply(localStorage.getItem("theme") || "light");

  btn.addEventListener("click", function () {
    var cur = document.documentElement.getAttribute("data-theme");
    apply(cur === "dark" ? "light" : "dark");
    if (typeof window.onThemeChange === "function") window.onThemeChange();
  });
})();
