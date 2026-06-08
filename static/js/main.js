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

const cryptoBookElement = document.querySelector("#cryptoBookData");
const assetSelect = document.querySelector("#assetSelect");
const networkSelect = document.querySelector("#networkSelect");
if (cryptoBookElement && assetSelect && networkSelect) {
  const cryptoBook = JSON.parse(cryptoBookElement.textContent);
  const refreshNetworks = () => {
    const networks = Object.keys(cryptoBook[assetSelect.value] || {});
    networkSelect.innerHTML = "";
    networks.forEach((network) => {
      const option = document.createElement("option");
      option.value = network;
      option.textContent = network;
      networkSelect.appendChild(option);
    });
  };
  assetSelect.addEventListener("change", refreshNetworks);
  refreshNetworks();
}

const showToast = (message) => {
  const toast = document.createElement("div");
  toast.className = "mini-toast";
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 2200);
};

document.querySelectorAll("[data-copy-target]").forEach((button) => {
  button.addEventListener("click", async () => {
    const target = document.querySelector(button.dataset.copyTarget);
    const value = target?.textContent?.trim();
    if (!value) return;
    await navigator.clipboard.writeText(value);
    showToast("Copied to clipboard.");
  });
});

document.querySelectorAll("[data-share-url]").forEach((button) => {
  button.addEventListener("click", async () => {
    const url = button.dataset.shareUrl;
    if (navigator.share) {
      await navigator.share({ title: "HopeBridge", url });
    } else {
      await navigator.clipboard.writeText(url);
      showToast("Share link copied.");
    }
  });
});

const supportChat = document.querySelector("#supportChat");
document.querySelector(".chat-toggle")?.addEventListener("click", () => {
  supportChat?.classList.add("open");
});
document.querySelector(".chat-close")?.addEventListener("click", () => {
  supportChat?.classList.remove("open");
});
