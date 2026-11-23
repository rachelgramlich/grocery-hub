(function () {
  if (window.__gwExternalLinksInstalled) {
    return;
  }
  window.__gwExternalLinksInstalled = true;

  var REL = "noopener noreferrer";

  function patchAnchor(anchor) {
    var href = anchor.getAttribute("href");
    if (!href || href.charAt(0) === "#" || href.indexOf("javascript:") === 0) {
      return;
    }
    if (!anchor.hasAttribute("target")) {
      anchor.setAttribute("target", "_blank");
      anchor.setAttribute("rel", REL);
    }
  }

  function patchTree(root) {
    if (!root || root.nodeType !== 1) {
      return;
    }
    if (root.matches && root.matches("a[href]")) {
      patchAnchor(root);
    }
    root.querySelectorAll("a[href]").forEach(patchAnchor);
  }

  patchTree(document);
  var observer = new MutationObserver(function (mutations) {
    mutations.forEach(function (mutation) {
      mutation.addedNodes.forEach(function (node) {
        patchTree(node);
      });
    });
  });
  observer.observe(document.body, { childList: true, subtree: true });
})();
