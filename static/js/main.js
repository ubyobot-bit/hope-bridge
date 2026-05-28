document.querySelectorAll(".password-toggle").forEach((button) => {
  button.addEventListener("click", () => {
    const input = button.parentElement.querySelector("input");
    const icon = button.querySelector("i");
    input.type = input.type === "password" ? "text" : "password";
    icon.classList.toggle("bi-eye");
    icon.classList.toggle("bi-eye-slash");
  });
});

document.querySelectorAll(".amount-grid label").forEach((label) => {
  label.addEventListener("click", () => {
    document.querySelectorAll(".amount-grid label").forEach((item) => item.classList.remove("selected"));
    label.classList.add("selected");
  });
});
