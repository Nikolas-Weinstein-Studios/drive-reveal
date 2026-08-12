/*
 * Works out which Drive item the user means, then hands it to the local helper by
 * navigating to a gdrivereveal:// URL. Firefox passes that to the OS and leaves the
 * Drive page where it is.
 *
 * Two sources for the target, in order of reliability:
 *
 *   1. A selected row in the file grid. Best when the user is browsing a folder and
 *      wants one specific file. Depends on Drive's markup, which is obfuscated and
 *      changes without notice, so every selector here is treated as optional.
 *   2. The page URL. Always present, never changes shape without a visible redesign,
 *      and correct whenever the user just wants the folder they are looking at.
 *
 * Only the ID travels to the helper. The helper does the parsing, so this file stays
 * small and a Drive URL change means editing Python, not reinstalling an extension.
 */

const PROTOCOL = "gdrivereveal";

/** Drive IDs are base64url-ish; the length floor rejects short DOM ids that are not IDs. */
const ID_RE = /^[A-Za-z0-9_-]{15,}$/;

/**
 * Read the ID of a single selected item in the file grid.
 * Returns null when nothing, or more than one thing, is selected.
 */
function selectedItemId() {
  const selectors = [
    '[role="row"][aria-selected="true"][data-id]',
    '[role="gridcell"][aria-selected="true"][data-id]',
    '[aria-selected="true"][data-id]',
    '.a-da-zc[aria-selected="true"][data-id]',
  ];

  for (const selector of selectors) {
    let nodes;
    try {
      nodes = document.querySelectorAll(selector);
    } catch (e) {
      continue; // a selector Drive no longer supports must not break the rest
    }
    const ids = new Set();
    for (const node of nodes) {
      const id = node.getAttribute("data-id");
      if (id && ID_RE.test(id)) ids.add(id);
    }
    // Ambiguous multi-selection: fall back to the folder in the address bar instead
    // of guessing which of several files the user meant.
    if (ids.size === 1) return [...ids][0];
    if (ids.size > 1) return null;
  }
  return null;
}

/** Build the payload the helper receives. Prefers a selected file over the page URL. */
function buildTarget() {
  const id = selectedItemId();
  if (id) return `${PROTOCOL}://reveal?id=${encodeURIComponent(id)}`;
  return `${PROTOCOL}://reveal?url=${encodeURIComponent(location.href)}`;
}

/**
 * Fire the protocol URL. A top-level assignment is used rather than an iframe because
 * Drive sends a strict Content-Security-Policy that blocks framing a custom scheme.
 * Firefox does not unload the page for a scheme it hands to the OS.
 */
function launch(target) {
  try {
    window.location.href = target;
    return true;
  } catch (e) {
    return false;
  }
}

function toast(message, isError) {
  const el = document.createElement("div");
  el.textContent = message;
  Object.assign(el.style, {
    position: "fixed",
    zIndex: "2147483647",
    bottom: "24px",
    left: "50%",
    transform: "translateX(-50%)",
    padding: "10px 16px",
    borderRadius: "6px",
    font: "13px/1.4 system-ui, sans-serif",
    color: "#fff",
    background: isError ? "#b3261e" : "#202124",
    boxShadow: "0 2px 10px rgba(0,0,0,.3)",
    pointerEvents: "none",
    maxWidth: "80vw",
  });
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

browser.runtime.onMessage.addListener((message) => {
  if (message !== "reveal") return;

  const target = buildTarget();
  if (!launch(target)) {
    toast("Could not hand the link to the local helper.", true);
    return Promise.resolve({ ok: false });
  }
  // The helper reports its own failures in a dialog; success is silent by design,
  // since the Explorer or Finder window appearing is the confirmation.
  return Promise.resolve({ ok: true, target });
});
