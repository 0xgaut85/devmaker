/**
 * Human simulation — realistic mouse movement, typing, and scrolling.
 * Makes extension interactions indistinguishable from real user behavior.
 */

function randomBetween(min, max) {
  return Math.random() * (max - min) + min;
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function clearTextbox(element) {
  element.focus();
  await sleep(randomBetween(100, 300));
  const current = element.textContent || element.innerText || element.value || "";
  if (current.trim().length > 0) {
    document.execCommand("selectAll", false);
    await sleep(randomBetween(50, 150));
    document.execCommand("delete", false);
    await sleep(randomBetween(200, 500));
  }
}

function getTextboxContent(element) {
  return (element.textContent || element.innerText || element.value || "").trim();
}

/**
 * Insert text char-by-char using execCommand("insertText") which fires
 * trusted beforeinput+input events. Do NOT add synthetic KeyboardEvents —
 * they cause DraftJS to double-process the input and corrupt editor state,
 * leaving the Post button permanently disabled.
 */
async function _typeCharByChar(element, text, minDelay = 25, maxDelay = 70) {
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    document.execCommand("insertText", false, char);

    await sleep(randomBetween(minDelay, maxDelay));

    if (char === " " && Math.random() < 0.1) {
      await sleep(randomBetween(80, 200));
    }
    if ((char === "." || char === "!" || char === "?") && Math.random() < 0.2) {
      await sleep(randomBetween(100, 300));
    }
  }
}

/**
 * Paste text via synthetic ClipboardEvent. DraftJS handles paste natively
 * and processes the entire text in one React render cycle.
 * Returns true if paste was accepted, false otherwise.
 */
function _pasteText(element, text) {
  const dt = new DataTransfer();
  dt.setData("text/plain", text);
  element.dispatchEvent(new ClipboardEvent("paste", {
    clipboardData: dt,
    bubbles: true,
    cancelable: true,
  }));
}

/**
 * Type text into a DraftJS editor. Tries paste first (most reliable for
 * React editors since it updates both DOM and internal state in one cycle),
 * then falls back to char-by-char execCommand if paste doesn't register.
 */
async function humanType(element, text) {
  element.focus();
  await sleep(randomBetween(150, 400));

  // Attempt 1: clipboard paste (DraftJS handles paste natively)
  _pasteText(element, text);
  await sleep(randomBetween(500, 1000));

  const afterPaste = getTextboxContent(element).length;
  if (afterPaste >= text.trim().length * 0.8) {
    console.log("[DevMaker] Paste accepted (" + afterPaste + " chars)");
    return;
  }

  // Attempt 2: char-by-char with execCommand("insertText")
  console.log("[DevMaker] Paste not accepted (" + afterPaste + " chars), falling back to char-by-char");
  await clearTextbox(element);
  await sleep(randomBetween(200, 400));
  element.focus();
  await sleep(randomBetween(100, 200));
  await _typeCharByChar(element, text, 8, 25);
}

async function humanClick(element) {
  const rect = element.getBoundingClientRect();
  const x = rect.left + randomBetween(rect.width * 0.2, rect.width * 0.8);
  const y = rect.top + randomBetween(rect.height * 0.2, rect.height * 0.8);

  element.dispatchEvent(new MouseEvent("mouseover", { clientX: x, clientY: y, bubbles: true }));
  await sleep(randomBetween(50, 200));
  element.dispatchEvent(new MouseEvent("mousemove", { clientX: x, clientY: y, bubbles: true }));
  await sleep(randomBetween(30, 100));
  element.dispatchEvent(new MouseEvent("mousedown", { clientX: x, clientY: y, bubbles: true }));
  await sleep(randomBetween(50, 150));
  element.dispatchEvent(new MouseEvent("mouseup", { clientX: x, clientY: y, bubbles: true }));
  element.click();
  await sleep(randomBetween(100, 300));
}

async function humanScroll(pixels) {
  const direction = pixels > 0 ? 1 : -1;
  let remaining = Math.abs(pixels);
  while (remaining > 0) {
    const chunk = Math.min(remaining, randomBetween(80, 200));
    window.scrollBy({ top: chunk * direction, behavior: "auto" });
    remaining -= chunk;
    await sleep(randomBetween(20, 80));
  }
}

async function smoothScrollDown(count = 1) {
  for (let i = 0; i < count; i++) {
    await humanScroll(window.innerHeight * randomBetween(0.7, 1.3));
    await sleep(randomBetween(800, 3000));
    if (Math.random() < 0.2) {
      await sleep(randomBetween(2000, 8000));
    }
  }
}

async function waitForElement(selector, timeout = 10000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const el = document.querySelector(selector);
    if (el) return el;
    await sleep(200);
  }
  return null;
}
