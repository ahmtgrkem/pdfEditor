"""XFA formunun tarayıcı içindeki çalışma zamanı (JavaScript).

:mod:`app.core.xfa_html` şablonu HTML'e derler; burada bulunan betik ise onu
**yaşatır**: XFA nesne modelini (``form``, ``xfa``, ``app``) DOM üzerine
kurar, şablondaki olay betiklerini çalıştırır ve sayfalamayı yeniden hesaplar.

Neden ayrı bir dosya değil de Python sabiti: uygulama PyInstaller ile tek
dosyaya paketlendiğinde ek veri dosyası taşımak gerekmiyor.

Kapsam
------
Gerçeklenen: ``rawValue``, ``presence``, ``access``, ``border.presence``,
``parent``, ``index``, ``instanceManager`` (satır ekle/sil), ``resolveNode``
/``resolveNodes``, ``clearItems``/``addItem``, ``xfa.layout.page(Count)``,
``app.alert``, ``xfa.host``, dosya eki nesneleri ve
``click``/``exit``/``enter``/``change``/``preOpen``/``ready``/``preSave``
olayları.

Gerçeklenmeyen: FormCalc (bu belgede kullanılmıyor), zengin metin
biçimlendirme, dijital imza.
"""
from __future__ import annotations

RUNTIME_JS = r"""
(function () {
"use strict";

var CFG = window.XFA_CONFIG || {};
var PAGE = CFG.page || {w: 595, h: 842, cx: 28, cy: 18, cw: 539, ch: 800};
var SCREEN_GAP = 14;               // ekranda sayfalar arası boşluk (pt)
var GAP = SCREEN_GAP;              // yazdırırken 0'a çekilir (bkz. setPrintMode)
var ABORT = {xfaAbort: true};      // dosya seçimi bekleniyor: betiği kes

var PX = 96 / 72;                  // 1 punto kaç CSS pikseli
var pagesEl, bgEl, flowEl, furnitureTpl, toastEl;
var ROOT = null;                   // kök alt formun DOM öğesi
var SCRIPTS = {};                  // som -> {activity: [kod...]}
var PRISTINE = {};                 // yinelenebilir alt formların kalıbı
var NS = {};                       // <variables> ad alanları
var PICKED = {};                   // dosya seçiciden gelen ekler
var OBJECTS = {};                  // içe aktarılmış ek nesneleri
var ready = false;
var relayoutPending = false;

// ==================================================================
// Küçük yardımcılar
// ==================================================================
function isNode(el) { return !!(el && el.dataset && el.dataset.kind); }

function kids(el) {
  var out = [], stack = [], i;
  for (i = el.children.length - 1; i >= 0; i--) stack.push(el.children[i]);
  while (stack.length) {
    var e = stack.pop();
    if (isNode(e)) out.push(e);
    else for (i = e.children.length - 1; i >= 0; i--) stack.push(e.children[i]);
  }
  return out;
}

function byName(el, name) {
  var all = kids(el), out = [], i;
  for (i = 0; i < all.length; i++) {
    if (all[i].dataset.name === name) out.push(all[i]);
  }
  return out;
}

function parentEl(el) {
  var p = el.parentElement;
  while (p && !isNode(p)) {
    if (p === flowEl || p === document.body) return null;
    p = p.parentElement;
  }
  return p;
}

function control(el) {
  return el.querySelector(':scope .xw > .xc, :scope .xw > input.xchk');
}

function overlay(el) {
  var o = el.firstElementChild;
  return (o && o.classList.contains('xhl')) ? o : null;
}

function toast(msg) {
  if (!toastEl) return;
  toastEl.textContent = msg;
  toastEl.classList.add('on');
  clearTimeout(toast._t);
  toast._t = setTimeout(function () { toastEl.classList.remove('on'); }, 4200);
}

function host() { return window.xfaHost || null; }

// ==================================================================
// Değer erişimi
// ==================================================================
function groupMembers(el) {
  // exclGroup üyeleri: doğrudan altındaki onay/radyo alanları
  var out = [], k = kids(el), i;
  for (i = 0; i < k.length; i++) {
    if (k[i].dataset.type === 'check') out.push(k[i]);
  }
  return out;
}

function getValue(el) {
  var kind = el.dataset.kind;
  if (kind === 'exclGroup') {
    var m = groupMembers(el), i, c;
    for (i = 0; i < m.length; i++) {
      c = control(m[i]);
      if (c && c.checked) return c.dataset.on || '1';
    }
    return '';
  }
  if (kind === 'draw') {
    var s = el.querySelector('.xd-in > span');
    return s ? s.textContent : '';
  }
  var ctl = control(el);
  if (!ctl) return '';
  if (el.dataset.type === 'check') return ctl.checked ? (ctl.dataset.on || '1') : '';
  return ctl.value;
}

function setValue(el, val, silent) {
  var kind = el.dataset.kind;
  var text = (val === null || val === undefined) ? '' : String(val);
  if (kind === 'exclGroup') {
    var m = groupMembers(el), i, c;
    for (i = 0; i < m.length; i++) {
      c = control(m[i]);
      if (c) c.checked = (text !== '' && (c.dataset.on || '1') === text);
    }
    if (!silent) schedule();
    return;
  }
  if (kind === 'draw') {
    var s = el.querySelector('.xd-in > span');
    if (s) s.textContent = text;
    if (!silent) schedule();
    return;
  }
  var ctl = control(el);
  if (!ctl) return;
  if (el.dataset.type === 'check') {
    ctl.checked = (text !== '' && text === (ctl.dataset.on || '1'));
  } else if (ctl.tagName === 'SELECT') {
    ctl.value = text;
    if (ctl.value !== text) {             // liste henüz doldurulmadıysa
      ctl.dataset.pending = text;
    }
  } else {
    ctl.value = text;
  }
  if (!silent) schedule();
}

// ==================================================================
// Nesne modeli
// ==================================================================
function api(el) {
  var self = {};

  Object.defineProperty(self, 'rawValue', {
    get: function () {
      var v = getValue(el);
      if (v === '' || v === null || v === undefined) return null;
      if (el.dataset.type === 'number') {
        var n = Number(v);
        if (!isNaN(n) && v !== '') return n;
      }
      return v;
    },
    set: function (v) { setValue(el, v); },
    enumerable: true, configurable: true
  });
  // formattedValue / value.oneOfChild yerine pratik takma adlar
  Object.defineProperty(self, 'formattedValue', {
    get: function () { return getValue(el); },
    set: function (v) { setValue(el, v); },
    configurable: true
  });

  Object.defineProperty(self, 'presence', {
    get: function () { return el.dataset.presence || 'visible'; },
    set: function (v) { setPresence(el, String(v)); },
    enumerable: true, configurable: true
  });

  Object.defineProperty(self, 'access', {
    get: function () { return el.dataset.access || 'open'; },
    set: function (v) {
      el.dataset.access = String(v);
      var locked = (v === 'readOnly' || v === 'protected' ||
                    v === 'nonInteractive');
      var ctls = el.querySelectorAll('.xc, input.xchk'), i;
      for (i = 0; i < ctls.length; i++) {
        ctls[i].disabled = locked;
        ctls[i].readOnly = locked && ctls[i].tagName !== 'SELECT';
      }
      el.classList.toggle('xlock', locked);
    },
    enumerable: true, configurable: true
  });

  Object.defineProperty(self, 'border', {
    get: function () {
      var ov = overlay(el);
      return {
        get presence() { return ov ? (ov.dataset.presence || 'visible') : 'visible'; },
        set presence(v) {
          if (!ov) return;
          ov.dataset.presence = String(v);
          ov.style.display = (v === 'visible') ? '' : 'none';
        },
        fill: {color: {value: ''}}
      };
    },
    configurable: true
  });

  Object.defineProperty(self, 'name', {
    get: function () { return el.dataset.name || ''; }, configurable: true
  });
  Object.defineProperty(self, 'className', {
    get: function () { return el.dataset.kind; }, configurable: true
  });
  Object.defineProperty(self, 'somExpression', {
    get: function () { return el.dataset.som; }, configurable: true
  });
  Object.defineProperty(self, 'parent', {
    get: function () { return node(parentEl(el)); }, configurable: true
  });
  Object.defineProperty(self, 'index', {
    get: function () { return instanceIndex(el); }, configurable: true
  });
  Object.defineProperty(self, 'instanceManager', {
    get: function () { return manager(el); }, configurable: true
  });
  Object.defineProperty(self, 'all', {
    get: function () { return nodeList(siblings(el)); }, configurable: true
  });
  Object.defineProperty(self, 'ui', {
    get: function () { return {oneOfChild: {}}; }, configurable: true
  });
  Object.defineProperty(self, 'value', {
    get: function () {
      return {
        get text() { return getValue(el); },
        set text(v) { setValue(el, v); },
        oneOfChild: {
          get value() { return getValue(el); },
          set value(v) { setValue(el, v); }
        }
      };
    },
    configurable: true
  });
  Object.defineProperty(self, 'length', {
    get: function () { return siblings(el).length; }, configurable: true
  });

  self.__el = el;

  self.resolveNode = function (expr) { return resolveFrom(el, expr, false); };
  self.resolveNodes = function (expr) { return resolveFrom(el, expr, true); };
  self.item = function (i) { return node(siblings(el)[i] || null); };

  self.clearItems = function () {
    var c = control(el);
    if (c && c.tagName === 'SELECT') {
      c.innerHTML = '<option value=""></option>';
    }
  };
  self.addItem = function (text, value) {
    var c = control(el);
    if (!c || c.tagName !== 'SELECT') return;
    var o = document.createElement('option');
    o.value = (value === undefined || value === null) ? String(text) : String(value);
    o.textContent = String(text);
    c.appendChild(o);
    if (c.dataset.pending && c.dataset.pending === o.value) {
      c.value = o.value;
      delete c.dataset.pending;
    }
  };
  self.deleteItem = function (i) {
    var c = control(el);
    if (c && c.tagName === 'SELECT' && c.options[i + 1]) {
      c.remove(i + 1);
    }
  };
  self.setItemState = function () {};
  self.execEvent = function (name) { fire(el, String(name).replace(/^on/, '')); };
  self.execValidate = function () { return true; };
  self.execCalculate = function () { fire(el, 'calculate'); };
  self.setFocus = function () { var c = control(el); if (c) c.focus(); };
  self.isNull = function () { return getValue(el) === ''; };
  self.toString = function () { return el.dataset.som; };
  self.valueOf = function () {
    var v = getValue(el);
    return v === '' ? null : v;
  };
  return self;
}

function node(el) {
  if (!el) return null;
  if (el.__xfa) return el.__xfa;
  var target = api(el);
  var proxy = new Proxy(target, {
    get: function (t, k) {
      if (typeof k !== 'string' || k in t) return t[k];
      var c = byName(el, k);
      if (c.length) return node(c[0]);
      return undefined;
    },
    set: function (t, k, v) {
      if (typeof k === 'string' && !(k in t)) {
        var c = byName(el, k);
        if (c.length) { setValue(c[0], v); return true; }
      }
      t[k] = v;
      return true;
    },
    has: function (t, k) {
      return (k in t) || (typeof k === 'string' && byName(el, k).length > 0);
    }
  });
  el.__xfa = proxy;
  return proxy;
}

function nodeList(els) {
  var list = {
    length: els.length,
    item: function (i) { return node(els[i] || null); }
  };
  for (var i = 0; i < els.length; i++) list[i] = node(els[i]);
  return list;
}

// -- örnekler (instanceManager) ------------------------------------
function siblings(el) {
  var p = el.parentElement;
  if (!p) return [el];
  var out = [], i;
  for (i = 0; i < p.children.length; i++) {
    var c = p.children[i];
    if (isNode(c) && c.dataset.name === el.dataset.name &&
        c.dataset.kind === el.dataset.kind) out.push(c);
  }
  return out.length ? out : [el];
}

/** Yinelenen kapların içindeki alanlar için dizinli SOM yolu. */
function somWithIndex(el) {
  var parts = [], cur = el;
  while (cur && cur !== ROOT) {
    var name = cur.dataset.name || '';
    var s = siblings(cur);
    parts.unshift(s.length > 1 ? name + '[' + instanceIndex(cur) + ']' : name);
    cur = parentEl(cur);
  }
  parts.unshift(ROOT.dataset.name);
  return parts.filter(function (p) { return p !== ''; }).join('.');
}

function instanceIndex(el) {
  var s = siblings(el);
  for (var i = 0; i < s.length; i++) if (s[i] === el) return i;
  return 0;
}

function manager(el) {
  var som = el.dataset.som;
  var minCount = parseInt(el.dataset.min || '1', 10) || 0;
  var maxCount = parseInt(el.dataset.max || '-1', 10);

  function list() { return siblings(el); }

  function makeClone() {
    var html = PRISTINE[som];
    if (!html) html = el.outerHTML;
    var box = document.createElement('div');
    box.innerHTML = html;
    var fresh = box.firstElementChild;
    // Kalıp gizliyse bile eklenen örnek görünür olmalı.
    fresh.style.display = '';
    fresh.dataset.presence = 'visible';
    return fresh;
  }

  return {
    get count() { return list().length; },
    set count(n) { this.setInstances(n); },
    get name() { return el.dataset.name; },
    get max() { return maxCount; },
    get min() { return minCount; },
    insertInstance: function (i) {
      var l = list();
      if (maxCount > 0 && l.length >= maxCount) {
        throw new Error('max instances');
      }
      var fresh = makeClone();
      var ref = l[Math.min(Math.max(i, 0), l.length - 1)];
      if (i >= l.length) ref.parentElement.insertBefore(fresh, ref.nextSibling);
      else ref.parentElement.insertBefore(fresh, ref);
      schedule();
      return node(fresh);
    },
    addInstance: function () {
      return this.insertInstance(list().length);
    },
    removeInstance: function (i) {
      var l = list();
      if (l.length <= Math.max(minCount, 1)) {
        throw new Error('min instances');
      }
      var victim = l[i] || l[l.length - 1];
      victim.parentElement.removeChild(victim);
      schedule();
    },
    setInstances: function (n) {
      var l = list();
      while (list().length < n) this.addInstance();
      while (list().length > n) this.removeInstance(list().length - 1);
    },
    moveInstance: function () {}
  };
}

// -- SOM çözümleme --------------------------------------------------
function splitSom(expr) {
  return String(expr)
    .replace(/^\$?(xfa\.)?(form\.)?/, '')
    .replace(/\$record\.?/g, '')
    .split('.')
    .filter(function (s) { return s.length > 0; });
}

function resolveFrom(startEl, expr, wantList) {
  var parts = splitSom(expr);
  if (!parts.length) return wantList ? nodeList([]) : null;

  var current = [startEl];
  // Mutlak ifade: kökten başla (ilk parça kök alt formun adıysa).
  if (parts[0] === ROOT.dataset.name) {
    current = [ROOT];
    parts = parts.slice(1);
  }

  for (var p = 0; p < parts.length; p++) {
    var raw = parts[p];
    var idx = null, name = raw;
    var m = raw.match(/^(.*?)\[(.*?)\]$/);
    if (m) { name = m[1]; idx = m[2]; }

    var next = [], i, j;
    for (i = 0; i < current.length; i++) {
      var found = byName(current[i], name);
      if (!found.length && current[i].dataset.name === name) found = [current[i]];
      if (!found.length) {
        // Yukarı doğru ara: betikler çoğu kez kardeş/ata bağlamı varsayar.
        var up = parentEl(current[i]);
        while (up && !found.length) { found = byName(up, name); up = parentEl(up); }
      }
      for (j = 0; j < found.length; j++) next.push(found[j]);
    }
    if (idx !== null && idx !== '*') {
      var n = parseInt(idx, 10);
      next = isNaN(n) ? next : (next[n] ? [next[n]] : []);
    }
    current = next;
    if (!current.length) break;
  }
  if (wantList) return nodeList(current);
  return current.length ? node(current[0]) : null;
}

// ==================================================================
// Görünürlük ve sayfalama
// ==================================================================
function setPresence(el, v) {
  el.dataset.presence = v;
  if (v === 'hidden' || v === 'inactive') {
    el.style.display = 'none';
    el.style.visibility = '';
  } else if (v === 'invisible') {
    el.style.display = '';
    el.style.visibility = 'hidden';
  } else {
    el.style.display = '';
    el.style.visibility = '';
  }
  schedule();
}

/** Sayfalamayı bir sonraki tura erteler (aynı turdaki çok sayıda değişikliği
 *  tek hesapta toplar).
 *
 *  ``requestAnimationFrame`` **kullanılmaz**: sayfa görünür değilken (pencere
 *  simge durumunda, görünüm yığında arkada, ya da testte gösterilmemiş bir
 *  görünümde) hiç tetiklenmez ve yerleşim eski hâlinde kalırdı.
 */
function schedule() {
  if (relayoutPending) return;
  relayoutPending = true;
  setTimeout(function () {
    relayoutPending = false;
    paginate();
  }, 16);
}

/** Sayfalanabilir en küçük parçalar: akış (tb/table) zincirinin yaprakları. */
function flowItems() {
  var out = [];
  (function walk(el) {
    var layout = el.dataset.layout || 'position';
    var children = kids(el), i;
    for (i = 0; i < children.length; i++) {
      var c = children[i];
      if (c.style.display === 'none') continue;
      var inner = c.dataset.layout || 'position';
      if ((layout === 'tb' || layout === 'table') &&
          (inner === 'tb' || inner === 'table') &&
          (c.dataset.kind === 'subform' || c.dataset.kind === 'subformSet')) {
        walk(c);
      } else if (layout === 'tb' || layout === 'table') {
        out.push(c);
      }
    }
  })(ROOT);
  return out;
}

/** ``el``in akış kabına göre üst kenarı (CSS pikseli).
 *
 * ``getBoundingClientRect`` yakınlaştırma dönüşümünden etkilendiği için
 * yerleşim koordinatı veren ``offsetTop`` zinciri kullanılır.
 */
function topIn(el) {
  var y = 0, e = el;
  while (e && e !== flowEl) { y += e.offsetTop; e = e.offsetParent; }
  return y;
}

function paginate() {
  if (!flowEl) return;
  // Önceki ara boşlukları temizle
  var old = flowEl.querySelectorAll('.xbrk'), i;
  for (i = 0; i < old.length; i++) old[i].parentElement.removeChild(old[i]);

  var step = (PAGE.h + GAP) * PX;       // bir sayfanın kapladığı dikey aralık
  var usable = PAGE.ch * PX;            // sayfa başına içerik yüksekliği
  var items = flowItems();

  for (i = 0; i < items.length; i++) {
    var el = items[i];
    if (el.offsetParent === null) continue;
    var top = topIn(el);
    var h = el.offsetHeight;
    var page = Math.floor(top / step);
    var limit = page * step + usable;
    var forced = el.dataset.break === '1' && i > 0;

    if (forced || (h > 0 && top + h > limit && top > page * step + 1)) {
      var pad = (page + 1) * step - top;
      if (pad > 0.5) {
        var spacer = document.createElement('div');
        spacer.className = 'xbrk';
        spacer.style.height = pad.toFixed(2) + 'px';
        el.parentElement.insertBefore(spacer, el);
      }
    }
  }

  var total = flowEl.offsetHeight;
  var count = Math.max(1, Math.ceil((total + GAP * PX) / step));
  buildPages(count);
}

function buildPages(count) {
  var existing = bgEl.querySelectorAll('.page');
  var i;
  for (i = existing.length; i < count; i++) {
    var page = document.createElement('div');
    page.className = 'page';
    page.style.position = 'absolute';
    page.style.left = '0';
    page.style.top = (i * (PAGE.h + GAP)).toFixed(2) + 'pt';
    page.style.margin = '0';
    if (furnitureTpl) {
      var bg = document.createElement('div');
      bg.className = 'pagebg';
      bg.appendChild(furnitureTpl.content.cloneNode(true));
      page.appendChild(bg);
    }
    bgEl.appendChild(page);
  }
  for (i = existing.length - 1; i >= count; i--) {
    existing[i].parentElement.removeChild(existing[i]);
  }
  // Konumlar **her seferinde** yazılır: yazdırma kipinde sayfa aralığı
  // sıfırlanıyor ve yalnızca yeni sayfalar konumlandırılsaydı eski çerçeveler
  // ekran aralığında kalıp sayfa başına 14 punto kayardı.
  var pages = bgEl.querySelectorAll('.page');
  for (i = 0; i < pages.length; i++) {
    pages[i].style.top = (i * (PAGE.h + GAP)).toFixed(2) + 'pt';
  }
  var height = (count * (PAGE.h + GAP) - GAP);
  pagesEl.style.height = height.toFixed(2) + 'pt';
  stampCounters(count);
  if (window.__xfaOnPages) window.__xfaOnPages(count);
}

function stampCounters(count) {
  var pages = bgEl.querySelectorAll('.page'), i, j;
  for (i = 0; i < pages.length; i++) {
    var fields = pages[i].querySelectorAll('[data-name]');
    for (j = 0; j < fields.length; j++) {
      var name = fields[j].dataset.name;
      if (name !== 'CurrentPage' && name !== 'PageCount') continue;
      var c = fields[j].querySelector('.xc');
      if (c) c.value = String(name === 'CurrentPage' ? i + 1 : count);
    }
    // Altbilgideki "Page x of y" metni gömülü alanlara atıfta bulunur.
    var marks = pages[i].querySelectorAll('[data-embed]');
    for (j = 0; j < marks.length; j++) {
      marks[j].textContent = String(
        marks[j].dataset.embed === 'CurrentPage' ? i + 1 : count);
    }
  }
}

function pageOf(el) {
  if (!el || !flowEl) return 1;
  return Math.floor(topIn(el) / ((PAGE.h + GAP) * PX)) + 1;
}

// ==================================================================
// Betik çalıştırma
// ==================================================================
var appObj = {
  alert: function (msg) {
    var text = String(msg);
    if (host() && host().alert) host().alert(text);
    else toast(text);
    return 1;
  },
  response: function (q, t, def) { return def || ''; },
  beep: function () {},
  launchURL: function (u) { if (host() && host().openUrl) host().openUrl(String(u)); },
  mailMsg: function () {},
  execMenuItem: function () {},
  setTimeOut: function (code, ms) { return setTimeout(function () {}, ms); },
  clearTimeOut: function (t) { clearTimeout(t); },
  viewerVersion: 11
};

var xfaObj = {
  get form() { return node(ROOT); },
  get datasets() { return {data: node(ROOT)}; },
  host: {
    name: 'AGY PDF Editor',
    version: '1.0',
    appType: 'Exchange-Pro',
    messageBox: function (msg) { return appObj.alert(msg); },
    response: function (q, t, d) { return d || ''; },
    resetData: function () { resetAll(); },
    setFocus: function (n) {
      var el = (n && n.__el) ? n.__el : null;
      var c = el && control(el);
      if (c) c.focus();
    },
    gotoURL: function (u) { appObj.launchURL(u); },
    pageUp: function () {}, pageDown: function () {},
    exportData: function () {}, importData: function () {},
    print: function () { if (host() && host().printDoc) host().printDoc(); },
    openList: function () {},
    beep: function () {},
    get currentPage() { return 0; },
    set currentPage(v) {},
    get numPages() { return bgEl.querySelectorAll('.page').length; }
  },
  layout: {
    page: function (n) { return pageOf(n && n.__el ? n.__el : null); },
    pageCount: function () { return bgEl.querySelectorAll('.page').length; },
    absPage: function (n) { return pageOf(n && n.__el ? n.__el : null); },
    relayout: function () { paginate(); },
    ready: true
  },
  event: {name: 'unknown', change: '', newText: '', prevText: ''},
  resolveNode: function (expr) {
    return resolveFrom(currentEl || ROOT, expr, false);
  },
  resolveNodes: function (expr) {
    return resolveFrom(currentEl || ROOT, expr, true);
  },
  get record() { return node(ROOT); }
};

// Dosya eki nesneleri — betikler bunlarla ek boyutunu ölçer ve dosya adını
// forma yazar. Tarayıcıda dosya seçimi eşzamanlı olamadığından ilk çağrı
// seçiciyi açıp betiği keser; dosya gelince aynı olay yeniden gönderilir.
function docShim(el) {
  return {
    removeDataObject: function (name) { delete OBJECTS[name]; },
    importDataObject: function (name) {
      if (OBJECTS[name]) return true;
      if (PICKED[name]) { OBJECTS[name] = PICKED[name]; delete PICKED[name]; return true; }
      requestFile(name, el);
      throw ABORT;
    },
    getDataObject: function (name) { return OBJECTS[name] || null; },
    getDataObjectContents: function (name) {
      return OBJECTS[name] ? OBJECTS[name].b64 : '';
    },
    createDataObject: function () {},
    exportDataObject: function () {},
    saveAs: function () {},
    getField: function () { return null; },
    info: {}
  };
}

var SOAP = {
  streamEncode: function (s) { return s; },
  streamDecode: function (s) { return s; },
  stringFromStream: function (s) { return String(s || ''); }
};

var fileInput = null;
function requestFile(name, el) {
  if (!fileInput) {
    fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.style.display = 'none';
    document.body.appendChild(fileInput);
  }
  fileInput.onchange = function () {
    var f = fileInput.files && fileInput.files[0];
    fileInput.value = '';
    if (!f) return;
    var reader = new FileReader();
    reader.onload = function () {
      var b64 = String(reader.result).split(',')[1] || '';
      PICKED[name] = {path: f.name, name: f.name, b64: b64, size: f.size};
      if (el) fire(el, 'click');            // betiği baştan çalıştır
    };
    reader.readAsDataURL(f);
  };
  fileInput.click();
}

var currentEl = null;

function compile(entry) {
  if (entry.fn) return entry.fn;
  if (entry.lang === 'formcalc') {
    entry.fn = function () {};             // FormCalc desteklenmiyor
    return entry.fn;
  }
  try {
    // Katı kip **kullanılmaz**: şablon betikleri döngü sayaçlarını sıklıkla
    // ``var`` olmadan kullanır (``for(i = 0; ...)``); katı kipte bu hata verir.
    entry.fn = new Function(
      'form', 'xfa', 'app', 'event', 'SOAP', '$', '$host', '$layout', 'console',
      'return (function(){\n' + entry.code + '\n});'
    );
  } catch (err) {
    entry.fn = function () { return function () {}; };
    logError(entry.som + ' derlenemedi: ' + err);
  }
  return entry.fn;
}

function runScript(entry, el, evt) {
  var prev = currentEl;
  currentEl = el;
  try {
    var maker = compile(entry);
    var body = maker(
      node(ROOT), xfaObj, appObj, evt, SOAP,
      node(el), xfaObj.host, xfaObj.layout, consoleShim
    );
    body.call(node(el));
  } catch (err) {
    if (err !== ABORT) logError(entry.som + '/' + entry.activity + ': ' + err);
  } finally {
    currentEl = prev;
  }
}

var consoleShim = {
  println: function (m) { try { console.log(m); } catch (e) {} },
  show: function () {}, clear: function () {}
};

function logError(msg) {
  try { console.warn('[XFA] ' + msg); } catch (e) {}
}

function fire(el, activity) {
  if (!el) return;
  var som = el.dataset.som;
  var bucket = SCRIPTS[som];
  if (!bucket || !bucket[activity]) return;
  var evt = {
    name: activity,
    target: docShim(el),
    change: '', newText: getValue(el), prevText: '',
    value: getValue(el), shift: false, modifier: false,
    get rc() { return true; }, set rc(v) {}
  };
  xfaObj.event = evt;
  var list = bucket[activity], i;
  for (i = 0; i < list.length; i++) runScript(list[i], el, evt);
}

/** Alandan yukarı doğru ilk eşleşen olayı gönderir (exclGroup click gibi). */
function fireUp(el, activity) {
  var cur = el;
  while (cur) {
    var bucket = SCRIPTS[cur.dataset.som];
    if (bucket && bucket[activity]) { fire(cur, activity); return; }
    cur = parentEl(cur);
  }
}

function resetAll() {
  var ctls = flowEl.querySelectorAll('.xc, input.xchk'), i;
  for (i = 0; i < ctls.length; i++) {
    if (ctls[i].type === 'checkbox') ctls[i].checked = false;
    else ctls[i].value = '';
  }
  schedule();
}

// ==================================================================
// Olay bağlantıları
// ==================================================================
function nodeOfTarget(t) {
  var el = t;
  while (el && !isNode(el)) el = el.parentElement;
  return el;
}

function bindEvents() {
  flowEl.addEventListener('click', function (e) {
    var el = nodeOfTarget(e.target);
    if (!el) return;
    if (el.dataset.type !== 'check' && el.dataset.type !== 'button') return;

    var grp = parentEl(el);
    if (grp && grp.dataset.kind === 'exclGroup' && e.target.type === 'checkbox') {
      // exclGroup birbirini dışlayan seçimdir: kutular HTML'de bağımsız
      // olduğu için karşılıklı dışlamayı burada uygularız.
      var m = groupMembers(grp), i, c;
      for (i = 0; i < m.length; i++) {
        c = control(m[i]);
        if (c && c !== e.target) c.checked = false;
      }
    }
    fire(el, 'click');
    if (grp && grp.dataset.kind === 'exclGroup') fire(grp, 'click');
    if (window.__xfaDirty) window.__xfaDirty();
  });

  flowEl.addEventListener('change', function (e) {
    var el = nodeOfTarget(e.target);
    if (!el) return;
    fire(el, 'change');
    if (e.target.tagName === 'SELECT' || e.target.type === 'checkbox') {
      fire(el, 'exit');
      var grp = parentEl(el);
      if (grp && grp.dataset.kind === 'exclGroup') fire(grp, 'exit');
    }
    if (window.__xfaDirty) window.__xfaDirty();
  });

  flowEl.addEventListener('input', function () {
    if (window.__xfaDirty) window.__xfaDirty();
  });

  flowEl.addEventListener('focusin', function (e) {
    var el = nodeOfTarget(e.target);
    if (!el) return;
    fire(el, 'enter');
    if (e.target.tagName === 'SELECT') fire(el, 'preOpen');
  });

  flowEl.addEventListener('focusout', function (e) {
    var el = nodeOfTarget(e.target);
    if (!el) return;
    if (e.target.tagName !== 'SELECT' && e.target.type !== 'checkbox') {
      fire(el, 'exit');
    }
  });

  flowEl.addEventListener('mousedown', function (e) {
    if (e.target.tagName === 'SELECT') {
      var el = nodeOfTarget(e.target);
      if (el) fire(el, 'preOpen');
    }
  }, true);
}

// ==================================================================
// Kurulum
// ==================================================================
function indexScripts() {
  var list = CFG.scripts || [], i;
  for (i = 0; i < list.length; i++) {
    var s = list[i];
    if (!s.som || s.som.indexOf('page') === 0) continue;   // sayfa sayaçları
    if (!SCRIPTS[s.som]) SCRIPTS[s.som] = {};
    var act = s.activity;
    if (!SCRIPTS[s.som][act]) SCRIPTS[s.som][act] = [];
    SCRIPTS[s.som][act].push(s);
  }
}

/** ``<variables>`` betiklerini ad alanı nesnesine çevirir. */
function loadVariables() {
  var list = CFG.variables || [], i;
  for (i = 0; i < list.length; i++) {
    var v = list[i];
    var names = [];
    var re = /function\s+([A-Za-z_$][\w$]*)\s*\(/g, m;
    while ((m = re.exec(v.code)) !== null) names.push(m[1]);
    var ret = names.map(function (n) { return n + ':' + n; }).join(',');
    try {
      var factory = new Function(
        'form', 'xfa', 'app', 'console', 'SOAP',
        v.code + '\nreturn {' + ret + '};'
      );
      NS[v.name] = factory(node(ROOT), xfaObj, appObj, consoleShim, SOAP);
      window[v.name] = NS[v.name];
      // Kütüphane işlevleri çıplak adla da çağrılabilir olmalı.
      for (var k = 0; k < names.length; k++) {
        if (!(names[k] in window)) window[names[k]] = NS[v.name][names[k]];
      }
    } catch (err) {
      logError('variables/' + v.name + ': ' + err);
      NS[v.name] = {};
      window[v.name] = NS[v.name];
    }
  }
}

function markPristine() {
  var reps = flowEl.querySelectorAll('[data-repeat="1"]'), i;
  for (i = 0; i < reps.length; i++) {
    var som = reps[i].dataset.som;
    if (!PRISTINE[som]) PRISTINE[som] = reps[i].outerHTML;
  }
}

function applyInitialAccess() {
  var locked = flowEl.querySelectorAll('[data-readonly="1"]'), i, j;
  for (i = 0; i < locked.length; i++) {
    var ctls = locked[i].querySelectorAll('.xc, input.xchk');
    for (j = 0; j < ctls.length; j++) ctls[j].disabled = true;
  }
}

function runReady() {
  // ``ready`` olayları (form/layout) ve alan başlangıç betikleri
  var som, bucket;
  for (som in SCRIPTS) {
    bucket = SCRIPTS[som];
    if (!bucket.ready && !bucket.initialize) continue;
    var el = flowEl.querySelector('[data-som="' + cssEscape(som) + '"]');
    if (!el) continue;
    if (bucket.initialize) fire(el, 'initialize');
    if (bucket.ready) fire(el, 'ready');
  }
}

function cssEscape(s) { return String(s).replace(/"/g, '\\"'); }

/** Kayıtlı ``datasets`` değerlerini forma geri yazar.
 *
 * Yollar ``Users.row[1].fname`` biçiminde dizinli olabilir; eksik satırlar
 * örnek yöneticisiyle oluşturulur, yoksa ikinci satırdaki veri kaybolurdu.
 */
function applyValues() {
  var values = CFG.values || {}, path;
  var touched = [];
  for (path in values) {
    var el = locate(path, true);
    if (!el) continue;
    setValue(el, values[path], true);
    touched.push(el);
  }
  // Kayıtlı bir seçim, ona bağlı bölümleri de açmalı: seçim betikleri yalnızca
  // tıklamada çalıştığı için dolu bir form yeniden açıldığında bölümler kapalı
  // kalırdı. Dosya eki düğmeleri tetiklenmez (dosya seçici açardı).
  for (var i = 0; i < touched.length; i++) {
    var el2 = touched[i];
    var grp = parentEl(el2);
    if (grp && grp.dataset.kind === 'exclGroup') el2 = grp;
    if (el2.dataset.kind === 'exclGroup' || el2.dataset.type === 'check') {
      fire(el2, 'click');
    }
  }
}

function locate(path, create) {
  var parts = splitSom(path);
  if (parts.length && parts[0] === ROOT.dataset.name) parts = parts.slice(1);
  var cur = ROOT;
  for (var i = 0; i < parts.length; i++) {
    var name = parts[i], idx = 0;
    var m = name.match(/^(.*?)\[(\d+)\]$/);
    if (m) { name = m[1]; idx = parseInt(m[2], 10); }
    var found = byName(cur, name);
    if (!found.length) return null;
    if (idx >= found.length) {
      if (!create || !found[0].dataset.repeat) return null;
      var mgr = manager(found[0]);
      try {
        while (siblings(found[0]).length <= idx) mgr.addInstance();
      } catch (err) { return null; }
      found = byName(cur, name);
      if (idx >= found.length) return null;
    }
    cur = found[idx];
  }
  return cur;
}

function boot() {
  pagesEl = document.getElementById('pages');
  toastEl = document.getElementById('toast');
  furnitureTpl = document.getElementById('furniture');
  var source = document.getElementById('source');
  ROOT = source.firstElementChild;

  // Sayfa çerçeveleri akışın **arkasında** durur.
  bgEl = document.createElement('div');
  bgEl.id = 'pagebg';
  pagesEl.appendChild(bgEl);

  // Akış kabı: bütün içerik tek bir sütunda akar; sayfa çerçeveleri arkada
  // durur ve sayfa kırılmaları ara boşluklarla verilir. Böylece DOM ağacı
  // XFA ağacıyla birebir kalır ve bir bölüm gizlendiğinde tarayıcı geri
  // kalanı kendiliğinden yukarı çeker.
  flowEl = document.createElement('div');
  flowEl.id = 'flow';
  flowEl.style.position = 'absolute';
  flowEl.style.left = PAGE.cx + 'pt';
  flowEl.style.top = PAGE.cy + 'pt';
  flowEl.style.width = PAGE.cw + 'pt';
  flowEl.appendChild(ROOT);
  source.parentElement.removeChild(source);
  pagesEl.appendChild(flowEl);

  indexScripts();
  markPristine();
  applyInitialAccess();
  loadVariables();
  bindEvents();
  buildPages(1);
  applyValues();
  runReady();
  paginate();
  ready = true;
  if (window.__xfaReady) window.__xfaReady();
}

// ==================================================================
// Dış arayüz (Qt tarafı bunları çağırır)
// ==================================================================
window.XFA = {
  /** Doldurulmuş değerler: {SOM yolu: değer} */
  values: function () {
    var out = {};
    var nodes = flowEl.querySelectorAll(
      '[data-kind="field"],[data-kind="exclGroup"]'), i;
    for (i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var t = el.dataset.type;
      if (t === 'button' || t === 'barcode' || t === 'signature') continue;
      // exclGroup üyeleri grubun kendi yolunda tek değer olarak yazılır;
      // XFA veri ağacında da öyle durur.
      var p = parentEl(el);
      if (el.dataset.kind === 'field' && p && p.dataset.kind === 'exclGroup') {
        continue;
      }
      var v = getValue(el);
      if (v === '' || v === null) continue;
      out[somWithIndex(el)] = v;
    }
    return out;
  },
  /** Kaydetmeden önce ``preSave`` betiklerini çalıştırır. */
  preSave: function () {
    var som;
    for (som in SCRIPTS) {
      if (!SCRIPTS[som].preSave) continue;
      var el = flowEl.querySelector('[data-som="' + cssEscape(som) + '"]');
      if (el) fire(el, 'preSave');
    }
    return true;
  },
  setZoom: function (z) {
    var stage = document.getElementById('stage');
    stage.style.transform = 'scale(' + z + ')';
    stage.style.height = (pagesEl.getBoundingClientRect().height * z) + 'px';
  },
  pageCount: function () { return bgEl.querySelectorAll('.page').length; },
  gotoPage: function (n) {
    var pages = bgEl.querySelectorAll('.page');
    if (pages[n - 1]) pages[n - 1].scrollIntoView({block: 'start'});
  },
  highlight: function (on) { document.body.classList.toggle('nohl', !on); },
  /** Yazdırma kipine geçer; toplam sayfa sayısını döndürür.
   *
   * Sayfa bölmesi Chromium'a bırakılmaz: kendi sayfalamamızla onun sayfa
   * kutuları birkaç puntoluk farkla kaydığı için altbilgiler bir sonraki
   * sayfanın tepesinde beliriyordu. Bunun yerine belge **tek sayfa
   * yüksekliğine** kırpılır ve her sayfa ayrı basılır (bkz. showPrintPage).
   */
  prepareForPrint: function () {
    if (document.activeElement && document.activeElement.blur) {
      document.activeElement.blur();
    }
    document.body.classList.add('printing');
    GAP = 0;
    paginate();
    var doc = document.getElementById('doc');
    doc.style.height = PAGE.h + 'pt';
    doc.style.overflow = 'hidden';
    doc.style.padding = '0';
    return bgEl.querySelectorAll('.page').length;
  },
  /** Yazdırma kipinde ``index``inci sayfayı görünür pencereye kaydırır. */
  showPrintPage: function (index) {
    var stage = document.getElementById('stage');
    stage.style.transform = 'translateY(' + (-index * PAGE.h) + 'pt)';
    return index;
  },
  /** Yazdırma sonrası ekran yerleşimine dön. */
  endPrint: function () {
    document.body.classList.remove('printing');
    var doc = document.getElementById('doc');
    doc.style.height = '';
    doc.style.overflow = '';
    doc.style.padding = '';
    document.getElementById('stage').style.transform = '';
    GAP = SCREEN_GAP;
    paginate();
    return true;
  },
  fieldCount: function () {
    return flowEl.querySelectorAll('[data-kind="field"]').length;
  },
  visibleFieldCount: function () {
    var n = flowEl.querySelectorAll('[data-kind="field"]'), c = 0, i;
    for (i = 0; i < n.length; i++) {
      if (n[i].offsetParent !== null) c++;
    }
    return c;
  },
  isReady: function () { return ready; }
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
})();
"""
