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
 * Type text reliably. Uses word-by-word insertion to avoid contentEditable
 * selection bugs that cause char-by-char typing to delete or truncate content.
 * No typo simulation — it was causing delete to wipe large chunks.
 */
async function humanType(element, text) {
  element.focus();
  await sleep(randomBetween(200, 500));

  const words = text.split(/(\s+)/);
  for (let i = 0; i < words.length; i++) {
    const chunk = words[i];
    if (!chunk) continue;

    element.dispatchEvent(new InputEvent("beforeinput", { inputType: "insertText", data: chunk, bubbles: true, cancelable: true }));
    document.execCommand("insertText", false, chunk);

    const delay = chunk.match(/\s/) ? randomBetween(50, 150) : randomBetween(40, 120);
    await sleep(delay);

    if (chunk.endsWith(".") || chunk.endsWith("!")) {
      await sleep(randomBetween(150, 350));
    }
  }
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
