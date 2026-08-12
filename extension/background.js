/*
 * Three ways to trigger a reveal: the toolbar button, a right-click on the page, and
 * Alt+Shift+R. All three do the same thing - ask the content script in the active tab
 * to work out the target and hand it to the local helper.
 */

const DRIVE_HOSTS = ["drive.google.com", "docs.google.com"];
const MENU_ID = "drive-reveal-open-local";

function isDrivePage(url) {
  try {
    return DRIVE_HOSTS.includes(new URL(url).hostname);
  } catch (e) {
    return false;
  }
}

async function reveal(tab) {
  if (!tab || !tab.id || !isDrivePage(tab.url || "")) return;
  try {
    await browser.tabs.sendMessage(tab.id, "reveal");
  } catch (e) {
    // Content script not injected yet - happens on a tab that was already open when
    // the extension loaded. Reloading is the documented fix; say so rather than
    // failing silently.
    console.warn("drive-reveal: no content script in this tab yet.", e);
  }
}

browser.browserAction.onClicked.addListener(reveal);

browser.commands.onCommand.addListener(async (command) => {
  if (command !== "reveal") return;
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  await reveal(tab);
});

browser.contextMenus.create({
  id: MENU_ID,
  title: "Reveal in local Drive folder",
  contexts: ["page", "link", "selection"],
  documentUrlPatterns: [
    "https://drive.google.com/*",
    "https://docs.google.com/document/*",
    "https://docs.google.com/spreadsheets/*",
    "https://docs.google.com/presentation/*",
  ],
});

browser.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === MENU_ID) reveal(tab);
});
