/* Minimal runtime for the page templates: {{ holes }}, <sc-if>, <sc-for>, event bindings.
   Renders a <template> into a root element and patches the DOM with morphdom on every state change. */
(function () {
  'use strict';

  function DCLogic(props) { this.props = props || {}; this.state = {}; }
  DCLogic.prototype.setState = function (patch) {
    var next = typeof patch === 'function' ? patch(this.state, this.props) : patch;
    this.state = Object.assign({}, this.state, next || {});
    if (this.__schedule) this.__schedule();
  };
  DCLogic.prototype.forceUpdate = function () { if (this.__schedule) this.__schedule(); };
  window.DCLogic = DCLogic;

  var HOLE = /\{\{\s*([^}]+?)\s*\}\}/g;
  var WHOLE = /^\s*\{\{\s*([^}]+?)\s*\}\}\s*$/;
  var EVENTS = { onclick: 'click', onchange: 'change', onpointerdown: 'pointerdown', onpointermove: 'pointermove', onpointerup: 'pointerup', onpointercancel: 'pointercancel' };

  function resolve(path, scopes) {
    if (path === 'true') return true;
    if (path === 'false') return false;
    if (/^-?\d+(\.\d+)?$/.test(path)) return Number(path);
    var parts = path.split('.');
    var head = parts[0], obj;
    for (var i = scopes.length - 1; i >= 0; i--) {
      if (scopes[i] && Object.prototype.hasOwnProperty.call(scopes[i], head)) { obj = scopes[i][head]; break; }
    }
    for (var k = 1; k < parts.length && obj != null; k++) obj = obj[parts[k]];
    return obj;
  }
  function interp(str, scopes) {
    return str.replace(HOLE, function (_, p) { var v = resolve(p, scopes); return v == null ? '' : String(v); });
  }

  function build(srcParent, dstParent, scopes, handlers) {
    var kids = srcParent.childNodes;
    for (var i = 0; i < kids.length; i++) {
      var n = kids[i];
      if (n.nodeType === 3) { dstParent.appendChild(document.createTextNode(interp(n.nodeValue, scopes))); continue; }
      if (n.nodeType !== 1) continue;
      var tag = n.tagName.toLowerCase();
      if (tag === 'sc-if') {
        var m = WHOLE.exec(n.getAttribute('value') || '');
        if (m && resolve(m[1], scopes)) build(n, dstParent, scopes, handlers);
        continue;
      }
      if (tag === 'sc-for') {
        var lm = WHOLE.exec(n.getAttribute('list') || '');
        var list = lm ? resolve(lm[1], scopes) : null;
        var as = n.getAttribute('as') || 'item';
        if (list && list.length) {
          for (var j = 0; j < list.length; j++) {
            var sc = {}; sc[as] = list[j]; sc.$index = j;
            build(n, dstParent, scopes.concat([sc]), handlers);
          }
        }
        continue;
      }
      var el = n.cloneNode(false);
      var deferredValue = null, isSelect = tag === 'select';
      var attrs = Array.prototype.slice.call(n.attributes);
      for (var a = 0; a < attrs.length; a++) {
        var name = attrs[a].name, val = attrs[a].value;
        if (name.indexOf('hint-') === 0) { el.removeAttribute(name); continue; }
        var whole = WHOLE.exec(val);
        if (EVENTS[name]) {
          el.removeAttribute(name);
          var fn = whole ? resolve(whole[1], scopes) : null;
          if (typeof fn === 'function') el.setAttribute('data-ev-' + EVENTS[name], String(handlers.push(fn) - 1));
          continue;
        }
        if (name === 'checked') {
          var c = whole ? resolve(whole[1], scopes) : val;
          if (c && c !== 'false') { el.setAttribute('checked', ''); el.checked = true; } else { el.removeAttribute('checked'); el.checked = false; }
          continue;
        }
        if (val.indexOf('{{') === -1) continue;
        var out = whole ? resolve(whole[1], scopes) : interp(val, scopes);
        out = out == null ? '' : String(out);
        if (name === 'value') { deferredValue = out; }
        el.setAttribute(name, out);
      }
      if (tag !== 'textarea') build(n, el, scopes, handlers);
      if (deferredValue !== null) {
        if (tag === 'textarea') { el.textContent = deferredValue; el.value = deferredValue; }
        else if (isSelect) {
          el.removeAttribute('value');
          Array.prototype.forEach.call(el.querySelectorAll('option'), function (o) {
            if (o.getAttribute('value') === deferredValue) o.setAttribute('selected', ''); else o.removeAttribute('selected');
          });
        } else { el.value = deferredValue; }
      }
      dstParent.appendChild(el);
    }
  }

  function mount(tpl, Component, root, props) {
    var comp = new Component(props || {});
    var handlers = [];
    var queued = false;
    function render() {
      queued = false;
      var vals = comp.renderVals();
      var next = [];
      var shadow = root.cloneNode(false);
      build(tpl.content, shadow, [vals], next);
      handlers = next;
      window.morphdom(root, shadow, {
        childrenOnly: true,
        onBeforeElUpdated: function (fromEl, toEl) {
          if (fromEl.tagName === 'CANVAS') {
            ['click', 'pointerdown', 'pointermove', 'pointerup', 'pointercancel'].forEach(function (t) {
              var v = toEl.getAttribute('data-ev-' + t);
              if (v === null) fromEl.removeAttribute('data-ev-' + t); else fromEl.setAttribute('data-ev-' + t, v);
            });
            return false;
          }
          if (fromEl.tagName === 'DETAILS') { if (fromEl.open) toEl.setAttribute('open', ''); }
          if (fromEl === document.activeElement && (fromEl.tagName === 'INPUT' || fromEl.tagName === 'TEXTAREA') && fromEl.type !== 'checkbox') {
            if (fromEl.value === toEl.value) {
              Array.prototype.forEach.call(toEl.attributes, function (at) { if (at.name !== 'value') fromEl.setAttribute(at.name, at.value); });
              return false;
            }
          }
          return true;
        }
      });
    }
    comp.__schedule = function () {
      if (queued) return;
      queued = true;
      (window.requestAnimationFrame || setTimeout)(render);
    };
    function wrap(e, el) {
      return {
        target: e.target, currentTarget: el, type: e.type,
        clientX: e.clientX, clientY: e.clientY, pointerId: e.pointerId, nativeEvent: e,
        preventDefault: function () { e.preventDefault(); },
        stopPropagation: function () { e.stopPropagation(); }
      };
    }
    function dispatch(type, attrType) {
      root.addEventListener(type, function (e) {
        var el = e.target && e.target.closest ? e.target.closest('[data-ev-' + attrType + ']') : null;
        if (!el || !root.contains(el)) return;
        var fn = handlers[Number(el.getAttribute('data-ev-' + attrType))];
        if (fn) fn(wrap(e, el));
      }, type.indexOf('pointer') === 0 ? { passive: false } : false);
    }
    dispatch('click', 'click');
    dispatch('input', 'change');
    dispatch('change', 'change');
    ['pointerdown', 'pointermove', 'pointerup', 'pointercancel'].forEach(function (t) { dispatch(t, t); });
    render();
    if (typeof comp.componentDidMount === 'function') comp.componentDidMount();
    return comp;
  }

  window.DC = { mount: mount };
})();
