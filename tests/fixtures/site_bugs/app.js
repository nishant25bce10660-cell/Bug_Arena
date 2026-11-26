// BugArena fixture client script with planted bugs and decoys
console.info("DECOY-01: Error handling initialized cleanly");

// Planted console error (FB-01)
setTimeout(() => {
  const missing = null;
  // Intentional null dereference
  console.log(missing.propertyThatDoesNotExist);
}, 30);

// Slow API call (FB-10)
fetch("/api/slow").then((r) => r.json()).catch(() => {});

// Deprecated API usage pattern (FB-15)
window.__deprecatedWriteHelper = function () {
  if (false) {
    document.write("legacy");
  }
};

// Click exception (FB-09)
document.getElementById("crash-btn").addEventListener("click", () => {
  nonExistentHandlerSymbol();
});

// Memory leak simulation (FB-13)
window.__leakedNodes = [];
document.getElementById("leak-btn").addEventListener("click", () => {
  for (let i = 0; i < 200; i++) {
    const div = document.createElement("div");
    div.textContent = "detached_" + i;
    window.__leakedNodes.push(div);
  }
});

// Form validation bug (FB-14)
document.getElementById("signup-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const val = document.getElementById("email-input").value;
  document.getElementById("form-result").textContent = "empty-email-accepted:" + val;
});
//# sourceMappingURL=app.js.map
