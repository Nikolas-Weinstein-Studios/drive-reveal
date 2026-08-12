/*
 * Readable source for the bookmarklet. install.html carries the minified copy that
 * actually gets dragged to the bookmarks bar; edit this file, then re-run
 *   python bookmarklet/build.py
 * to regenerate it.
 *
 * The bookmarklet is the no-install path: no extension, no signing, and it rides
 * Firefox Sync to every machine along with the rest of the bookmarks. It does the same
 * job as the extension's content script, minus the toolbar button and hotkey.
 */
(function () {
  var ID = /^[A-Za-z0-9_-]{15,}$/;
  var ids = {};
  var count = 0;

  // A single selected row means the user wants that file. Anything else (nothing
  // selected, or several) falls back to the folder in the address bar.
  var nodes = document.querySelectorAll('[aria-selected="true"][data-id]');
  for (var i = 0; i < nodes.length; i++) {
    var v = nodes[i].getAttribute('data-id');
    if (ID.test(v) && !ids[v]) {
      ids[v] = 1;
      count++;
    }
  }

  var target;
  if (count === 1) {
    target = 'gdrivereveal://reveal?id=' + encodeURIComponent(Object.keys(ids)[0]);
  } else {
    target = 'gdrivereveal://reveal?url=' + encodeURIComponent(location.href);
  }

  location.href = target;
})();
