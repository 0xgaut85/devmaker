const backendUrlInput = document.getElementById("backendUrl");
const accountIdInput = document.getElementById("accountId");
const connectBtn = document.getElementById("connectBtn");
const disconnectBtn = document.getElementById("disconnectBtn");
const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const errorMsg = document.getElementById("errorMsg");

function showError(msg) {
  errorMsg.textContent = msg;
  errorMsg.style.display = msg ? "block" : "none";
}

function updateUI(connected, url, id) {
  statusDot.classList.toggle("connected", connected);
  statusText.textContent = connected ? "Connected" : "Disconnected";
  connectBtn.style.display = connected ? "none" : "block";
  connectBtn.disabled = false;
  connectBtn.textContent = "Connect";
  disconnectBtn.style.display = connected ? "block" : "none";
  if (url) backendUrlInput.value = url;
  if (id) accountIdInput.value = id;
  if (connected) showError("");
}

chrome.runtime.sendMessage({ type: "getStatus" }, (resp) => {
  if (resp) updateUI(resp.connected, resp.backendUrl, resp.accountId);
});

connectBtn.addEventListener("click", () => {
  const url = backendUrlInput.value.trim();
  const id = accountIdInput.value.trim();
  if (!url || !id) {
    showError("Both fields are required");
    return;
  }

  showError("");
  connectBtn.disabled = true;
  connectBtn.textContent = "Connecting...";

  chrome.runtime.sendMessage(
    { type: "configure", backendUrl: url, accountId: id },
    () => {
      let checks = 0;
      const interval = setInterval(() => {
        checks++;
        chrome.runtime.sendMessage({ type: "getStatus" }, (resp) => {
          if (resp && resp.connected) {
            clearInterval(interval);
            updateUI(true, resp.backendUrl, resp.accountId);
          } else if (checks >= 5) {
            clearInterval(interval);
            updateUI(false, url, id);
            showError("Connection failed. Check URL, Account ID, and that the backend is running.");
          }
        });
      }, 1000);
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
    updateUI(msg.status === "connected", backendUrlInput.value, accountIdInput.value);
  }
});
