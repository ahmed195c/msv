/*
 * Multi-photo inputs marked with data-keep-files: each new pick (a camera shot
 * or more files from the gallery) is ADDED to the photos already chosen.
 * Browsers replace the whole selection on every pick, so taking several photos
 * one by one with the camera would otherwise keep only the last one.
 * Chosen files show as thumbnails, each with a button to drop it.
 */
(function () {
  if (typeof DataTransfer === 'undefined') return;

  var SELECTOR = 'input[type="file"][data-keep-files]';
  var kept = new WeakMap();

  function fileKey(file) {
    return file.name + '|' + file.size + '|' + file.lastModified;
  }

  function addStyles() {
    if (document.getElementById('keep-files-style')) return;
    var style = document.createElement('style');
    style.id = 'keep-files-style';
    style.textContent =
      '.keep-files{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}' +
      '.keep-files:empty{display:none}' +
      '.keep-files__item{position:relative;width:76px;height:76px;border-radius:10px;overflow:hidden;' +
      'background:#eef2f6;border:1px solid #d7dfe8;display:flex;align-items:center;justify-content:center;' +
      'font-size:11px;font-weight:700;color:#41576f;text-align:center;padding:4px;box-sizing:border-box;word-break:break-all}' +
      '.keep-files__item img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}' +
      '.keep-files__remove{position:absolute;top:4px;inset-inline-end:4px;width:24px;height:24px;border-radius:50%;' +
      'border:none;background:rgba(15,23,42,.72);color:#fff;font-size:15px;line-height:24px;padding:0;cursor:pointer;z-index:1}' +
      '.keep-files__count{flex-basis:100%;font-size:12px;font-weight:700;color:#41576f}';
    document.head.appendChild(style);
  }

  function previewBox(input) {
    var box = input.keepFilesBox;
    if (!box) {
      box = document.createElement('div');
      box.className = 'keep-files';
      var card = input.closest('.upload-card');
      (card || input.parentNode).appendChild(box);
      input.keepFilesBox = box;
    }
    return box;
  }

  function render(input, files) {
    var box = previewBox(input);
    (input.keepFilesUrls || []).forEach(function (url) { URL.revokeObjectURL(url); });
    input.keepFilesUrls = [];
    box.textContent = '';
    if (!files.length) return;
    var count = document.createElement('div');
    count.className = 'keep-files__count';
    count.textContent = files.length === 1 ? 'صورة واحدة جاهزة للحفظ' : files.length + ' صور جاهزة للحفظ';
    box.appendChild(count);
    files.forEach(function (file, index) {
      var item = document.createElement('div');
      item.className = 'keep-files__item';
      if (file.type && file.type.indexOf('image/') === 0) {
        var url = URL.createObjectURL(file);
        input.keepFilesUrls.push(url);
        var img = document.createElement('img');
        img.src = url;
        img.alt = file.name;
        item.appendChild(img);
      } else {
        item.textContent = file.name;
      }
      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'keep-files__remove';
      remove.setAttribute('aria-label', 'حذف ' + file.name);
      remove.textContent = '×';
      remove.addEventListener('click', function () {
        var rest = (kept.get(input) || []).filter(function (_, i) { return i !== index; });
        setFiles(input, rest);
        // Let the page's own upload card update its summary too.
        input.dispatchEvent(new Event('change', { bubbles: true }));
      });
      item.appendChild(remove);
      box.appendChild(item);
    });
  }

  function setFiles(input, files) {
    var dt = new DataTransfer();
    files.forEach(function (file) { dt.items.add(file); });
    input.files = dt.files;
    kept.set(input, files);
    render(input, files);
  }

  // Capture phase: the merged list is in place before the page's own handlers read it.
  document.addEventListener('change', function (event) {
    var input = event.target;
    if (!input.matches || !input.matches(SELECTOR)) return;
    var previous = kept.get(input) || [];
    var seen = {};
    previous.forEach(function (file) { seen[fileKey(file)] = true; });
    var added = Array.from(input.files || []).filter(function (file) { return !seen[fileKey(file)]; });
    setFiles(input, previous.concat(added));
  }, true);

  addStyles();
})();
