const backendUrlInput = document.getElementById("backendUrl");
const accountIdInput = document.getElementById("accountId");
const connectBtn = document.getElementById("connectBtn");
const disconnectBtn = document.getElementById("disconnectBtn");
const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");

function updateUI(connected, url, id) {
  statusDot.classList.toggle("connected", connected);
  statusText.textContent = connected ? "Connected" : "Disconnected";
  connectBtn.style.display = connected ? "none" : "block";
  disconnectBtn.style.display = connected ? "block" : "none";
  if (url) backendUrlInput.value = url;
  if (id) accountIdInput.value = id;
}

chrome.runtime.sendMessage({ type: "getStatus" }, (resp) => {
  if (resp) updateUI(resp.connected, resp.backendUrl, resp.accountId);
});

connectBtn.addEventListener("click", () => {
  const url = backendUrlInput.value.trim();
  const id = accountIdInput.value.trim();
  if (!url || !id) return;

  chrome.runtime.sendMessage(
    { type: "configure", backendUrl: url, accountId: id },
    () => {
      setTimeout(() => {
        chrome.runtime.sendMessage({ type: "getStatus" }, (resp) => {
          if (resp) updateUI(resp.connected, resp.backendUrl, resp.accountId);
        });
      }, 2000);
    }
  );
});

disconnectBtn.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "disconnect" }, () => {
    updateUI(false);
  });
});

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "status") {
    updateUI(msg.status === "connected");
  }
});
