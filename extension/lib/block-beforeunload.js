/**
 * Blocks the "Changes you made may not be saved" / "Leave site?" dialog
 * by intercepting beforeunload event registration at the earliest possible moment.
 * Runs at document_start before X's own scripts can register handlers.
 */

(function () {
  const _origAddEventListener = EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener = function (type, listener, options) {
    if (type === "beforeunload") return;
    return _origAddEventListener.call(this, type, listener, options);
  };

  const _origRemoveEventListener = EventTarget.prototype.removeEventListener;
  EventTarget.prototype.removeEventListener = function (type, listener, options) {
    if (type === "beforeunload") return;
    return _origRemoveEventListener.call(this, type, listener, options);
  };

  Object.defineProperty(window, "onbeforeunload", {
    get: () => null,
    set: () => {},
    configurable: false,
  });
})();
