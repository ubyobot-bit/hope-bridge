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

document.querySelectorAll('input[name="payment_method"]').forEach((input) => {
  input.addEventListener("change", () => {
    document.querySelectorAll(".payment-section").forEach((section) => {
      section.classList.toggle("d-none", section.dataset.method !== input.value);
    });
  });
});

const supportChat = document.querySelector("#supportChat");
document.querySelector(".chat-toggle")?.addEventListener("click", () => {
  supportChat?.classList.add("open");
});
document.querySelector(".chat-close")?.addEventListener("click", () => {
  supportChat?.classList.remove("open");
});
