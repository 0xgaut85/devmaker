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
 * Insert text char-by-char at human speed. Uses keyboard event sequence
 * matching real browser behavior: keydown → beforeinput → DOM change → input → keyup.
 * document.execCommand("insertText") fires native beforeinput+input automatically;
 * we add keydown/keyup to satisfy editors that listen for keyboard events.
 */
async function _typeCharByChar(element, text, minDelay = 25, maxDelay = 70) {
  for (let i = 0; i < text.length; i++) {
    const char = text[i];

    element.dispatchEvent(new KeyboardEvent("keydown", {
      key: char, bubbles: true, cancelable: true,
    }));

    document.execCommand("insertText", false, char);

    element.dispatchEvent(new KeyboardEvent("keyup", {
      key: char, bubbles: true, cancelable: true,
    }));

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
 * Type text into a DraftJS editor.
 *  - Short texts (<=150 chars): char-by-char at human speed.
 *  - Long texts (>150 chars): type first 30 chars slowly, paste the rest.
 *    Falls back to fast char-by-char (5-10ms) if paste doesn't register.
 */
async function humanType(element, text) {
  element.focus();
  await sleep(randomBetween(150, 400));

  if (text.length <= 150) {
    await _typeCharByChar(element, text);
    return;
  }

  // Long text: type prefix slowly, paste the rest
  const prefixLen = Math.min(30, text.length);
  const prefix = text.slice(0, prefixLen);
  const remainder = text.slice(prefixLen);

  await _typeCharByChar(element, prefix);
  await sleep(randomBetween(300, 700));

  const beforePaste = getTextboxContent(element).length;
  _pasteText(element, remainder);
  await sleep(randomBetween(400, 800));

  const afterPaste = getTextboxContent(element).length;
  if (afterPaste >= beforePaste + remainder.length * 0.5) {
    return; // paste worked
  }

  // Paste didn't register — fast char-by-char fallback
  console.log("[DevMaker] Paste not accepted by DraftJS, falling back to fast typing");
  await _typeCharByChar(element, remainder, 5, 15);
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
