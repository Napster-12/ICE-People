// On-page document viewer, copied from IGSP (16 Nov 2026, at the user's request).
// Links marked data-pdf-view open the PDF in a window over the page (70% of the screen) instead of a new tab,
// without the browser viewer's toolbar (page count) or thumbnail sidebar.
// Without JavaScript the link still works and opens the PDF in the same tab.
(function () {
    var pdfViewer = null, pdfReturnFocus = null;
    function buildPdfViewer() {
        var wrap = document.createElement('div');
        wrap.className = 'pdfv';
        wrap.hidden = true;
        wrap.innerHTML =
            '<div class="pdfv-backdrop" data-pdfv-close></div>' +
            '<div class="pdfv-dialog" role="dialog" aria-modal="true" aria-labelledby="pdfv-title">' +
            '  <div class="pdfv-head">' +
            '    <strong id="pdfv-title" class="pdfv-title"></strong>' +
            '    <a class="pdfv-download" download>Download</a>' +
            '    <button type="button" class="pdfv-close" data-pdfv-close aria-label="Close document">&times;</button>' +
            '  </div>' +
            '  <iframe class="pdfv-frame" title="Document preview"></iframe>' +
            '</div>';
        document.body.appendChild(wrap);
        return wrap;
    }
    function openPdf(link) {
        pdfViewer = pdfViewer || buildPdfViewer();
        pdfReturnFocus = link;
        pdfViewer.querySelector('.pdfv-title').textContent = link.dataset.pdfTitle || 'Document';
        pdfViewer.querySelector('.pdfv-download').href = link.href.split('#')[0] + (link.href.indexOf('?') < 0 ? '?download=1' : '&download=1');
        // Hide the browser PDF viewer's toolbar (page count) and thumbnail sidebar; fit the page to the width.
        // toolbar/navpanes: Chrome, Edge, Safari. pagemode: Firefox.
        var url = link.href.split('#')[0];
        var isImage = /\.(png|jpe?g)$/i.test(link.dataset.pdfFile || '');
        pdfViewer.querySelector('.pdfv-frame').src = isImage ? url : url + '#toolbar=0&navpanes=0&pagemode=none&view=FitH';
        pdfViewer.hidden = false;
        document.body.classList.add('pdfv-open');
        pdfViewer.querySelector('.pdfv-close').focus();
    }
    function closePdf() {
        if (!pdfViewer || pdfViewer.hidden) { return; }
        pdfViewer.hidden = true;
        pdfViewer.querySelector('.pdfv-frame').src = 'about:blank';
        document.body.classList.remove('pdfv-open');
        if (pdfReturnFocus) { pdfReturnFocus.focus(); }
    }
    document.addEventListener('click', function (e) {
        var link = e.target.closest('a[data-pdf-view]');
        if (link && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
            e.preventDefault();
            openPdf(link);
            return;
        }
        if (e.target.closest('[data-pdfv-close]')) { closePdf(); }
    });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') { closePdf(); }
    });
})();
