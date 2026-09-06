//#region node_modules/@lit/reactive-element/css-tag.js
var e = globalThis, t = e.ShadowRoot && (e.ShadyCSS === void 0 || e.ShadyCSS.nativeShadow) && "adoptedStyleSheets" in Document.prototype && "replace" in CSSStyleSheet.prototype, n = Symbol(), r = /* @__PURE__ */ new WeakMap(), i = class {
	constructor(e, t, r) {
		if (this._$cssResult$ = !0, r !== n) throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");
		this.cssText = e, this.t = t;
	}
	get styleSheet() {
		let e = this.o, n = this.t;
		if (t && e === void 0) {
			let t = n !== void 0 && n.length === 1;
			t && (e = r.get(n)), e === void 0 && ((this.o = e = new CSSStyleSheet()).replaceSync(this.cssText), t && r.set(n, e));
		}
		return e;
	}
	toString() {
		return this.cssText;
	}
}, a = (e) => new i(typeof e == "string" ? e : e + "", void 0, n), o = (e, ...t) => new i(e.length === 1 ? e[0] : t.reduce((t, n, r) => t + ((e) => {
	if (!0 === e._$cssResult$) return e.cssText;
	if (typeof e == "number") return e;
	throw Error("Value passed to 'css' function must be a 'css' function result: " + e + ". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.");
})(n) + e[r + 1], e[0]), e, n), s = (n, r) => {
	if (t) n.adoptedStyleSheets = r.map((e) => e instanceof CSSStyleSheet ? e : e.styleSheet);
	else for (let t of r) {
		let r = document.createElement("style"), i = e.litNonce;
		i !== void 0 && r.setAttribute("nonce", i), r.textContent = t.cssText, n.appendChild(r);
	}
}, c = t ? (e) => e : (e) => e instanceof CSSStyleSheet ? ((e) => {
	let t = "";
	for (let n of e.cssRules) t += n.cssText;
	return a(t);
})(e) : e, { is: l, defineProperty: u, getOwnPropertyDescriptor: ee, getOwnPropertyNames: te, getOwnPropertySymbols: ne, getPrototypeOf: re } = Object, ie = globalThis, ae = ie.trustedTypes, oe = ae ? ae.emptyScript : "", se = ie.reactiveElementPolyfillSupport, d = (e, t) => e, f = {
	toAttribute(e, t) {
		switch (t) {
			case Boolean:
				e = e ? oe : null;
				break;
			case Object:
			case Array: e = e == null ? e : JSON.stringify(e);
		}
		return e;
	},
	fromAttribute(e, t) {
		let n = e;
		switch (t) {
			case Boolean:
				n = e !== null;
				break;
			case Number:
				n = e === null ? null : Number(e);
				break;
			case Object:
			case Array: try {
				n = JSON.parse(e);
			} catch {
				n = null;
			}
		}
		return n;
	}
}, ce = (e, t) => !l(e, t), le = {
	attribute: !0,
	type: String,
	converter: f,
	reflect: !1,
	useDefault: !1,
	hasChanged: ce
};
Symbol.metadata ??= Symbol("metadata"), ie.litPropertyMetadata ??= /* @__PURE__ */ new WeakMap();
var p = class extends HTMLElement {
	static addInitializer(e) {
		this._$Ei(), (this.l ??= []).push(e);
	}
	static get observedAttributes() {
		return this.finalize(), this._$Eh && [...this._$Eh.keys()];
	}
	static createProperty(e, t = le) {
		if (t.state && (t.attribute = !1), this._$Ei(), this.prototype.hasOwnProperty(e) && ((t = Object.create(t)).wrapped = !0), this.elementProperties.set(e, t), !t.noAccessor) {
			let n = Symbol(), r = this.getPropertyDescriptor(e, n, t);
			r !== void 0 && u(this.prototype, e, r);
		}
	}
	static getPropertyDescriptor(e, t, n) {
		let { get: r, set: i } = ee(this.prototype, e) ?? {
			get() {
				return this[t];
			},
			set(e) {
				this[t] = e;
			}
		};
		return {
			get: r,
			set(t) {
				let a = r?.call(this);
				i?.call(this, t), this.requestUpdate(e, a, n);
			},
			configurable: !0,
			enumerable: !0
		};
	}
	static getPropertyOptions(e) {
		return this.elementProperties.get(e) ?? le;
	}
	static _$Ei() {
		if (this.hasOwnProperty(d("elementProperties"))) return;
		let e = re(this);
		e.finalize(), e.l !== void 0 && (this.l = [...e.l]), this.elementProperties = new Map(e.elementProperties);
	}
	static finalize() {
		if (this.hasOwnProperty(d("finalized"))) return;
		if (this.finalized = !0, this._$Ei(), this.hasOwnProperty(d("properties"))) {
			let e = this.properties, t = [...te(e), ...ne(e)];
			for (let n of t) this.createProperty(n, e[n]);
		}
		let e = this[Symbol.metadata];
		if (e !== null) {
			let t = litPropertyMetadata.get(e);
			if (t !== void 0) for (let [e, n] of t) this.elementProperties.set(e, n);
		}
		this._$Eh = /* @__PURE__ */ new Map();
		for (let [e, t] of this.elementProperties) {
			let n = this._$Eu(e, t);
			n !== void 0 && this._$Eh.set(n, e);
		}
		this.elementStyles = this.finalizeStyles(this.styles);
	}
	static finalizeStyles(e) {
		let t = [];
		if (Array.isArray(e)) {
			let n = new Set(e.flat(1 / 0).reverse());
			for (let e of n) t.unshift(c(e));
		} else e !== void 0 && t.push(c(e));
		return t;
	}
	static _$Eu(e, t) {
		let n = t.attribute;
		return !1 === n ? void 0 : typeof n == "string" ? n : typeof e == "string" ? e.toLowerCase() : void 0;
	}
	constructor() {
		super(), this._$Ep = void 0, this.isUpdatePending = !1, this.hasUpdated = !1, this._$Em = null, this._$Ev();
	}
	_$Ev() {
		this._$ES = new Promise((e) => this.enableUpdating = e), this._$AL = /* @__PURE__ */ new Map(), this._$E_(), this.requestUpdate(), this.constructor.l?.forEach((e) => e(this));
	}
	addController(e) {
		(this._$EO ??= /* @__PURE__ */ new Set()).add(e), this.renderRoot !== void 0 && this.isConnected && e.hostConnected?.();
	}
	removeController(e) {
		this._$EO?.delete(e);
	}
	_$E_() {
		let e = /* @__PURE__ */ new Map(), t = this.constructor.elementProperties;
		for (let n of t.keys()) this.hasOwnProperty(n) && (e.set(n, this[n]), delete this[n]);
		e.size > 0 && (this._$Ep = e);
	}
	createRenderRoot() {
		let e = this.shadowRoot ?? this.attachShadow(this.constructor.shadowRootOptions);
		return s(e, this.constructor.elementStyles), e;
	}
	connectedCallback() {
		this.renderRoot ??= this.createRenderRoot(), this.enableUpdating(!0), this._$EO?.forEach((e) => e.hostConnected?.());
	}
	enableUpdating(e) {}
	disconnectedCallback() {
		this._$EO?.forEach((e) => e.hostDisconnected?.());
	}
	attributeChangedCallback(e, t, n) {
		this._$AK(e, n);
	}
	_$ET(e, t) {
		let n = this.constructor.elementProperties.get(e), r = this.constructor._$Eu(e, n);
		if (r !== void 0 && !0 === n.reflect) {
			let i = (n.converter?.toAttribute === void 0 ? f : n.converter).toAttribute(t, n.type);
			this._$Em = e, i == null ? this.removeAttribute(r) : this.setAttribute(r, i), this._$Em = null;
		}
	}
	_$AK(e, t) {
		let n = this.constructor, r = n._$Eh.get(e);
		if (r !== void 0 && this._$Em !== r) {
			let e = n.getPropertyOptions(r), i = typeof e.converter == "function" ? { fromAttribute: e.converter } : e.converter?.fromAttribute === void 0 ? f : e.converter;
			this._$Em = r;
			let a = i.fromAttribute(t, e.type);
			this[r] = a ?? this._$Ej?.get(r) ?? a, this._$Em = null;
		}
	}
	requestUpdate(e, t, n, r = !1, i) {
		if (e !== void 0) {
			let a = this.constructor;
			if (!1 === r && (i = this[e]), n ??= a.getPropertyOptions(e), !((n.hasChanged ?? ce)(i, t) || n.useDefault && n.reflect && i === this._$Ej?.get(e) && !this.hasAttribute(a._$Eu(e, n)))) return;
			this.C(e, t, n);
		}
		!1 === this.isUpdatePending && (this._$ES = this._$EP());
	}
	C(e, t, { useDefault: n, reflect: r, wrapped: i }, a) {
		n && !(this._$Ej ??= /* @__PURE__ */ new Map()).has(e) && (this._$Ej.set(e, a ?? t ?? this[e]), !0 !== i || a !== void 0) || (this._$AL.has(e) || (this.hasUpdated || n || (t = void 0), this._$AL.set(e, t)), !0 === r && this._$Em !== e && (this._$Eq ??= /* @__PURE__ */ new Set()).add(e));
	}
	async _$EP() {
		this.isUpdatePending = !0;
		try {
			await this._$ES;
		} catch (e) {
			Promise.reject(e);
		}
		let e = this.scheduleUpdate();
		return e != null && await e, !this.isUpdatePending;
	}
	scheduleUpdate() {
		return this.performUpdate();
	}
	performUpdate() {
		if (!this.isUpdatePending) return;
		if (!this.hasUpdated) {
			if (this.renderRoot ??= this.createRenderRoot(), this._$Ep) {
				for (let [e, t] of this._$Ep) this[e] = t;
				this._$Ep = void 0;
			}
			let e = this.constructor.elementProperties;
			if (e.size > 0) for (let [t, n] of e) {
				let { wrapped: e } = n, r = this[t];
				!0 !== e || this._$AL.has(t) || r === void 0 || this.C(t, void 0, n, r);
			}
		}
		let e = !1, t = this._$AL;
		try {
			e = this.shouldUpdate(t), e ? (this.willUpdate(t), this._$EO?.forEach((e) => e.hostUpdate?.()), this.update(t)) : this._$EM();
		} catch (t) {
			throw e = !1, this._$EM(), t;
		}
		e && this._$AE(t);
	}
	willUpdate(e) {}
	_$AE(e) {
		this._$EO?.forEach((e) => e.hostUpdated?.()), this.hasUpdated || (this.hasUpdated = !0, this.firstUpdated(e)), this.updated(e);
	}
	_$EM() {
		this._$AL = /* @__PURE__ */ new Map(), this.isUpdatePending = !1;
	}
	get updateComplete() {
		return this.getUpdateComplete();
	}
	getUpdateComplete() {
		return this._$ES;
	}
	shouldUpdate(e) {
		return !0;
	}
	update(e) {
		this._$Eq &&= this._$Eq.forEach((e) => this._$ET(e, this[e])), this._$EM();
	}
	updated(e) {}
	firstUpdated(e) {}
};
p.elementStyles = [], p.shadowRootOptions = { mode: "open" }, p[d("elementProperties")] = /* @__PURE__ */ new Map(), p[d("finalized")] = /* @__PURE__ */ new Map(), se?.({ ReactiveElement: p }), (ie.reactiveElementVersions ??= []).push("2.1.2");
//#endregion
//#region node_modules/lit-html/lit-html.js
var ue = globalThis, de = (e) => e, m = ue.trustedTypes, fe = m ? m.createPolicy("lit-html", { createHTML: (e) => e }) : void 0, pe = "$lit$", h = `lit$${Math.random().toFixed(9).slice(2)}$`, me = "?" + h, he = `<${me}>`, g = document, _ = () => g.createComment(""), v = (e) => e === null || typeof e != "object" && typeof e != "function", ge = Array.isArray, _e = (e) => ge(e) || typeof e?.[Symbol.iterator] == "function", ve = "[ 	\n\f\r]", y = /<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g, ye = /-->/g, be = />/g, b = RegExp(`>|${ve}(?:([^\\s"'>=/]+)(${ve}*=${ve}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`, "g"), xe = /'/g, Se = /"/g, Ce = /^(?:script|style|textarea|title)$/i, x = ((e) => (t, ...n) => ({
	_$litType$: e,
	strings: t,
	values: n
}))(1), S = Symbol.for("lit-noChange"), C = Symbol.for("lit-nothing"), we = /* @__PURE__ */ new WeakMap(), w = g.createTreeWalker(g, 129);
function Te(e, t) {
	if (!ge(e) || !e.hasOwnProperty("raw")) throw Error("invalid template strings array");
	return fe === void 0 ? t : fe.createHTML(t);
}
var Ee = (e, t) => {
	let n = e.length - 1, r = [], i, a = t === 2 ? "<svg>" : t === 3 ? "<math>" : "", o = y;
	for (let t = 0; t < n; t++) {
		let n = e[t], s, c, l = -1, u = 0;
		for (; u < n.length && (o.lastIndex = u, c = o.exec(n), c !== null);) u = o.lastIndex, o === y ? c[1] === "!--" ? o = ye : c[1] === void 0 ? c[2] === void 0 ? c[3] !== void 0 && (o = b) : (Ce.test(c[2]) && (i = RegExp("</" + c[2], "g")), o = b) : o = be : o === b ? c[0] === ">" ? (o = i ?? y, l = -1) : c[1] === void 0 ? l = -2 : (l = o.lastIndex - c[2].length, s = c[1], o = c[3] === void 0 ? b : c[3] === "\"" ? Se : xe) : o === Se || o === xe ? o = b : o === ye || o === be ? o = y : (o = b, i = void 0);
		let ee = o === b && e[t + 1].startsWith("/>") ? " " : "";
		a += o === y ? n + he : l >= 0 ? (r.push(s), n.slice(0, l) + pe + n.slice(l) + h + ee) : n + h + (l === -2 ? t : ee);
	}
	return [Te(e, a + (e[n] || "<?>") + (t === 2 ? "</svg>" : t === 3 ? "</math>" : "")), r];
}, De = class e {
	constructor({ strings: t, _$litType$: n }, r) {
		let i;
		this.parts = [];
		let a = 0, o = 0, s = t.length - 1, c = this.parts, [l, u] = Ee(t, n);
		if (this.el = e.createElement(l, r), w.currentNode = this.el.content, n === 2 || n === 3) {
			let e = this.el.content.firstChild;
			e.replaceWith(...e.childNodes);
		}
		for (; (i = w.nextNode()) !== null && c.length < s;) {
			if (i.nodeType === 1) {
				if (i.hasAttributes()) for (let e of i.getAttributeNames()) if (e.endsWith(pe)) {
					let t = u[o++], n = i.getAttribute(e).split(h), r = /([.?@])?(.*)/.exec(t);
					c.push({
						type: 1,
						index: a,
						name: r[2],
						strings: n,
						ctor: r[1] === "." ? Ae : r[1] === "?" ? je : r[1] === "@" ? Me : E
					}), i.removeAttribute(e);
				} else e.startsWith(h) && (c.push({
					type: 6,
					index: a
				}), i.removeAttribute(e));
				if (Ce.test(i.tagName)) {
					let e = i.textContent.split(h), t = e.length - 1;
					if (t > 0) {
						i.textContent = m ? m.emptyScript : "";
						for (let n = 0; n < t; n++) i.append(e[n], _()), w.nextNode(), c.push({
							type: 2,
							index: ++a
						});
						i.append(e[t], _());
					}
				}
			} else if (i.nodeType === 8) {
				if (i.data === me) c.push({
					type: 2,
					index: a
				});
				else {
					let e = -1;
					for (; (e = i.data.indexOf(h, e + 1)) !== -1;) c.push({
						type: 7,
						index: a
					}), e += h.length - 1;
				}
			}
			a++;
		}
	}
	static createElement(e, t) {
		let n = g.createElement("template");
		return n.innerHTML = e, n;
	}
};
function T(e, t, n = e, r) {
	if (t === S) return t;
	let i = r === void 0 ? n._$Cl : n._$Co?.[r], a = v(t) ? void 0 : t._$litDirective$;
	return i?.constructor !== a && (i?._$AO?.(!1), a === void 0 ? i = void 0 : (i = new a(e), i._$AT(e, n, r)), r === void 0 ? n._$Cl = i : (n._$Co ??= [])[r] = i), i !== void 0 && (t = T(e, i._$AS(e, t.values), i, r)), t;
}
var Oe = class {
	constructor(e, t) {
		this._$AV = [], this._$AN = void 0, this._$AD = e, this._$AM = t;
	}
	get parentNode() {
		return this._$AM.parentNode;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	u(e) {
		let { el: { content: t }, parts: n } = this._$AD, r = (e?.creationScope ?? g).importNode(t, !0);
		w.currentNode = r;
		let i = w.nextNode(), a = 0, o = 0, s = n[0];
		for (; s !== void 0;) {
			if (a === s.index) {
				let t;
				s.type === 2 ? t = new ke(i, i.nextSibling, this, e) : s.type === 1 ? t = new s.ctor(i, s.name, s.strings, this, e) : s.type === 6 && (t = new Ne(i, this, e)), this._$AV.push(t), s = n[++o];
			}
			a !== s?.index && (i = w.nextNode(), a++);
		}
		return w.currentNode = g, r;
	}
	p(e) {
		let t = 0;
		for (let n of this._$AV) n !== void 0 && (n.strings === void 0 ? n._$AI(e[t]) : (n._$AI(e, n, t), t += n.strings.length - 2)), t++;
	}
}, ke = class e {
	get _$AU() {
		return this._$AM?._$AU ?? this._$Cv;
	}
	constructor(e, t, n, r) {
		this.type = 2, this._$AH = C, this._$AN = void 0, this._$AA = e, this._$AB = t, this._$AM = n, this.options = r, this._$Cv = r?.isConnected ?? !0;
	}
	get parentNode() {
		let e = this._$AA.parentNode, t = this._$AM;
		return t !== void 0 && e?.nodeType === 11 && (e = t.parentNode), e;
	}
	get startNode() {
		return this._$AA;
	}
	get endNode() {
		return this._$AB;
	}
	_$AI(e, t = this) {
		e = T(this, e, t), v(e) ? e === C || e == null || e === "" ? (this._$AH !== C && this._$AR(), this._$AH = C) : e !== this._$AH && e !== S && this._(e) : e._$litType$ === void 0 ? e.nodeType === void 0 ? _e(e) ? this.k(e) : this._(e) : this.T(e) : this.$(e);
	}
	O(e) {
		return this._$AA.parentNode.insertBefore(e, this._$AB);
	}
	T(e) {
		this._$AH !== e && (this._$AR(), this._$AH = this.O(e));
	}
	_(e) {
		this._$AH !== C && v(this._$AH) ? this._$AA.nextSibling.data = e : this.T(g.createTextNode(e)), this._$AH = e;
	}
	$(e) {
		let { values: t, _$litType$: n } = e, r = typeof n == "number" ? this._$AC(e) : (n.el === void 0 && (n.el = De.createElement(Te(n.h, n.h[0]), this.options)), n);
		if (this._$AH?._$AD === r) this._$AH.p(t);
		else {
			let e = new Oe(r, this), n = e.u(this.options);
			e.p(t), this.T(n), this._$AH = e;
		}
	}
	_$AC(e) {
		let t = we.get(e.strings);
		return t === void 0 && we.set(e.strings, t = new De(e)), t;
	}
	k(t) {
		ge(this._$AH) || (this._$AH = [], this._$AR());
		let n = this._$AH, r, i = 0;
		for (let a of t) i === n.length ? n.push(r = new e(this.O(_()), this.O(_()), this, this.options)) : r = n[i], r._$AI(a), i++;
		i < n.length && (this._$AR(r && r._$AB.nextSibling, i), n.length = i);
	}
	_$AR(e = this._$AA.nextSibling, t) {
		for (this._$AP?.(!1, !0, t); e !== this._$AB;) {
			let t = de(e).nextSibling;
			de(e).remove(), e = t;
		}
	}
	setConnected(e) {
		this._$AM === void 0 && (this._$Cv = e, this._$AP?.(e));
	}
}, E = class {
	get tagName() {
		return this.element.tagName;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	constructor(e, t, n, r, i) {
		this.type = 1, this._$AH = C, this._$AN = void 0, this.element = e, this.name = t, this._$AM = r, this.options = i, n.length > 2 || n[0] !== "" || n[1] !== "" ? (this._$AH = Array(n.length - 1).fill(/* @__PURE__ */ new String()), this.strings = n) : this._$AH = C;
	}
	_$AI(e, t = this, n, r) {
		let i = this.strings, a = !1;
		if (i === void 0) e = T(this, e, t, 0), a = !v(e) || e !== this._$AH && e !== S, a && (this._$AH = e);
		else {
			let r = e, o, s;
			for (e = i[0], o = 0; o < i.length - 1; o++) s = T(this, r[n + o], t, o), s === S && (s = this._$AH[o]), a ||= !v(s) || s !== this._$AH[o], s === C ? e = C : e !== C && (e += (s ?? "") + i[o + 1]), this._$AH[o] = s;
		}
		a && !r && this.j(e);
	}
	j(e) {
		e === C ? this.element.removeAttribute(this.name) : this.element.setAttribute(this.name, e ?? "");
	}
}, Ae = class extends E {
	constructor() {
		super(...arguments), this.type = 3;
	}
	j(e) {
		this.element[this.name] = e === C ? void 0 : e;
	}
}, je = class extends E {
	constructor() {
		super(...arguments), this.type = 4;
	}
	j(e) {
		this.element.toggleAttribute(this.name, !!e && e !== C);
	}
}, Me = class extends E {
	constructor(e, t, n, r, i) {
		super(e, t, n, r, i), this.type = 5;
	}
	_$AI(e, t = this) {
		if ((e = T(this, e, t, 0) ?? C) === S) return;
		let n = this._$AH, r = e === C && n !== C || e.capture !== n.capture || e.once !== n.once || e.passive !== n.passive, i = e !== C && (n === C || r);
		r && this.element.removeEventListener(this.name, this, n), i && this.element.addEventListener(this.name, this, e), this._$AH = e;
	}
	handleEvent(e) {
		typeof this._$AH == "function" ? this._$AH.call(this.options?.host ?? this.element, e) : this._$AH.handleEvent(e);
	}
}, Ne = class {
	constructor(e, t, n) {
		this.element = e, this.type = 6, this._$AN = void 0, this._$AM = t, this.options = n;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	_$AI(e) {
		T(this, e);
	}
}, Pe = ue.litHtmlPolyfillSupport;
Pe?.(De, ke), (ue.litHtmlVersions ??= []).push("3.3.3");
var Fe = (e, t, n) => {
	let r = n?.renderBefore ?? t, i = r._$litPart$;
	if (i === void 0) {
		let e = n?.renderBefore ?? null;
		r._$litPart$ = i = new ke(t.insertBefore(_(), e), e, void 0, n ?? {});
	}
	return i._$AI(e), i;
}, Ie = globalThis, D = class extends p {
	constructor() {
		super(...arguments), this.renderOptions = { host: this }, this._$Do = void 0;
	}
	createRenderRoot() {
		let e = super.createRenderRoot();
		return this.renderOptions.renderBefore ??= e.firstChild, e;
	}
	update(e) {
		let t = this.render();
		this.hasUpdated || (this.renderOptions.isConnected = this.isConnected), super.update(e), this._$Do = Fe(t, this.renderRoot, this.renderOptions);
	}
	connectedCallback() {
		super.connectedCallback(), this._$Do?.setConnected(!0);
	}
	disconnectedCallback() {
		super.disconnectedCallback(), this._$Do?.setConnected(!1);
	}
	render() {
		return S;
	}
};
D._$litElement$ = !0, D.finalized = !0, Ie.litElementHydrateSupport?.({ LitElement: D });
var Le = Ie.litElementPolyfillSupport;
Le?.({ LitElement: D }), (Ie.litElementVersions ??= []).push("4.2.2");
//#endregion
//#region node_modules/@lit/reactive-element/decorators/custom-element.js
var O = (e) => (t, n) => {
	n === void 0 ? customElements.define(e, t) : n.addInitializer(() => {
		customElements.define(e, t);
	});
}, Re = {
	attribute: !0,
	type: String,
	converter: f,
	reflect: !1,
	hasChanged: ce
}, ze = (e = Re, t, n) => {
	let { kind: r, metadata: i } = n, a = globalThis.litPropertyMetadata.get(i);
	if (a === void 0 && globalThis.litPropertyMetadata.set(i, a = /* @__PURE__ */ new Map()), r === "setter" && ((e = Object.create(e)).wrapped = !0), a.set(n.name, e), r === "accessor") {
		let { name: r } = n;
		return {
			set(n) {
				let i = t.get.call(this);
				t.set.call(this, n), this.requestUpdate(r, i, e, !0, n);
			},
			init(t) {
				return t !== void 0 && this.C(r, void 0, e, t), t;
			}
		};
	}
	if (r === "setter") {
		let { name: r } = n;
		return function(n) {
			let i = this[r];
			t.call(this, n), this.requestUpdate(r, i, e, !0, n);
		};
	}
	throw Error("Unsupported decorator location: " + r);
};
function k(e) {
	return (t, n) => typeof n == "object" ? ze(e, t, n) : ((e, t, n) => {
		let r = t.hasOwnProperty(n);
		return t.constructor.createProperty(n, e), r ? Object.getOwnPropertyDescriptor(t, n) : void 0;
	})(e, t, n);
}
//#endregion
//#region node_modules/@lit/reactive-element/decorators/state.js
function A(e) {
	return k({
		...e,
		state: !0,
		attribute: !1
	});
}
//#endregion
//#region node_modules/@lit/reactive-element/decorators/base.js
var Be = (e, t, n) => (n.configurable = !0, n.enumerable = !0, Reflect.decorate && typeof t != "object" && Object.defineProperty(e, t, n), n);
//#endregion
//#region node_modules/@lit/reactive-element/decorators/query.js
function Ve(e, t) {
	return (n, r, i) => {
		let a = (t) => t.renderRoot?.querySelector(e) ?? null;
		if (t) {
			let { get: e, set: t } = typeof r == "object" ? n : i ?? (() => {
				let e = Symbol();
				return {
					get() {
						return this[e];
					},
					set(t) {
						this[e] = t;
					}
				};
			})();
			return Be(n, r, { get() {
				let n = e.call(this);
				return n === void 0 && (n = a(this), (n !== null || this.hasUpdated) && t.call(this, n)), n;
			} });
		}
		return Be(n, r, { get() {
			return a(this);
		} });
	};
}
//#endregion
//#region node_modules/lit-html/static.js
var He = Symbol.for(""), Ue = (e) => {
	if (e?.r === He) return e?._$litStatic$;
}, We = (e) => ({
	_$litStatic$: e,
	r: He
}), Ge = /* @__PURE__ */ new Map(), Ke = ((e) => (t, ...n) => {
	let r = n.length, i, a, o = [], s = [], c, l = 0, u = !1;
	for (; l < r;) {
		for (c = t[l]; l < r && (a = n[l], (i = Ue(a)) !== void 0);) c += i + t[++l], u = !0;
		l !== r && s.push(a), o.push(c), l++;
	}
	if (l === r && o.push(t[r]), u) {
		let e = o.join("$$lit$$");
		(t = Ge.get(e)) === void 0 && (o.raw = o, Ge.set(e, t = o)), n = s;
	}
	return e(t, ...n);
})(x), qe = "component.device_links", Je = ["exceptions", "issues"];
function Ye(e, t) {
	return t ? e.replace(/\{(\w+)\}/g, (e, n) => {
		let r = t[n];
		return r == null ? e : String(r);
	}) : e;
}
function Xe(e, t, n) {
	for (let r of Je) {
		let i = e?.localize(`${qe}.${r}.${t}.message`, { ...n ?? {} });
		if (i) return i;
	}
	let r = {
		backend_not_loaded: "The {backend} integration is not loaded, so the group {group} link from {device} to {target} was not written. Set that protocol integration up again, then apply.",
		blocked_by_plan: "The plan refused a change on {device} without saying why. That is a fault in Device Links rather than in the device; please report it with the diagnostics file.",
		button_semantics_unknown: "{emitter} on {device} may toggle rather than always sending off, so an off-all button here can turn the lights back on every second press. Test it before you rely on it.",
		check_failed: "The Z-Wave driver could not be asked whether group {group} on {device} may reach {target}, so nothing was written. Check that Z-Wave JS is running, then try again.",
		device_unavailable: "{device} stopped answering, so its group {group} link to {target} was left alone. It will be planned again once the device can be read.",
		feature_unavailable_color: "{emitter} does not send colour commands, so the colour part of this rule was left out.",
		feature_unavailable_level_hold: "{emitter} does not send hold-to-dim, so holding the control will do nothing. The rest of the rule still works.",
		feature_unavailable_level_set: "{emitter} does not send a brightness level, so dimming was left out of this rule. The rest of it still works.",
		feature_unavailable_on_off: "{emitter} does not send an on or off command, so this rule cannot switch anything with it. Choose a control that does, or take on/off out of the rule.",
		feature_unavailable_scene: "{emitter} does not send scene commands, so the scene part of this rule was left out.",
		feature_unavailable_status_report: "{emitter} does not report its own state, so the status feedback part of this rule was left out.",
		group_full: "Group {group} on {device} is full ({used} of {capacity}). Remove an entry it holds, or point this rule at a group with room, before adding {target}.",
		group_not_offered: "No control of {device} uses association group {group}. The groups it offers are: {groups}.",
		import_unknown_devices: "This profile names devices that are not on this network: {devices}. The rules waiting for them are: {rules}. Nothing was imported, so nothing was lost.",
		job_running: "An apply is already running. Wait for it to finish and plan again: a plan made before it started would be out of date by the time it ran.",
		level_hold_without_on_off: "{emitter} can dim on hold but cannot switch on or off, so the light can be dimmed and not turned on. Add on/off to the rule if the control supports it.",
		lifeline_is_protected: "Group {group} on {device} is its lifeline, which is how the device reports to Home Assistant at all. Device Links never writes to it.",
		link_write_failed: "{device} did not accept the group {group} link to {target}. The error the backend reported is in the job details.",
		link_write_raised: "Writing the group {group} link from {device} to {target} failed unexpectedly, so it was not written. The error is in the log.",
		multi_channel_downgrade: "{emitter} cannot address a single endpoint, so the link to {device} was written to the whole device instead. Every endpoint of it will respond.",
		no_active_profile: "No profile is active, so there is nothing to do. Activate one first.",
		no_backend_loaded: "None of the protocol integrations Device Links adapts is loaded yet, so there is nothing to read or write. Setup is retried automatically; if Z-Wave JS was removed for good, remove Device Links as well.",
		no_supported_commands: "{target} cannot act on the commands {device} sends from group {group}, so the link would do nothing and was not written.",
		not_a_zwave_device: "{device} is not a Z-Wave device, and this action works on Z-Wave only.",
		not_loaded: "Device Links is not loaded, so there is nothing to act on. Its integration page says why it did not start.",
		operation_timeout: "{device} did not answer within {seconds} seconds while writing the group {group} link to {target}. It was retried twice and then reported as failed.",
		plan_out_of_date: "This plan was made before something changed, so nothing was written. Plan again and look at what it says now.",
		profile_exists: "A profile with the id {profile} already exists. Update that one, or give this one a different id.",
		profile_invalid: "This profile could not be read: {error}. Nothing was changed.",
		profile_not_active: "{profile} is not the active profile, so applying it would change what your house does without you switching to it. Activate it first, then apply.",
		runner_shut_down: "Device Links is unloading, so this apply was refused rather than written through backends that are being taken down. Try again once it has started up.",
		security_class_mismatch: "{device} and {target} were included with different security classes, so the radio refuses the group {group} link. Re-include one of them so that both match.",
		self_association: "A device cannot be in its own association group, so {device} cannot control itself over the radio.",
		self_association_use_hybrid_leg: "{device} cannot control itself over the radio. An automation can carry that instead; Device Links does not write those legs yet.",
		setting_not_applied: "{device} accepted the change to {setting} and then reported its old value, so the setting did not stick.",
		setting_not_reported: "{device} did not report {setting} back after it was written, so the change could not be confirmed.",
		setting_write_failed: "{setting} could not be written to {device}. The error is in the log; nothing else about the rule was changed.",
		settings_not_available: "{device} has no {setting} setting that Device Links knows how to write, so that part of the rule was not applied. The rest of it is unaffected; contributing a profile entry for this model would add it.",
		source_is_long_range: "{device} joined over Z-Wave Long Range, which cannot use associations at all. Re-include it as classic Z-Wave if you want to link it.",
		stale_plan: "{device} changed after this plan was made, so its group {group} link to {target} was not written. Plan again to see what is needed now.",
		storage_no_migration: "The stored profiles are at schema version {found} and this version of Device Links reads version {supported}, and there is no way to migrate between them. Restore the file from a backup, or move it aside and start again.",
		storage_unreadable: "The stored profiles could not be read: {error}. The file was left exactly as it is, so nothing has been lost.",
		storage_version_too_new: "The stored profiles were written by a newer version of Device Links (schema version {found}; this one reads {supported}). Update Home Assistant, or restore the file from a backup.",
		system_link_protected: "Group {group} on {device} holds a system link, which Device Links never writes to, so the entry for {target} was left alone.",
		target_cannot_receive: "{device} cannot act on {feature}, so that part of the rule would do nothing and was left out.",
		target_is_long_range: "{device} joined over Z-Wave Long Range, which cannot be an association target. Re-include it as classic Z-Wave if you want to link it.",
		target_security_class_not_granted: "{target} was not granted the security class {device} sends group {group} on, so the radio refuses the link. Re-include {target} with matching security.",
		two_way_target_has_no_control: "{device} has no single control that can drive the other device back, so this rule works in one direction only.",
		unknown_check_result: "The Z-Wave driver answered {value} when asked whether the group {group} link from {device} to {target} may be written, and this version of Device Links does not recognise that answer, so it refused. Please report it.",
		unknown_device: "{device} is not a device Device Links can see.",
		unknown_emitter: "{device} has no control called {emitter}. If the device was replaced by a different model, point the rule at one of the controls it does have.",
		unknown_group: "{device} does not report an association group {group}, so the link to {target} cannot be written. Re-interview the device in Z-Wave JS if you expected it to have one.",
		unknown_job: "No job with the id {job} is in the history. Only the most recent applies are kept.",
		unknown_profile: "There is no profile called {profile}. It may have been renamed or deleted since this was opened.",
		unknown_rule: "The active profile has no rule with the id {rule}.",
		unmanaged_not_selected: "The group {group} entry on {device} pointing at {target} was not created by Device Links, so it was left alone. Tick it in the plan if you want it removed.",
		unsupported_operation: "Device Links cannot carry out {operation} on {device} yet, so it was reported rather than attempted.",
		verify_missing: "The group {group} link from {device} to {target} was written and is not on the device, so it counts as drifted. Apply again, or look at the group in Z-Wave JS.",
		verify_not_confirmed: "{device} did not confirm the group {group} link to {target} on a fresh read, so it is reported as unconfirmed rather than as applied. Press Verify when the device is awake and reachable.",
		verify_still_present: "The group {group} entry on {device} pointing at {target} was removed and is still on the device, so it counts as drifted.",
		verify_unreadable: "{device} could not be read after the write, so the group {group} link to {target} cannot be confirmed. Press Verify when the device is reachable."
	}[t];
	return r === void 0 ? null : Ye(r, n);
}
function Ze(e, t) {
	if (!t) return "";
	let n = Xe(e, t.translation_key, t.placeholders);
	return n === null ? `Device Links reported "${t.translation_key.replace(/_/g, " ")}", and this panel has no wording for it yet.` : n;
}
//#endregion
//#region src/api.ts
var j = {
	profilesList: "device_links/profiles/list",
	profilesGet: "device_links/profiles/get",
	profilesCreate: "device_links/profiles/create",
	profilesUpdate: "device_links/profiles/update",
	profilesDelete: "device_links/profiles/delete",
	profilesActivate: "device_links/profiles/activate",
	profilesDuplicate: "device_links/profiles/duplicate",
	profilesExport: "device_links/profiles/export",
	profilesImport: "device_links/profiles/import",
	rulesValidate: "device_links/rules/validate",
	rulesUpsert: "device_links/rules/upsert",
	rulesDelete: "device_links/rules/delete",
	rulesSetEnabled: "device_links/rules/set_enabled",
	devicesList: "device_links/devices/list",
	devicesGet: "device_links/devices/get",
	devicesRefresh: "device_links/devices/refresh",
	templatesList: "device_links/templates/list",
	plan: "device_links/plan",
	apply: "device_links/apply",
	verify: "device_links/verify",
	jobsList: "device_links/jobs/list",
	jobsGet: "device_links/jobs/get",
	jobsCancel: "device_links/jobs/cancel",
	jobsSubscribe: "device_links/jobs/subscribe",
	unmanagedIgnore: "device_links/unmanaged/ignore",
	unmanagedRemove: "device_links/unmanaged/remove",
	snapshotsList: "device_links/snapshots/list"
}, M = class e extends Error {
	constructor(e, t = {}) {
		super(e), this.name = "DeviceLinksApiError", this.code = t.code ?? "unknown_error", this.translationKey = t.translationKey ?? null, this.translationDomain = t.translationDomain ?? null, this.placeholders = t.placeholders ?? {};
	}
	static from(t) {
		return t instanceof e ? t : Qe(t) ? new e(t.message || "Device Links could not answer.", {
			code: t.code,
			translationKey: t.translation_key ?? null,
			translationDomain: t.translation_domain ?? null,
			placeholders: t.translation_placeholders ?? null
		}) : t instanceof Error ? new e(t.message || "Device Links could not answer.", { code: "connection_error" }) : new e("Device Links could not answer, and gave no reason. The connection to Home Assistant may have dropped.", { code: "connection_error" });
	}
};
function Qe(e) {
	if (typeof e != "object" || !e) return !1;
	let t = e;
	return typeof t.code == "string" && typeof t.message == "string";
}
function N(e, t) {
	if (t.translationKey) {
		let n = Xe(e, t.translationKey, t.placeholders);
		if (n !== null) return n;
	}
	return Ye(t.message, t.placeholders);
}
function $e(e) {
	let t = {};
	return e?.rule_ids?.length && (t.rule_ids = [...e.rule_ids]), e?.device_ids?.length && (t.device_ids = [...e.device_ids]), t;
}
var et = class {
	constructor(e) {
		this.open = /* @__PURE__ */ new Set(), this.hass = e;
	}
	async listProfiles() {
		return this.send(j.profilesList);
	}
	async getProfile(e) {
		return this.send(j.profilesGet, { profile_id: e });
	}
	async createProfile(e) {
		return (await this.send(j.profilesCreate, { profile: e })).profile;
	}
	async updateProfile(e) {
		return (await this.send(j.profilesUpdate, { profile: e })).profile;
	}
	async deleteProfile(e) {
		await this.send(j.profilesDelete, { profile_id: e });
	}
	async activateProfile(e) {
		return this.send(j.profilesActivate, { profile_id: e });
	}
	async duplicateProfile(e, t) {
		return (await this.send(j.profilesDuplicate, {
			profile_id: e,
			...t === void 0 ? {} : { name: t }
		})).profile;
	}
	async exportProfile(e) {
		return this.send(j.profilesExport, { ...e === void 0 ? {} : { profile_id: e } });
	}
	async importProfile(e) {
		return this.send(j.profilesImport, { yaml: e });
	}
	async validateRule(e) {
		return this.send(j.rulesValidate, { rule: e });
	}
	async upsertRule(e, t) {
		return this.send(j.rulesUpsert, {
			rule: e,
			...t === void 0 ? {} : { profile_id: t }
		});
	}
	async deleteRule(e, t) {
		await this.send(j.rulesDelete, {
			rule_id: e,
			...t === void 0 ? {} : { profile_id: t }
		});
	}
	async setRuleEnabled(e, t) {
		return this.send(j.rulesSetEnabled, {
			rule_id: e,
			enabled: t
		});
	}
	async listDevices() {
		return (await this.send(j.devicesList)).devices;
	}
	async getDevice(e) {
		return this.send(j.devicesGet, { device_id: e });
	}
	async refreshDevice(e, t = !1) {
		return this.send(j.devicesRefresh, {
			device_id: e,
			deep: t
		});
	}
	async listTemplates() {
		return (await this.send(j.templatesList)).templates;
	}
	async plan(e, t) {
		return this.send(j.plan, {
			...$e(e),
			...t?.length ? { remove_unmanaged: [...t] } : {}
		});
	}
	async apply(e) {
		return this.send(j.apply, {
			plan_token: e.planToken,
			...$e(e.scope),
			...e.removeUnmanaged?.length ? { remove_unmanaged: [...e.removeUnmanaged] } : {}
		});
	}
	async verify(e) {
		return this.send(j.verify, $e(e));
	}
	async listJobs() {
		return this.send(j.jobsList);
	}
	async getJob(e) {
		return this.send(j.jobsGet, { job_id: e });
	}
	async cancelJob() {
		return (await this.send(j.jobsCancel)).cancelled;
	}
	subscribeJobs(e, t) {
		let n = {
			closed: !1,
			unsubscribe: () => {
				n.closed || (n.closed = !0, this.open.delete(n), i());
			}
		}, r = null, i = () => {
			let e = r;
			if (r = null, e) try {
				Promise.resolve(e()).catch(() => void 0);
			} catch {}
		};
		return this.open.add(n), this.hass.connection.subscribeMessage((t) => {
			n.closed || e(t);
		}, { type: j.jobsSubscribe }).then((e) => {
			r = e, n.closed && i();
		}).catch((e) => {
			n.closed = !0, this.open.delete(n), t?.(M.from(e));
		}), n;
	}
	close() {
		for (let e of [...this.open]) e.unsubscribe();
	}
	async setUnmanagedIgnored(e, t) {
		return (await this.send(j.unmanagedIgnore, {
			fingerprints: [...e],
			ignored: t
		})).ignored;
	}
	async removeUnmanaged(e) {
		return this.send(j.unmanagedRemove, { fingerprints: [...e] });
	}
	async listSnapshots() {
		return (await this.send(j.snapshotsList)).snapshots;
	}
	async send(e, t = {}) {
		try {
			return await this.hass.connection.sendMessagePromise({
				type: e,
				...t
			});
		} catch (e) {
			throw M.from(e);
		}
	}
};
//#endregion
//#region \0@oxc-project+runtime@0.148.0/helpers/esm/decorate.js
function P(e, t, n, r) {
	var i = arguments.length, a = i < 3 ? t : r === null ? r = Object.getOwnPropertyDescriptor(t, n) : r, o;
	if (typeof Reflect == "object" && typeof Reflect.decorate == "function") a = Reflect.decorate(e, t, n, r);
	else for (var s = e.length - 1; s >= 0; s--) (o = e[s]) && (a = (i < 3 ? o(a) : i > 3 ? o(t, n, a) : o(t, n)) || a);
	return i > 3 && a && Object.defineProperty(t, n, a), a;
}
//#endregion
//#region src/components/two-pane.ts
var F = class extends D {
	constructor(...e) {
		super(...e), this.narrow = !1, this.showDetail = !1;
	}
	static {
		this.styles = o`
    :host {
      display: grid;
      gap: 16px;
      grid-template-columns: minmax(280px, 1fr) minmax(0, 2fr);
      align-items: start;
    }

    :host([narrow]) {
      grid-template-columns: 1fr;
    }

    .pane {
      min-width: 0;
    }

    .hidden {
      display: none;
    }
  `;
	}
	render() {
		let e = this.narrow && this.showDetail, t = this.narrow && !this.showDetail;
		return x`
      <div class="pane ${e ? "hidden" : ""}"><slot name="list"></slot></div>
      <div class="pane ${t ? "hidden" : ""}"><slot name="detail"></slot></div>
    `;
	}
};
P([k({
	type: Boolean,
	reflect: !0
})], F.prototype, "narrow", void 0), P([k({
	type: Boolean,
	attribute: "show-detail"
})], F.prototype, "showDetail", void 0), F = P([O("dl-two-pane")], F);
//#endregion
//#region src/ha-components.ts
var tt = [
	"ha-alert",
	"ha-assist-chip",
	"ha-button",
	"ha-card",
	"ha-checkbox",
	"ha-chip-set",
	"ha-data-table",
	"ha-dialog",
	"ha-expansion-panel",
	"ha-form",
	"ha-icon",
	"ha-icon-button",
	"ha-list-item",
	"ha-markdown",
	"ha-menu-button",
	"ha-select",
	"ha-spinner",
	"ha-svg-icon",
	"ha-switch",
	"ha-tab-group",
	"ha-tab-group-tab",
	"ha-tooltip",
	"ha-top-app-bar-fixed"
], nt = {
	"ha-alert": "div",
	"ha-assist-chip": "span",
	"ha-button": "button",
	"ha-card": "div",
	"ha-checkbox": "input",
	"ha-chip-set": "div",
	"ha-data-table": "div",
	"ha-dialog": "dialog",
	"ha-expansion-panel": "details",
	"ha-form": "div",
	"ha-icon": "span",
	"ha-icon-button": "button",
	"ha-list-item": "li",
	"ha-markdown": "div",
	"ha-menu-button": "span",
	"ha-select": "select",
	"ha-spinner": "span",
	"ha-svg-icon": "span",
	"ha-switch": "input",
	"ha-tab-group": "nav",
	"ha-tab-group-tab": "button",
	"ha-tooltip": "span",
	"ha-top-app-bar-fixed": "div"
}, rt = 5e3, it = class {
	constructor(e, t) {
		this.defined = e, this.missing = t;
	}
	has(e) {
		return this.defined.has(e);
	}
	tag(e) {
		return this.defined.has(e) ? e : nt[e] ?? "div";
	}
};
async function at(e = tt, t = {}) {
	let n = t.registry ?? globalThis.customElements;
	await ot(t.loadHelpers ?? (() => window.loadCardHelpers?.()));
	let r = t.timeoutMs ?? rt, i = /* @__PURE__ */ new Set(), a = [];
	return await Promise.all(e.map(async (e) => {
		await st(n, e, r) ? i.add(e) : a.push(e);
	})), a.sort(), a.length && console.warn(`Device Links: these Home Assistant components did not load, so plain elements are used instead: ${a.join(", ")}`), new it(i, a);
}
async function ot(e) {
	try {
		let t = await e();
		if (!t) return;
		await (await t.createCardElement({
			type: "entities",
			entities: []
		})).constructor.getConfigElement?.();
	} catch {}
}
async function st(e, t, n) {
	if (!e) return !1;
	if (e.get(t)) return !0;
	let r;
	try {
		return await Promise.race([e.whenDefined(t).then(() => !0), new Promise((e) => {
			r = setTimeout(() => e(!1), n);
		})]);
	} catch {
		return !1;
	} finally {
		r !== void 0 && clearTimeout(r);
	}
}
//#endregion
//#region src/tabs.ts
var I = [
	{
		id: "overview",
		label: "Overview",
		icon: "mdi:view-dashboard-outline",
		tagName: "device-links-overview"
	},
	{
		id: "rules",
		label: "Rules",
		icon: "mdi:link-variant",
		tagName: "device-links-rules"
	},
	{
		id: "devices",
		label: "Devices",
		icon: "mdi:z-wave",
		tagName: "device-links-devices"
	},
	{
		id: "profiles",
		label: "Profiles",
		icon: "mdi:file-multiple-outline",
		tagName: "device-links-profiles"
	},
	{
		id: "activity",
		label: "Activity",
		icon: "mdi:history",
		tagName: "device-links-activity"
	}
], ct = I[0]?.id ?? "overview";
function lt(e) {
	let t = (e ?? "").split("/").filter(Boolean)[0];
	return I.some((e) => e.id === t) ? t : ct;
}
//#endregion
//#region src/format.ts
var ut = {
	on_off: "On and off",
	level_set: "Brightness",
	level_hold: "Hold to dim",
	scene: "Scenes",
	color: "Colour",
	status_report: "Status feedback"
}, dt = {
	on_off: "mdi:power",
	level_set: "mdi:brightness-6",
	level_hold: "mdi:gesture-tap-hold",
	scene: "mdi:palette-outline",
	color: "mdi:invert-colors",
	status_report: "mdi:arrow-left-right"
}, ft = {
	zwave: "Z-Wave",
	zigbee2mqtt: "Zigbee",
	matter: "Matter"
}, pt = {
	remote: "Remote control",
	virtual_3way: "Virtual 3-way",
	scene_button: "Scene button",
	off_all: "Off all",
	status_feedback: "Status feedback",
	custom: "Custom"
}, mt = {
	remote: "One control drives one or more lights, on, off and dimming.",
	virtual_3way: "Two switches control each other, so either one works like the other.",
	scene_button: "A scene button sends one command to the devices you pick.",
	off_all: "One press turns a set of devices off.",
	status_feedback: "A device reports its state back to the control that drives it.",
	custom: "Choose the control, the targets and the features yourself."
}, ht = {
	in_sync: "In sync",
	drift: "Drift",
	pending: "Pending",
	blocked: "Blocked",
	disabled: "Disabled",
	unknown: "Unknown"
}, gt = {
	in_sync: "ok",
	drift: "error",
	pending: "warn",
	blocked: "error",
	disabled: "muted",
	unknown: "muted"
}, _t = {
	in_sync: "Every link this rule asks for is on the devices.",
	drift: "The devices do not hold what this rule asks for. Something changed them.",
	pending: "This rule has links waiting to be written. Plan and apply to write them.",
	blocked: "This rule compiles to nothing. Open it to see why.",
	disabled: "This rule is off, so its links are not on the devices.",
	unknown: "A device this rule uses could not be read, so its state cannot be judged."
}, vt = {
	completed: "Completed",
	partial: "Partly done",
	cancelled: "Cancelled",
	interrupted: "Interrupted"
}, yt = {
	completed: "ok",
	partial: "warn",
	cancelled: "muted",
	interrupted: "error"
}, bt = {
	applied: "Written",
	already_present: "Already there",
	unverified: "Written, not verified",
	unconfirmed: "Written, not confirmed",
	pending_wakeup: "Waiting for the device to wake",
	failed: "Failed",
	blocked: "Blocked",
	stale_plan: "Plan was out of date",
	cancelled: "Cancelled",
	interrupted: "Interrupted"
}, xt = {
	applied: "ok",
	already_present: "ok",
	unverified: "warn",
	unconfirmed: "warn",
	pending_wakeup: "warn",
	failed: "error",
	blocked: "error",
	stale_plan: "warn",
	cancelled: "muted",
	interrupted: "error"
};
function L(e) {
	return ut[e] ?? e;
}
function St(e) {
	return dt[e] ?? "mdi:link-variant";
}
function R(e) {
	return e === null ? "Unknown protocol" : ft[e] ?? e;
}
function z(e) {
	return pt[e] ?? e;
}
function Ct(e) {
	return mt[e] ?? "";
}
function B(e) {
	return ht[e] ?? e;
}
function wt(e) {
	return gt[e] ?? "muted";
}
function Tt(e) {
	return _t[e] ?? "";
}
function Et(e) {
	return vt[e] ?? e;
}
function Dt(e) {
	return yt[e] ?? "muted";
}
function Ot(e) {
	return bt[e] ?? e;
}
function kt(e) {
	return xt[e] ?? "muted";
}
function At(e, t) {
	let n = e.group_ids.length ? e.group_ids : Object.values(e.actions).filter((e) => e !== void 0), r = null;
	for (let i of n) {
		let n = t.filter((e) => e.emitter_group === i).length;
		(r === null || n > r.used) && (r = {
			group: i,
			used: n,
			capacity: e.capacity,
			free: Math.max(0, e.capacity - n)
		});
	}
	return r;
}
function jt(e) {
	let t = e.name || e.identity;
	return e.endpoint === null || e.endpoint === 0 ? t : `${t} (endpoint ${e.endpoint})`;
}
function Mt(e) {
	return `${L(e.feature)} from ${jt(e.source)} group ${e.emitter_group} to ${jt(e.target)}`;
}
function Nt(e) {
	let t = [], n = "", r = !1;
	for (let i of e) r ? (n += i, r = !1) : i === "\\" ? r = !0 : i === "|" ? (t.push(n), n = "") : n += i;
	t.push(n);
	let [i, a, o, s, c, l, u] = t;
	return t.length !== 7 || i === void 0 ? null : {
		backend: i,
		source: a ?? "",
		sourceEndpoint: o ?? "",
		group: s ?? "",
		target: c ?? "",
		targetEndpoint: l ?? "",
		feature: u ?? ""
	};
}
function Pt(e, t) {
	let n = Nt(e);
	if (n === null) return e;
	let r = ut[n.feature] ?? n.feature, i = n.targetEndpoint ? `${t(n.target)} (endpoint ${n.targetEndpoint})` : t(n.target);
	return `${r} from ${t(n.source)} group ${n.group} to ${i}`;
}
function V(e, t, n) {
	return `${e} ${e === 1 ? t : n ?? `${t}s`}`;
}
function Ft(e, t) {
	let n = new Date(e);
	if (Number.isNaN(n.getTime())) return e;
	try {
		return new Intl.DateTimeFormat(t || void 0, {
			dateStyle: "medium",
			timeStyle: "short"
		}).format(n);
	} catch {
		return n.toISOString();
	}
}
function It(e, t = Date.now()) {
	let n = new Date(e).getTime();
	if (Number.isNaN(n)) return "";
	let r = Math.max(0, Math.round((t - n) / 1e3));
	if (r < 60) return "just now";
	let i = Math.round(r / 60);
	if (i < 60) return `${V(i, "minute")} ago`;
	let a = Math.round(i / 60);
	return a < 24 ? `${V(a, "hour")} ago` : `${V(Math.round(a / 24), "day")} ago`;
}
//#endregion
//#region src/styles.ts
var H = o`
  :host {
    display: block;
    color: var(--primary-text-color, #212121);
    font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif);
    font-size: 14px;
  }

  .content {
    padding: 16px;
    max-width: 1400px;
    margin: 0 auto;
    box-sizing: border-box;
  }

  .card {
    background: var(--card-background-color, #fff);
    border-radius: var(--ha-card-border-radius, 12px);
    box-shadow: var(--ha-card-box-shadow, 0 2px 2px rgba(0, 0, 0, 0.12));
    border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    padding: 16px;
    box-sizing: border-box;
  }

  .card + .card {
    margin-top: 16px;
  }

  h2 {
    font-size: 20px;
    font-weight: 500;
    margin: 0 0 8px;
  }

  h3 {
    font-size: 16px;
    font-weight: 500;
    margin: 0 0 8px;
  }

  h4 {
    font-size: 14px;
    font-weight: 500;
    margin: 0 0 4px;
  }

  p {
    margin: 0 0 8px;
    line-height: 1.5;
  }

  .secondary {
    color: var(--secondary-text-color, #727272);
  }

  a {
    color: var(--primary-color, #03a9f4);
  }

  /* Layout helpers. */

  .row {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }

  .row.nowrap {
    flex-wrap: nowrap;
    white-space: nowrap;
  }

  .spread {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
  }

  .grow {
    flex: 1 1 200px;
    min-width: 0;
  }

  .stack {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .toolbar {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
    margin-bottom: 12px;
  }

  .truncate {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* Chips: a small piece of state, in one of five tones. */

  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 10px;
    border-radius: 14px;
    font-size: 12px;
    line-height: 20px;
    white-space: nowrap;
    border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    background: var(--secondary-background-color, #f5f5f5);
    color: var(--primary-text-color, #212121);
  }

  .chip.ok {
    border-color: var(--success-color, #43a047);
    color: var(--success-color, #43a047);
    background: transparent;
  }

  .chip.warn {
    border-color: var(--warning-color, #ffa600);
    color: var(--warning-color, #ffa600);
    background: transparent;
  }

  .chip.error {
    border-color: var(--error-color, #db4437);
    color: var(--error-color, #db4437);
    background: transparent;
  }

  .chip.info {
    border-color: var(--info-color, #039be5);
    color: var(--info-color, #039be5);
    background: transparent;
  }

  .chip.muted {
    color: var(--secondary-text-color, #727272);
  }

  /* Buttons. Home Assistant's own when it has them, these when it does not. */

  button {
    font: inherit;
    color: var(--primary-color, #03a9f4);
    background: none;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 8px 12px;
    cursor: pointer;
    min-height: 36px;
  }

  button:hover:not(:disabled) {
    background: var(--secondary-background-color, #f5f5f5);
  }

  button:focus-visible {
    outline: 2px solid var(--primary-color, #03a9f4);
    outline-offset: 2px;
  }

  button:disabled {
    color: var(--disabled-text-color, #bdbdbd);
    cursor: default;
  }

  button.primary {
    background: var(--primary-color, #03a9f4);
    color: var(--text-primary-color, #fff);
  }

  button.primary:hover:not(:disabled) {
    filter: brightness(1.08);
  }

  button.primary:disabled {
    background: var(--disabled-text-color, #bdbdbd);
    color: var(--card-background-color, #fff);
  }

  button.outlined {
    border-color: var(--divider-color, rgba(0, 0, 0, 0.12));
  }

  button.danger {
    color: var(--error-color, #db4437);
  }

  button.link {
    padding: 0;
    min-height: 0;
    text-decoration: underline;
  }

  /* Form controls. ha-textfield does not exist on the target frontend, so these are
     plain elements styled to sit beside Home Assistant's own. */

  input[type="text"],
  input[type="search"],
  select,
  textarea {
    font: inherit;
    color: var(--primary-text-color, #212121);
    background: var(--card-background-color, #fff);
    border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.38));
    border-radius: 8px;
    padding: 8px 10px;
    min-height: 36px;
    box-sizing: border-box;
    max-width: 100%;
  }

  textarea {
    width: 100%;
    min-height: 160px;
    font-family: var(--code-font-family, ui-monospace, monospace);
    font-size: 13px;
  }

  input:focus-visible,
  select:focus-visible,
  textarea:focus-visible {
    outline: 2px solid var(--primary-color, #03a9f4);
    outline-offset: 1px;
  }

  label.field {
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 12px;
    color: var(--secondary-text-color, #727272);
  }

  label.choice {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 6px 0;
    cursor: pointer;
  }

  label.choice.disabled {
    cursor: default;
    color: var(--disabled-text-color, #bdbdbd);
  }

  /* Lists and tables. Every table scrolls inside its own box rather than pushing the
     page sideways, because a rules table on a phone is wider than the phone. */

  .scroll-x {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }

  table {
    border-collapse: collapse;
    width: 100%;
    font-size: 14px;
  }

  th {
    text-align: left;
    font-weight: 500;
    color: var(--secondary-text-color, #727272);
    padding: 8px;
    border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    white-space: nowrap;
  }

  td.actions {
    white-space: nowrap;
  }

  td {
    padding: 8px;
    border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    vertical-align: top;
  }

  tbody tr:hover td {
    background: var(--secondary-background-color, #f5f5f5);
  }

  .list {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .list > li {
    padding: 10px 0;
    border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
  }

  .list > li:last-child {
    border-bottom: none;
  }

  .selectable {
    display: block;
    width: 100%;
    text-align: left;
    border-radius: 8px;
    padding: 8px 10px;
    border: 1px solid transparent;
    color: inherit;
  }

  .selectable[aria-current="true"] {
    background: var(--secondary-background-color, #f5f5f5);
    border-color: var(--primary-color, #03a9f4);
  }

  .empty {
    padding: 24px 8px;
    text-align: center;
    color: var(--secondary-text-color, #727272);
  }

  .unavailable {
    opacity: 0.72;
  }

  .mono {
    font-family: var(--code-font-family, ui-monospace, monospace);
    font-size: 12px;
    color: var(--secondary-text-color, #727272);
    overflow-wrap: anywhere;
  }

  .notice {
    border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    border-left: 4px solid var(--info-color, #039be5);
    border-radius: 8px;
    padding: 10px 12px;
    background: var(--secondary-background-color, #f5f5f5);
    margin-bottom: 12px;
  }

  .notice.warn {
    border-left-color: var(--warning-color, #ffa600);
  }

  .notice.error {
    border-left-color: var(--error-color, #db4437);
  }
`, U = class extends D {
	constructor(...e) {
		super(...e), this.narrow = !1, this.selected = null;
	}
	goTo(e, t) {
		this.dispatchEvent(new CustomEvent("dl-navigate", {
			detail: t === void 0 ? { tab: e } : {
				tab: e,
				select: t
			},
			bubbles: !0,
			composed: !0
		}));
	}
};
P([k({ attribute: !1 })], U.prototype, "hass", void 0), P([k({ attribute: !1 })], U.prototype, "api", void 0), P([k({ attribute: !1 })], U.prototype, "components", void 0), P([k({ type: Boolean })], U.prototype, "narrow", void 0), P([k({ attribute: !1 })], U.prototype, "selected", void 0);
//#endregion
//#region src/views/activity.ts
var W = class extends U {
	constructor(...e) {
		super(...e), this._jobs = [], this._running = null, this._selectedId = null, this._detail = null, this._devices = [], this._loading = !0, this._error = null, this._cancelling = !1, this._snapshots = [], this._subscription = null;
	}
	static {
		this.styles = H;
	}
	connectedCallback() {
		super.connectedCallback(), this._load(), this._subscribe();
	}
	disconnectedCallback() {
		super.disconnectedCallback(), this._subscription?.unsubscribe(), this._subscription = null;
	}
	willUpdate(e) {
		e.has("selected") && this.selected !== null && this._select(this.selected);
	}
	render() {
		return x`
      <div class="content">
        ${this._error === null ? C : x`<div class="notice error" role="alert">${this._error}</div>`}
        ${this._renderRunning()}
        <dl-two-pane .narrow=${this.narrow} ?show-detail=${this._selectedId !== null}>
          <div slot="list" class="card">${this._renderList()}</div>
          <div slot="detail" class="card">${this._renderDetail()}</div>
        </dl-two-pane>
        ${this._renderSnapshots()}
      </div>
    `;
	}
	_renderRunning() {
		let e = this._running;
		return e === null ? C : x`
      <div class="card">
        <div class="spread">
          <div class="grow">
            <h3>An apply is running</h3>
            <p class="secondary">
              ${e.completed} of ${e.total} done${e.devices_in_flight.length ? `, now on ${e.devices_in_flight.join(", ")}` : ""}.
            </p>
          </div>
          <button type="button" class="danger" ?disabled=${this._cancelling} @click=${this._cancel}>
            ${this._cancelling ? "Stopping" : "Stop"}
          </button>
        </div>
      </div>
    `;
	}
	_renderList() {
		return this._loading ? x`<p class="secondary">Loading.</p>` : this._jobs.length === 0 ? x`<p class="empty">Nothing has been applied yet.</p>` : x`
      <h3>${V(this._jobs.length, "job")}</h3>
      <ul class="list">
        ${this._jobs.map((e) => x`
            <li>
              <button
                type="button"
                class="selectable"
                aria-current=${e.id === this._selectedId ? "true" : "false"}
                @click=${() => this._select(e.id)}
              >
                <span class="row">
                  <span class="chip ${Dt(e.status)}">${Et(e.status)}</span>
                  <span class="grow truncate">${e.scope}</span>
                </span>
                <span class="secondary">
                  ${Ft(e.created_at, this.hass?.language)} &middot;
                  ${V(e.total, "link")}
                </span>
              </button>
            </li>
          `)}
      </ul>
    `;
	}
	_renderDetail() {
		let e = this._detail;
		return e === null ? x`<p class="empty">Choose a job to see what it did.</p>` : x`
      ${this.narrow ? x`<button type="button" class="link" @click=${this._clear}>Back to the list</button>` : C}
      <div class="row" style="margin: 8px 0">
        <span class="chip ${Dt(e.status)}">${Et(e.status)}</span>
        <strong class="grow">${e.scope}</strong>
      </div>
      <p class="secondary">
        ${Ft(e.created_at, this.hass?.language)} (${It(e.created_at)}) &middot;
        ${V(e.total, "link")}
      </p>
      <div class="chips" style="margin-bottom: 12px">
        ${[...this._outcomeCounts(e)].map(([e, t]) => x`<span class="chip ${kt(e)}">${Ot(e)} ${t}</span>`)}
      </div>
      ${e.results.length === 0 ? x`<p class="secondary">This job touched no links.</p>` : x`<ul class="list">${e.results.map((e) => this._renderResult(e))}</ul>`}
    `;
	}
	_renderResult(e) {
		return x`
      <li>
        <div class="row">
          <span class="chip ${kt(e.status)}">${Ot(e.status)}</span>
          <span class="grow">${Pt(e.fingerprint, (e) => this._nameOf(e))}</span>
        </div>
        <details>
          <summary class="secondary">What the backend reported</summary>
          <p class="mono">${e.reason ?? "Nothing beyond the outcome above."}</p>
          <p class="mono">${e.fingerprint}</p>
        </details>
      </li>
    `;
	}
	_renderSnapshots() {
		return this._snapshots.length === 0 ? C : x`
      <div class="card">
        <h3>Snapshots</h3>
        <p class="secondary">
          Taken before an apply, so what a device held can be read back. Restoring one is
          not in this release.
        </p>
        <div class="scroll-x">
          <table>
            <thead>
              <tr>
                <th>Taken</th>
                <th>Why</th>
                <th>Devices</th>
                <th>Links</th>
              </tr>
            </thead>
            <tbody>
              ${this._snapshots.map((e) => x`
                  <tr>
                    <td>${Ft(e.created_at, this.hass?.language)}</td>
                    <td>${e.reason}</td>
                    <td>${e.devices.length}</td>
                    <td>${e.links}</td>
                  </tr>
                `)}
            </tbody>
          </table>
        </div>
      </div>
    `;
	}
	_outcomeCounts(e) {
		let t = /* @__PURE__ */ new Map();
		for (let n of e.results) t.set(n.status, (t.get(n.status) ?? 0) + 1);
		return t;
	}
	_nameOf(e) {
		return this._devices.find((t) => t.identity === e)?.name ?? e;
	}
	async _load() {
		if (this.api) {
			this._loading = !0;
			try {
				let [e, t, n] = await Promise.all([
					this.api.listJobs(),
					this.api.listDevices(),
					this.api.listSnapshots()
				]);
				if (this._jobs = e.jobs ?? [], this._running = e.running ?? null, this._devices = t ?? [], this._snapshots = n ?? [], this._error = null, this._selectedId === null && !this.narrow) {
					let e = this._jobs[0];
					e !== void 0 && this._select(e.id);
				}
			} catch (e) {
				this._error = N(this.hass, M.from(e));
			} finally {
				this._loading = !1;
			}
		}
	}
	_select(e) {
		this._selectedId = e, this._detail = this._jobs.find((t) => t.id === e) ?? null, this.api && this.api.getJob(e).then((t) => {
			this._selectedId === e && (this._detail = t);
		}).catch((e) => {
			this._error = N(this.hass, M.from(e));
		});
	}
	_clear() {
		this._selectedId = null, this._detail = null;
	}
	_subscribe() {
		this.api && this._subscription === null && (this._subscription = this.api.subscribeJobs((e) => {
			if (e.type === "progress") {
				this._running = e.job, this._cancelling = !1;
				return;
			}
			this._running = null, this._load();
		}, (e) => {
			this._error = N(this.hass, e);
		}));
	}
	async _cancel() {
		if (this.api) {
			this._cancelling = !0;
			try {
				await this.api.cancelJob();
			} catch (e) {
				this._error = N(this.hass, M.from(e)), this._cancelling = !1;
			}
		}
	}
};
P([A()], W.prototype, "_jobs", void 0), P([A()], W.prototype, "_running", void 0), P([A()], W.prototype, "_selectedId", void 0), P([A()], W.prototype, "_detail", void 0), P([A()], W.prototype, "_devices", void 0), P([A()], W.prototype, "_loading", void 0), P([A()], W.prototype, "_error", void 0), P([A()], W.prototype, "_cancelling", void 0), P([A()], W.prototype, "_snapshots", void 0), W = P([O("device-links-activity")], W);
//#endregion
//#region src/components/dialog.ts
var G = class extends D {
	constructor(...e) {
		super(...e), this.open = !1, this.heading = "", this.narrow = !1, this.dismissible = !0, this._returnFocusTo = null, this._onKeyDown = (e) => {
			this.open && this.dismissible && e.key === "Escape" && (e.stopPropagation(), this._close());
		};
	}
	static {
		this.styles = o`
    :host {
      display: contents;
    }

    .scrim {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.5);
      z-index: 8;
    }

    .dialog {
      position: fixed;
      z-index: 9;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      display: flex;
      flex-direction: column;
      width: min(720px, calc(100vw - 32px));
      max-height: calc(100vh - 64px);
      box-sizing: border-box;
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color, #212121);
      border-radius: var(--ha-card-border-radius, 12px);
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.32);
      font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif);
      font-size: 14px;
    }

    :host([narrow]) .dialog {
      top: 0;
      left: 0;
      transform: none;
      width: 100vw;
      height: 100dvh;
      max-height: none;
      border-radius: 0;
    }

    .dialog:focus-visible {
      outline: none;
    }

    header {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 16px 16px 8px;
      border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    }

    h2 {
      margin: 0;
      flex: 1;
      font-size: 20px;
      font-weight: 500;
      overflow-wrap: anywhere;
    }

    .body {
      padding: 16px;
      overflow-y: auto;
      overflow-x: hidden;
      flex: 1;
    }

    footer {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 8px;
      padding: 8px 16px 16px;
      border-top: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    }

    footer:empty {
      display: none;
    }

    button.close {
      font: inherit;
      color: inherit;
      background: none;
      border: none;
      border-radius: 50%;
      width: 36px;
      height: 36px;
      cursor: pointer;
      font-size: 18px;
      line-height: 1;
    }

    button.close:hover {
      background: var(--secondary-background-color, #f5f5f5);
    }

    button.close:focus-visible {
      outline: 2px solid var(--primary-color, #03a9f4);
      outline-offset: 2px;
    }
  `;
	}
	connectedCallback() {
		super.connectedCallback(), document.addEventListener("keydown", this._onKeyDown);
	}
	disconnectedCallback() {
		super.disconnectedCallback(), document.removeEventListener("keydown", this._onKeyDown);
	}
	updated(e) {
		e.has("open") && (this.open ? (this._returnFocusTo = document.activeElement, this._surface?.focus()) : this._returnFocusTo instanceof HTMLElement && (this._returnFocusTo.focus(), this._returnFocusTo = null));
	}
	render() {
		return this.open ? x`
      <div class="scrim" @click=${this._onScrim}></div>
      <div class="dialog" role="dialog" aria-modal="true" aria-label=${this.heading} tabindex="-1">
        <header>
          <h2>${this.heading}</h2>
          ${this.dismissible ? x`<button
                class="close"
                type="button"
                aria-label="Close"
                title="Close"
                @click=${this._close}
              >
                &#10005;
              </button>` : C}
        </header>
        <div class="body"><slot></slot></div>
        <footer><slot name="actions"></slot></footer>
      </div>
    ` : C;
	}
	_onScrim() {
		this.dismissible && this._close();
	}
	_close() {
		this.dispatchEvent(new CustomEvent("dl-dialog-closed", {
			bubbles: !0,
			composed: !0
		}));
	}
};
P([k({
	type: Boolean,
	reflect: !0
})], G.prototype, "open", void 0), P([k({ type: String })], G.prototype, "heading", void 0), P([k({
	type: Boolean,
	reflect: !0
})], G.prototype, "narrow", void 0), P([k({ type: Boolean })], G.prototype, "dismissible", void 0), P([Ve(".dialog")], G.prototype, "_surface", void 0), G = P([O("dl-dialog")], G);
//#endregion
//#region src/dialogs/plan-dialog.ts
var K = class extends D {
	constructor(...e) {
		super(...e), this.components = null, this.narrow = !1, this.open = !1, this.heading = "Plan and apply", this.initialPlan = null, this.initialRemoveUnmanaged = [], this._plan = null, this._phase = "loading", this._error = null, this._stale = !1, this._removeUnmanaged = [], this._progress = null, this._finished = null, this._cancelling = !1, this._jobId = null, this._subscription = null;
	}
	static {
		this.styles = [H, o`
      .summary {
        margin-bottom: 12px;
      }

      .device {
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 12px;
      }

      .device > header {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
        margin-bottom: 8px;
      }

      .device h3 {
        margin: 0;
        overflow-wrap: anywhere;
      }

      .bucket {
        margin-top: 10px;
      }

      .bucket h4 {
        margin: 0 0 4px;
        color: var(--secondary-text-color, #727272);
        text-transform: uppercase;
        font-size: 11px;
        letter-spacing: 0.06em;
      }

      .item {
        padding: 4px 0;
        overflow-wrap: anywhere;
      }

      .reason {
        color: var(--secondary-text-color, #727272);
        margin: 2px 0 0;
      }

      .bar {
        height: 8px;
        border-radius: 4px;
        background: var(--divider-color, rgba(0, 0, 0, 0.12));
        overflow: hidden;
        margin: 12px 0 8px;
      }

      .bar > div {
        height: 100%;
        background: var(--primary-color, #03a9f4);
        transition: width 120ms linear;
      }

      .unmanaged-item {
        display: flex;
        gap: 8px;
        align-items: flex-start;
        padding: 4px 0;
      }

      .unmanaged-item input {
        margin-top: 3px;
        min-height: 0;
      }
    `];
	}
	disconnectedCallback() {
		super.disconnectedCallback(), this._unsubscribe();
	}
	willUpdate(e) {
		e.has("open") && (this.open ? this._start() : this._reset());
	}
	render() {
		return x`
      <dl-dialog
        .open=${this.open}
        .narrow=${this.narrow}
        .heading=${this.heading}
        .dismissible=${this._phase !== "applying"}
        @dl-dialog-closed=${this._requestClose}
      >
        ${this._renderBody()}
        <div slot="actions">${this._renderActions()}</div>
      </dl-dialog>
    `;
	}
	_renderBody() {
		return this._error === null ? this._phase === "loading" ? x`<p class="secondary">Working out what would change.</p>` : this._phase === "applying" ? this._renderProgress() : this._phase === "finished" ? this._renderResult() : this._renderPlan() : x`
        <div class="notice error" role="alert">
          <p>${this._error}</p>
          ${this._stale ? x`<p class="secondary">
                Nothing was written. Plan again to see what would happen now.
              </p>` : C}
        </div>
      `;
	}
	_renderPlan() {
		let e = this._plan;
		return e === null ? x`<p class="secondary">No plan yet.</p>` : e.is_empty && e.counts.unmanaged === 0 ? x`
        <p>Nothing to do. Every link this covers is already on the devices.</p>
        ${e.unchanged_count > 0 ? x`<p class="secondary">
              ${V(e.unchanged_count, "link")} checked and left alone.
            </p>` : C}
      ` : x`
      ${this._renderSummary(e)}
      ${e.devices.map((e) => this._renderDevice(e))}
    `;
	}
	_renderSummary(e) {
		let t = e.counts;
		return x`
      <div class="summary">
        <p>
          ${V(this._changeCount(e), "change")} on
          ${V(e.devices.length, "device")}.
          ${e.unchanged_count > 0 ? x`<span class="secondary">
                ${V(e.unchanged_count, "link")} already correct.
              </span>` : C}
        </p>
        <div class="chips">
          ${this._countChip("Add", t.add, "ok")}
          ${this._countChip("Remove", t.remove, "warn")}
          ${this._countChip("Settings", t.set_param, "info")}
          ${this._countChip("Blocked", t.blocked, "error")}
          ${this._countChip("Pending", t.pending, "warn")}
          ${this._countChip("Unmanaged", t.unmanaged, "muted")}
        </div>
        ${this._renderUnmanagedControls(e)}
      </div>
    `;
	}
	_countChip(e, t, n) {
		return t === 0 ? C : x`<span class="chip ${n}">${e} ${t}</span>`;
	}
	_renderUnmanagedControls(e) {
		let t = this._selectableUnmanaged(e);
		if (t.length === 0) return C;
		let n = this._removeUnmanaged.length;
		return x`
      <div class="notice">
        <p>
          ${V(t.length, "link")} on these devices belong to no rule. They are
          left alone unless you tick them.
        </p>
        <div class="row">
          <span class="secondary">${n} selected for removal</span>
          <button
            type="button"
            class="link"
            @click=${() => this._selectAllUnmanaged(t)}
            ?disabled=${n === t.length}
          >
            ${t.length === 1 ? "Select it" : `Select all ${t.length}`}
          </button>
          <button
            type="button"
            class="link"
            @click=${() => this._setRemoveUnmanaged([])}
            ?disabled=${n === 0}
          >
            Clear
          </button>
        </div>
      </div>
    `;
	}
	_renderDevice(e) {
		return x`
      <section class="device">
        <header>
          <h3>${e.name}</h3>
          <span class="chip muted">${R(e.backend)}</span>
          ${e.available ? C : x`<span class="chip warn" title="This device is not answering right now">
                Not answering
              </span>`}
        </header>
        ${e.available ? C : x`<p class="secondary">
              Device Links cannot read this device right now, so what it holds is what was
              last seen. Anything planned for it may be refused when apply runs.
            </p>`}
        ${this._renderBucket("Add", e.add)}
        ${this._renderBucket("Remove", e.remove)}
        ${this._renderBucket("Settings", e.set_param)}
        ${this._renderBucket("Blocked", e.blocked)}
        ${this._renderBucket("Waiting for the device to wake", e.pending)}
        ${this._renderUnmanaged(e.unmanaged)}
      </section>
    `;
	}
	_renderBucket(e, t) {
		return t.length === 0 ? C : x`
      <div class="bucket">
        <h4>${e}</h4>
        ${t.map((e) => this._renderItem(e))}
      </div>
    `;
	}
	_renderItem(e) {
		let t = e.reason === null ? null : Ze(this.hass, e.reason);
		return x`
      <div class="item">
        <div>${this._describeItem(e)}</div>
        ${t === null ? C : x`<p class="reason">${t}</p>`}
        ${e.op === "pending" ? x`<p class="reason">
              Battery devices only accept changes while they are awake. Press a button on
              it, or wait for it to check in.
            </p>` : C}
      </div>
    `;
	}
	_describeItem(e) {
		if (e.link !== null) return Mt(e.link);
		if (e.setting !== null) {
			let t = e.setting, n = t.bitmask === null ? "" : ` (bitmask ${t.bitmask})`;
			return `Set ${t.capability}, parameter ${t.parameter}${n}, to ${t.value}`;
		}
		return "A change this panel has no wording for yet.";
	}
	_renderUnmanaged(e) {
		return e.length === 0 ? C : x`
      <div class="bucket">
        <h4>Not managed by any rule</h4>
        ${e.map((e) => this._renderUnmanagedLink(e))}
      </div>
    `;
	}
	_renderUnmanagedLink(e) {
		return e.is_system ? x`
        <div class="unmanaged-item">
          <span class="chip muted">System link</span>
          <span>${Mt(e)}</span>
        </div>
      ` : x`
      <label class="unmanaged-item">
        <input
          type="checkbox"
          .checked=${this._removeUnmanaged.includes(e.fingerprint)}
          ?disabled=${this._phase !== "plan"}
          @change=${(t) => this._toggleUnmanaged(e, t)}
        />
        <span>
          Also remove: ${Mt(e)}
          ${e.ignored ? x`<span class="chip muted">Ignored</span>` : C}
        </span>
      </label>
    `;
	}
	_renderProgress() {
		let e = this._progress, t = e?.total ?? 0, n = e?.completed ?? 0;
		return x`
      <p>Writing to your devices. Leave this open until it finishes.</p>
      <div class="bar"><div style=${`width: ${t === 0 ? 0 : Math.round(n / t * 100)}%`}></div></div>
      <p class="secondary">
        ${t === 0 ? "Starting" : `${n} of ${t} done`}
        ${e?.devices_in_flight.length ? x`<span> &middot; now on ${e.devices_in_flight.join(", ")}</span>` : C}
      </p>
      ${this._cancelling ? x`<p class="secondary">
            Stopping. What is already in flight still finishes.
          </p>` : C}
    `;
	}
	_renderResult() {
		let e = this._finished;
		if (e === null) return x`<p>The job finished.</p>`;
		let t = Object.entries(e.results);
		return x`
      <div class="row">
        <span class="chip ${Dt(e.status)}">${Et(e.status)}</span>
        <span class="secondary">${V(e.total, "link")} attempted</span>
      </div>
      <div class="chips" style="margin-top: 12px">
        ${t.map(([e, t]) => x`<span class="chip ${kt(e)}">
              ${Ot(e)} ${t}
            </span>`)}
      </div>
      ${e.status === "completed" ? C : x`<p class="secondary" style="margin-top: 12px">
            Activity has the per-link detail, including what each device said.
          </p>`}
    `;
	}
	_renderActions() {
		if (this._error !== null) return x`
        <button type="button" class="outlined" @click=${this._requestClose}>Close</button>
        <button type="button" class="primary" @click=${this._replan}>Plan again</button>
      `;
		if (this._phase === "applying") return x`
        <button type="button" class="danger" @click=${this._cancel} ?disabled=${this._cancelling}>
          Stop
        </button>
      `;
		if (this._phase === "finished") return x`
        <button type="button" class="outlined" @click=${this._replan}>Plan again</button>
        <button type="button" class="primary" @click=${this._requestClose}>Close</button>
      `;
		let e = this._plan === null ? 0 : this._changeCount(this._plan);
		return x`
      <button type="button" class="outlined" @click=${this._requestClose}>Cancel</button>
      <button
        type="button"
        class="primary"
        ?disabled=${this._phase !== "plan" || e === 0}
        @click=${this._apply}
      >
        ${e === 0 ? "Nothing to apply" : `Apply ${V(e, "change")}`}
      </button>
    `;
	}
	_changeCount(e) {
		return e.counts.add + e.counts.remove + e.counts.set_param;
	}
	_selectableUnmanaged(e) {
		return e.devices.flatMap((e) => e.unmanaged.filter((e) => !e.is_system));
	}
	_selectAllUnmanaged(e) {
		this._setRemoveUnmanaged(e.map((e) => e.fingerprint));
	}
	_toggleUnmanaged(e, t) {
		let n = t.target.checked, r = this._removeUnmanaged.filter((t) => t !== e.fingerprint);
		n && r.push(e.fingerprint), this._setRemoveUnmanaged(r);
	}
	_setRemoveUnmanaged(e) {
		this._removeUnmanaged = e, this._load();
	}
	_start() {
		if (this._reset(), this._removeUnmanaged = [...this.initialRemoveUnmanaged], this.initialPlan !== null) {
			this._plan = this.initialPlan, this._phase = "plan";
			return;
		}
		this._load();
	}
	_reset() {
		this._unsubscribe(), this._plan = null, this._phase = "loading", this._error = null, this._stale = !1, this._removeUnmanaged = [], this._progress = null, this._finished = null, this._cancelling = !1, this._jobId = null;
	}
	_replan() {
		this._error = null, this._stale = !1, this._finished = null, this._progress = null, this._jobId = null, this._load();
	}
	async _load() {
		if (this.api) {
			this._phase = "loading", this._error = null;
			try {
				this._plan = await this.api.plan(this.scope, this._removeUnmanaged), this._phase = "plan";
			} catch (e) {
				this._fail(e);
			}
		}
	}
	async _apply() {
		let e = this._plan;
		if (this.api && e !== null) {
			this._phase = "applying", this._error = null, this._progress = null, this._subscribe();
			try {
				let t = await this.api.apply({
					planToken: e.token,
					...this.scope === void 0 ? {} : { scope: this.scope },
					removeUnmanaged: this._removeUnmanaged
				});
				this._jobId = t.job_id, t.job_id === null && (this._unsubscribe(), this._phase = "plan", this._load());
			} catch (e) {
				this._unsubscribe(), this._fail(e);
			}
		}
	}
	async _cancel() {
		if (this.api) {
			this._cancelling = !0;
			try {
				await this.api.cancelJob();
			} catch (e) {
				this._fail(e);
			}
		}
	}
	_subscribe() {
		this._unsubscribe(), this._subscription = this.api.subscribeJobs((e) => {
			if (e.type === "progress") {
				this._progress = e.job;
				return;
			}
			(this._jobId === null || e.job.id === this._jobId) && (this._finished = e.job, this._phase = "finished", this._progress = null, this._unsubscribe(), this.dispatchEvent(new CustomEvent("dl-plan-applied", {
				detail: { job: e.job },
				bubbles: !0,
				composed: !0
			})));
		}, (e) => {
			this._error = N(this.hass, e);
		});
	}
	_unsubscribe() {
		this._subscription?.unsubscribe(), this._subscription = null;
	}
	_fail(e) {
		let t = M.from(e);
		this._error = N(this.hass, t), this._stale = t.translationKey === "plan_out_of_date", this._phase = "plan";
	}
	_requestClose() {
		this._phase !== "applying" && this.dispatchEvent(new CustomEvent("dl-plan-closed", {
			detail: {
				applied: this._phase === "finished",
				changes: this._plan === null ? 0 : this._changeCount(this._plan)
			},
			bubbles: !0,
			composed: !0
		}));
	}
};
P([k({ attribute: !1 })], K.prototype, "hass", void 0), P([k({ attribute: !1 })], K.prototype, "api", void 0), P([k({ attribute: !1 })], K.prototype, "components", void 0), P([k({ type: Boolean })], K.prototype, "narrow", void 0), P([k({ type: Boolean })], K.prototype, "open", void 0), P([k({ attribute: !1 })], K.prototype, "scope", void 0), P([k({ type: String })], K.prototype, "heading", void 0), P([k({ attribute: !1 })], K.prototype, "initialPlan", void 0), P([k({ attribute: !1 })], K.prototype, "initialRemoveUnmanaged", void 0), P([A()], K.prototype, "_plan", void 0), P([A()], K.prototype, "_phase", void 0), P([A()], K.prototype, "_error", void 0), P([A()], K.prototype, "_stale", void 0), P([A()], K.prototype, "_removeUnmanaged", void 0), P([A()], K.prototype, "_progress", void 0), P([A()], K.prototype, "_finished", void 0), P([A()], K.prototype, "_cancelling", void 0), K = P([O("dl-plan-dialog")], K);
//#endregion
//#region src/components/icon.ts
function Lt(e, t) {
	return e?.has("ha-icon") ? x`<ha-icon .icon=${t} aria-hidden="true"></ha-icon>` : C;
}
//#endregion
//#region src/views/devices.ts
var q = class extends U {
	constructor(...e) {
		super(...e), this._devices = [], this._detail = null, this._selectedId = null, this._search = "", this._loading = !0, this._busy = !1, this._error = null, this._confidence = "cached", this._incoming = null, this._incomingState = "idle", this._planOpen = !1, this._planRemove = [], this._planHeading = "Plan and apply", this._linkIndex = [], this._ignored = /* @__PURE__ */ new Set();
	}
	static {
		this.styles = H;
	}
	connectedCallback() {
		super.connectedCallback(), this._load();
	}
	willUpdate(e) {
		e.has("selected") && this.selected !== null && this._select(this.selected);
	}
	render() {
		return x`
      <div class="content">
        ${this._error === null ? C : x`<div class="notice error" role="alert">${this._error}</div>`}
        <dl-two-pane .narrow=${this.narrow} ?show-detail=${this._selectedId !== null}>
          <div slot="list" class="card">${this._renderList()}</div>
          <div slot="detail" class="card">${this._renderDetail()}</div>
        </dl-two-pane>
      </div>
      <dl-plan-dialog
        .hass=${this.hass}
        .api=${this.api}
        .components=${this.components}
        .narrow=${this.narrow}
        .open=${this._planOpen}
        .scope=${this._planScope}
        .initialRemoveUnmanaged=${this._planRemove}
        .heading=${this._planHeading}
        @dl-plan-closed=${this._closePlan}
        @dl-plan-applied=${this._afterApply}
      ></dl-plan-dialog>
    `;
	}
	_renderList() {
		let e = this._filtered();
		return x`
      <label class="field" style="margin-bottom: 8px">
        <span>Search</span>
        <input
          type="search"
          .value=${this._search}
          placeholder="Name or address"
          @input=${(e) => {
			this._search = e.target.value;
		}}
        />
      </label>
      ${this._loading ? x`<p class="secondary">Loading.</p>` : e.length === 0 ? x`<p class="empty">No device matches that search.</p>` : x`
              <ul class="list">
                ${e.map((e) => this._renderListRow(e))}
              </ul>
            `}
    `;
	}
	_renderListRow(e) {
		return x`
      <li>
        <button
          type="button"
          class="selectable ${e.available ? "" : "unavailable"}"
          aria-current=${e.device_id === this._selectedId ? "true" : "false"}
          ?disabled=${e.device_id === null}
          @click=${() => this._selectRow(e)}
        >
          <span class="row">
            <span class="grow">${e.name}</span>
            <span class="chip muted">${R(e.backend)}</span>
          </span>
          <span class="chips" style="margin-top: 4px">
            <span class="chip muted">${V(e.links, "link")}</span>
            <span class="chip muted">${V(e.emitters, "control")}</span>
            ${e.available ? C : x`<span class="chip warn">Not answering</span>`}
            ${e.is_long_range ? x`<span class="chip error">Long Range</span>` : C}
            ${e.device_id === null ? x`<span class="chip muted">No Home Assistant device</span>` : C}
          </span>
        </button>
      </li>
    `;
	}
	_renderDetail() {
		let e = this._detail;
		if (e === null) return x`<p class="empty">Choose a device to see what is on it.</p>`;
		let t = e.device;
		return x`
      ${this.narrow ? x`<button type="button" class="link" @click=${this._clear}>Back to the list</button>` : C}
      <div class="spread" style="margin-top: 8px">
        <div class="grow">
          <h2>${t.name}</h2>
          <div class="chips">
            <span class="chip muted">${R(t.backend)}</span>
            <span class="chip muted">${t.protocol_id}</span>
            ${t.available ? C : x`<span class="chip warn">Not answering</span>`}
            ${t.is_long_range ? x`<span class="chip error">Long Range</span>` : C}
          </div>
        </div>
        <div class="row">
          <button type="button" class="outlined" ?disabled=${this._busy} @click=${() => this._refresh(!1)}>
            Refresh
          </button>
          <button type="button" class="outlined" ?disabled=${this._busy} @click=${() => this._refresh(!0)}>
            Deep verify
          </button>
        </div>
      </div>
      ${this._renderConfidence(t)}
      ${this._renderOutgoing(e)}
      ${this._renderIncoming(e)}
      ${this._renderSettings(e)}
    `;
	}
	_renderConfidence(e) {
		return e.available ? this._confidence === "confirmed" ? x`
        <div class="notice">
          <p>Read from the device itself just now.</p>
        </div>
      ` : this._confidence === "unconfirmed" ? x`
        <div class="notice warn">
          <p>
            The deep verify did not come back confirmed. The device may have been asleep or
            simply did not report a value, so what follows is still the last known state
            rather than a fresh reading. It is not evidence that anything is wrong.
          </p>
        </div>
      ` : x`
      <p class="secondary">
        From the driver's cache. Deep verify reads the device itself.
      </p>
    ` : x`
        <div class="notice warn">
          <p>
            This device is not answering. What follows is what Device Links last read from
            it, kept so you can see what it holds; it cannot be confirmed right now, and
            nothing can be planned for it until it answers again.
          </p>
        </div>
      `;
	}
	_renderOutgoing(e) {
		let t = /* @__PURE__ */ new Set();
		return x`
      <h3 style="margin-top: 16px">Outgoing</h3>
      <p class="secondary">What this device sends, and to whom.</p>
      ${e.emitters.length === 0 ? x`<p class="secondary">This device offers no controls that reach another device.</p>` : e.emitters.map((n) => this._renderEmitter(e, n, t))}
      ${this._renderOrphans(e, t)}
    `;
	}
	_renderEmitter(e, t, n) {
		let r = new Set(t.group_ids.length ? t.group_ids : Object.values(t.actions).filter((e) => e !== void 0)), i = e.links.filter((e) => r.has(e.emitter_group));
		for (let e of i) n.add(e.fingerprint);
		let a = At(t, e.links), o = Object.keys(t.actions);
		return x`
      <div class="card" style="margin-top: 8px">
        <div class="row">
          <strong class="grow">${t.label}</strong>
          ${t.is_lifeline ? x`<span class="chip muted" title="Device Links never writes to a lifeline">
                System link
              </span>` : C}
          ${a === null ? C : x`<span class="chip ${a.free === 0 ? "warn" : "muted"}">
                ${a.used} of ${a.capacity} used in group ${a.group}
              </span>`}
        </div>
        <div class="chips" style="margin: 6px 0">
          ${o.map((e) => x`<span class="chip">
                ${Lt(this.components, St(e))}${L(e)}
              </span>`)}
          ${t.semantics === "unknown" ? x`<span class="chip warn" title="What this control sends has not been observed">
                Unverified
              </span>` : C}
        </div>
        ${i.length === 0 ? x`<p class="secondary">Nothing on it.</p>` : x`<ul class="list">${i.map((e) => this._renderEntry(e))}</ul>`}
      </div>
    `;
	}
	_renderOrphans(e, t) {
		let n = e.links.filter((e) => !t.has(e.fingerprint));
		return n.length === 0 ? C : x`
      <div class="card" style="margin-top: 8px">
        <div class="row">
          <strong class="grow">Other groups</strong>
          <span class="chip muted">${V(n.length, "entry", "entries")}</span>
        </div>
        <p class="secondary">
          These are on groups no control of this device claims, so Device Links cannot say
          which button they belong to.
        </p>
        <ul class="list">${n.map((e) => this._renderEntry(e))}</ul>
      </div>
    `;
	}
	_renderEntry(e) {
		let t = !e.is_system && e.rule_id === null;
		return x`
      <li>
        <div class="spread">
          <div class="grow">
            <div class="row">
              <span>${jt(e.target)}</span>
              <span class="chip muted">${L(e.feature)}</span>
              <span class="chip muted">group ${e.emitter_group}</span>
            </div>
            <p class="secondary" style="margin: 4px 0 0">
              ${e.is_system ? "System link. Device Links never removes this." : e.rule_name === null ? e.rule_id === null ? "Not managed by any rule. Somebody added this by hand, or a rule that used to own it changed." : "Managed by a rule that is no longer in the active profile" : `Managed by ${e.rule_name}`}
            </p>
          </div>
          ${this._renderEntryActions(e, t)}
        </div>
      </li>
    `;
	}
	_renderEntryActions(e, t) {
		return e.is_system || !t ? C : x`
      <div class="row">
        <button
          type="button"
          class="outlined"
          ?disabled=${this._busy}
          @click=${() => this._setIgnored(e, !this._isIgnored(e))}
        >
          ${this._isIgnored(e) ? "Stop ignoring" : "Ignore"}
        </button>
        <button type="button" class="danger" @click=${() => this._planRemoval(e)}>
          Remove
        </button>
      </div>
    `;
	}
	_renderIncoming(e) {
		let t = e.device.identity;
		return x`
      <h3 style="margin-top: 16px">Incoming</h3>
      <p class="secondary">What reaches this device from somewhere else.</p>
      ${this._incomingState === "loading" ? x`<p class="secondary">Reading every device to find what controls this one.</p>` : this._incomingState === "error" ? x`<p class="secondary">
              The other devices could not all be read, so this list may be short.
            </p>` : C}
      ${this._renderIncomingList(t)}
    `;
	}
	_renderIncomingList(e) {
		let t = (this._incoming ?? []).filter((t) => t.target.identity === e);
		return this._incomingState === "loading" ? x`` : t.length === 0 ? x`<p class="secondary">Nothing controls this device over the radio.</p>` : x`
      <ul class="list">
        ${t.map((e) => x`
            <li>
              <div class="row">
                <span class="grow">${jt(e.source)}</span>
                <span class="chip muted">group ${e.emitter_group}</span>
                <span class="chip muted">${L(e.feature)}</span>
                ${e.is_system ? x`<span class="chip muted">System link</span>` : C}
              </div>
              <p class="secondary" style="margin: 4px 0 0">
                ${e.rule_name ?? (e.is_system ? "System link" : "Not managed by any rule")}
              </p>
            </li>
          `)}
      </ul>
    `;
	}
	_renderSettings(e) {
		let t = Object.entries(e.settings);
		return t.length === 0 ? C : x`
      <h3 style="margin-top: 16px">Association settings</h3>
      <p class="secondary">
        The device settings a rule can write. The value is what was last read from the device.
      </p>
      <div class="scroll-x">
        <table>
          <thead>
            <tr>
              <th>Setting</th>
              <th>Current value</th>
            </tr>
          </thead>
          <tbody>
            ${t.map(([e, t]) => x`
                <tr>
                  <td>${e}</td>
                  <td class="mono">${String(t)}</td>
                </tr>
              `)}
          </tbody>
        </table>
      </div>
    `;
	}
	_filtered() {
		let e = this._search.trim().toLowerCase();
		return e ? this._devices.filter((t) => `${t.name} ${t.protocol_id}`.toLowerCase().includes(e)) : this._devices;
	}
	async _load() {
		if (this.api) {
			this._loading = !0;
			try {
				this._devices = await this.api.listDevices() ?? [], this._error = null;
			} catch (e) {
				this._error = N(this.hass, M.from(e));
			} finally {
				this._loading = !1;
			}
		}
	}
	_selectRow(e) {
		e.device_id !== null && this._select(e.device_id);
	}
	async _select(e) {
		if (this.api) {
			this._selectedId = e, this._confidence = "cached", this._busy = !0;
			try {
				this._detail = await this.api.getDevice(e), this._error = null;
			} catch (e) {
				this._error = N(this.hass, M.from(e));
			} finally {
				this._busy = !1;
			}
			this._loadIncoming();
		}
	}
	_clear() {
		this._selectedId = null, this._detail = null;
	}
	async _refresh(e) {
		let t = this._selectedId;
		if (this.api && t !== null) {
			this._busy = !0;
			try {
				let n = await this.api.refreshDevice(t, e);
				this._detail = n, this._confidence = e ? n.deep_verified ? "confirmed" : "unconfirmed" : "cached", this._error = null, this._linkIndex = [], this._incomingState = "idle", this._loadIncoming();
			} catch (e) {
				this._error = N(this.hass, M.from(e));
			} finally {
				this._busy = !1;
			}
		}
	}
	async _loadIncoming() {
		if (!this.api || this._incomingState === "loading") return;
		if (this._linkIndex.length > 0 || this._incomingState === "ready") {
			this._incoming = this._linkIndex;
			return;
		}
		this._incomingState = "loading";
		let e = this._devices.map((e) => e.device_id).filter((e) => e !== null), t = await Promise.allSettled(e.map((e) => this.api.getDevice(e))), n = [], r = !1;
		for (let e of t) e.status === "fulfilled" ? n.push(...e.value.links) : r = !0;
		this._linkIndex = n, this._incoming = n, this._incomingState = r ? "error" : "ready";
	}
	_isIgnored(e) {
		return this._ignored.has(e.fingerprint);
	}
	async _setIgnored(e, t) {
		if (this.api) {
			this._busy = !0;
			try {
				await this.api.setUnmanagedIgnored([e.fingerprint], t), t ? this._ignored.add(e.fingerprint) : this._ignored.delete(e.fingerprint), this.requestUpdate(), this._error = null;
			} catch (e) {
				this._error = N(this.hass, M.from(e));
			} finally {
				this._busy = !1;
			}
		}
	}
	_planRemoval(e) {
		let t = this._detail?.device.device_id;
		this._planScope = t == null ? void 0 : { device_ids: [t] }, this._planRemove = [e.fingerprint], this._planHeading = `Remove a link from ${this._detail?.device.name ?? "this device"}`, this._planOpen = !0;
	}
	_closePlan() {
		this._planOpen = !1, this._planRemove = [];
	}
	_afterApply() {
		this._load(), this._selectedId !== null && this._select(this._selectedId);
	}
};
P([A()], q.prototype, "_devices", void 0), P([A()], q.prototype, "_detail", void 0), P([A()], q.prototype, "_selectedId", void 0), P([A()], q.prototype, "_search", void 0), P([A()], q.prototype, "_loading", void 0), P([A()], q.prototype, "_busy", void 0), P([A()], q.prototype, "_error", void 0), P([A()], q.prototype, "_confidence", void 0), P([A()], q.prototype, "_incoming", void 0), P([A()], q.prototype, "_incomingState", void 0), P([A()], q.prototype, "_planOpen", void 0), P([A()], q.prototype, "_planScope", void 0), P([A()], q.prototype, "_planRemove", void 0), P([A()], q.prototype, "_planHeading", void 0), q = P([O("device-links-devices")], q);
//#endregion
//#region src/views/overview.ts
var Rt = [
	"blocked",
	"drift",
	"pending",
	"unknown"
], zt = [
	"in_sync",
	"drift",
	"pending",
	"blocked",
	"disabled",
	"unknown"
], J = class extends U {
	constructor(...e) {
		super(...e), this._profile = null, this._rules = [], this._devices = [], this._jobs = [], this._loading = !0, this._error = null, this._verifying = !1, this._verifiedAt = null, this._verifiedDevices = 0, this._planOpen = !1, this._planHeading = "Plan and apply";
	}
	static {
		this.styles = H;
	}
	connectedCallback() {
		super.connectedCallback(), this._load();
	}
	render() {
		return x`
      <div class="content">
        ${this._error === null ? C : x`<div class="notice error" role="alert">${this._error}</div>`}
        ${this._renderHeader()}
        ${this._renderAttention()}
        ${this._renderActivity()}
      </div>
      <dl-plan-dialog
        .hass=${this.hass}
        .api=${this.api}
        .components=${this.components}
        .narrow=${this.narrow}
        .open=${this._planOpen}
        .scope=${this._planScope}
        .heading=${this._planHeading}
        @dl-plan-closed=${this._closePlan}
        @dl-plan-applied=${this._afterApply}
      ></dl-plan-dialog>
    `;
	}
	_renderHeader() {
		let e = this._stateCounts();
		return x`
      <div class="card">
        <div class="spread">
          <div class="grow">
            <h2>${this._profile?.name ?? "No profile is active"}</h2>
            <p class="secondary">
              ${this._profile === null ? "Activate a profile in the Profiles tab, or make one there." : `${V(this._profile.rules, "rule")}, ${this._profile.enabled_rules} enabled.`}
            </p>
            <div class="chips">
              ${zt.map((t) => (e.get(t) ?? 0) === 0 ? C : x`<span class="chip ${wt(t)}" title=${Tt(t)}>
                      ${B(t)} ${e.get(t)}
                    </span>`)}
              ${this._loading ? x`<span class="chip muted">Loading</span>` : this._rules.length === 0 ? x`<span class="chip muted">No rules yet</span>` : C}
            </div>
          </div>
          <div class="row">
            <button type="button" class="outlined" ?disabled=${this._verifying} @click=${this._verify}>
              ${this._verifying ? "Verifying" : "Verify"}
            </button>
            <button type="button" class="primary" @click=${() => this._openPlan()}>
              Plan and apply
            </button>
          </div>
        </div>
        <p class="secondary" style="margin: 12px 0 0">
          ${this._verifiedAt === null ? "Verify reads every device in the active profile and changes nothing." : `Verified ${It(this._verifiedAt)}: ${V(this._verifiedDevices, "device")} re-read.`}
        </p>
      </div>
    `;
	}
	_renderAttention() {
		let e = this._rules.filter((e) => Rt.includes(e.state)), t = this._devices.filter((e) => !e.available);
		return e.length === 0 && t.length === 0 ? x`
        <div class="card">
          <h3>Needs attention</h3>
          <p class="secondary">
            ${this._loading ? "Looking." : "Nothing. Every rule holds what it asks for, and every device answered."}
          </p>
        </div>
      ` : x`
      <div class="card">
        <h3>Needs attention</h3>
        <ul class="list">
          ${e.slice().sort((e, t) => Rt.indexOf(e.state) - Rt.indexOf(t.state)).map((e) => this._renderAttentionRule(e))}
          ${t.length === 0 ? C : x`
                <li>
                  <div class="spread">
                    <div class="grow">
                      <div class="row">
                        <span class="chip warn">Not answering</span>
                        <strong>${V(t.length, "device")}</strong>
                      </div>
                      <p class="secondary" style="margin: 4px 0 0">
                        ${t.map((e) => e.name).join(", ")}. Their links are
                        shown from the last successful read and cannot be confirmed now.
                      </p>
                    </div>
                    <button type="button" class="outlined" @click=${() => this.goTo("devices")}>
                      Open devices
                    </button>
                  </div>
                </li>
              `}
        </ul>
      </div>
    `;
	}
	_renderAttentionRule(e) {
		return x`
      <li>
        <div class="spread">
          <div class="grow">
            <div class="row">
              <span class="chip ${wt(e.state)}">${B(e.state)}</span>
              <strong>${e.rule.name}</strong>
            </div>
            <p class="secondary" style="margin: 4px 0 0">
              ${Tt(e.state)}
              ${e.links_total > 0 ? ` ${e.links_in_sync} of ${e.links_total} links are in place.` : ""}
            </p>
          </div>
          <div class="row">
            <button type="button" class="outlined" @click=${() => this.goTo("rules", e.rule.id)}>
              Open rule
            </button>
            <button
              type="button"
              class="primary"
              @click=${() => this._openPlan({ rule_ids: [e.rule.id] }, e.rule.name)}
            >
              Plan
            </button>
          </div>
        </div>
      </li>
    `;
	}
	_renderActivity() {
		return x`
      <div class="card">
        <div class="spread">
          <h3>Recent activity</h3>
          <button type="button" class="link" @click=${() => this.goTo("activity")}>
            See all
          </button>
        </div>
        ${this._jobs.length === 0 ? x`<p class="secondary">Nothing has been applied yet.</p>` : x`
              <ul class="list">
                ${this._jobs.slice(0, 5).map((e) => x`
                    <li>
                      <button
                        type="button"
                        class="selectable"
                        @click=${() => this.goTo("activity", e.id)}
                      >
                        <span class="row">
                          <span class="chip ${Dt(e.status)}">
                            ${Et(e.status)}
                          </span>
                          <span class="grow truncate">${e.scope}</span>
                          <span class="secondary">${V(e.total, "link")}</span>
                          <span class="secondary">${Ft(e.created_at, this.hass?.language)}</span>
                        </span>
                      </button>
                    </li>
                  `)}
              </ul>
            `}
      </div>
    `;
	}
	async _load() {
		if (this.api) {
			this._loading = !0;
			try {
				let [e, t, n] = await Promise.all([
					this.api.listProfiles(),
					this.api.listJobs(),
					this.api.listDevices()
				]);
				this._jobs = t.jobs ?? [], this._devices = n ?? [];
				let r = (e.profiles ?? []).find((e) => e.is_active) ?? null;
				this._profile = r, this._rules = r === null ? [] : (await this.api.getProfile(r.id)).rules ?? [], this._error = null;
			} catch (e) {
				this._error = N(this.hass, M.from(e));
			} finally {
				this._loading = !1;
			}
		}
	}
	_stateCounts() {
		let e = /* @__PURE__ */ new Map();
		for (let t of this._rules) e.set(t.state, (e.get(t.state) ?? 0) + 1);
		return e;
	}
	async _verify() {
		if (this.api) {
			this._verifying = !0, this._error = null;
			try {
				let e = await this.api.verify();
				this._verifiedDevices = e.devices, this._verifiedAt = (/* @__PURE__ */ new Date()).toISOString(), await this._load();
			} catch (e) {
				this._error = N(this.hass, M.from(e));
			} finally {
				this._verifying = !1;
			}
		}
	}
	_openPlan(e, t) {
		this._planScope = e, this._planHeading = t === void 0 ? "Plan and apply" : `Plan and apply: ${t}`, this._planOpen = !0;
	}
	_closePlan() {
		this._planOpen = !1, this._load();
	}
	_afterApply() {
		this._load();
	}
};
P([A()], J.prototype, "_profile", void 0), P([A()], J.prototype, "_rules", void 0), P([A()], J.prototype, "_devices", void 0), P([A()], J.prototype, "_jobs", void 0), P([A()], J.prototype, "_loading", void 0), P([A()], J.prototype, "_error", void 0), P([A()], J.prototype, "_verifying", void 0), P([A()], J.prototype, "_verifiedAt", void 0), P([A()], J.prototype, "_verifiedDevices", void 0), P([A()], J.prototype, "_planOpen", void 0), P([A()], J.prototype, "_planScope", void 0), P([A()], J.prototype, "_planHeading", void 0), J = P([O("device-links-overview")], J);
//#endregion
//#region src/views/profiles.ts
var Y = class extends U {
	constructor(...e) {
		super(...e), this._profiles = [], this._loading = !0, this._busy = !1, this._error = null, this._sheet = "none", this._subject = null, this._text = "", this._exported = "", this._planOpen = !1, this._plan = null, this._planHeading = "Plan and apply";
	}
	static {
		this.styles = H;
	}
	connectedCallback() {
		super.connectedCallback(), this._load();
	}
	render() {
		return x`
      <div class="content">
        ${this._error === null ? C : x`<div class="notice error" role="alert">${this._error}</div>`}
        <div class="card">
          <div class="spread">
            <div class="grow">
              <h2>Profiles</h2>
              <p class="secondary">
                One profile is in force at a time. The others are kept as they are, and
                nothing they say reaches a device until you activate them and apply.
              </p>
            </div>
            <div class="row">
              <button type="button" class="outlined" @click=${() => this._open("import")}>
                Import
              </button>
              <button type="button" class="primary" @click=${() => this._open("create")}>
                New profile
              </button>
            </div>
          </div>
          ${this._renderList()}
        </div>
      </div>
      ${this._renderSheets()}
      <dl-plan-dialog
        .hass=${this.hass}
        .api=${this.api}
        .components=${this.components}
        .narrow=${this.narrow}
        .open=${this._planOpen}
        .initialPlan=${this._plan}
        .heading=${this._planHeading}
        @dl-plan-closed=${this._closePlan}
        @dl-plan-applied=${this._afterApply}
      ></dl-plan-dialog>
    `;
	}
	_renderList() {
		return this._loading ? x`<p class="secondary">Loading.</p>` : this._profiles.length === 0 ? x`<p class="empty">No profiles yet.</p>` : x`
      <ul class="list">
        ${this._profiles.map((e) => this._renderRow(e))}
      </ul>
    `;
	}
	_renderRow(e) {
		return x`
      <li>
        <div class="spread">
          <div class="grow">
            <div class="row">
              <strong>${e.name}</strong>
              ${e.is_active ? x`<span class="chip ok">Active</span>` : C}
            </div>
            <p class="secondary" style="margin: 4px 0 0">
              ${V(e.rules, "rule")}, ${e.enabled_rules} enabled.
            </p>
          </div>
          <div class="row">
            ${e.is_active ? x`<button type="button" class="outlined" @click=${() => this.goTo("rules")}>
                  Open rules
                </button>` : x`<button
                  type="button"
                  class="primary"
                  ?disabled=${this._busy}
                  @click=${() => this._activate(e)}
                >
                  Activate
                </button>`}
            <button
              type="button"
              class="outlined"
              ?disabled=${this._busy}
              @click=${() => this._duplicate(e)}
            >
              Duplicate
            </button>
            <button
              type="button"
              class="outlined"
              ?disabled=${this._busy}
              @click=${() => this._export(e)}
            >
              Export
            </button>
            <button type="button" class="danger" @click=${() => this._open("delete", e)}>
              Delete
            </button>
          </div>
        </div>
      </li>
    `;
	}
	_renderSheets() {
		return x`
      <dl-dialog
        .open=${this._sheet === "create"}
        .narrow=${this.narrow}
        heading="New profile"
        @dl-dialog-closed=${this._closeSheet}
      >
        <label class="field">
          <span>Name</span>
          <input
            type="text"
            .value=${this._text}
            @input=${(e) => {
			this._text = e.target.value;
		}}
          />
        </label>
        <p class="secondary">
          A new profile starts empty and is not activated. Nothing changes on any device.
        </p>
        <div slot="actions">
          <button type="button" class="outlined" @click=${this._closeSheet}>Cancel</button>
          <button
            type="button"
            class="primary"
            ?disabled=${this._text.trim() === "" || this._busy}
            @click=${this._create}
          >
            Create
          </button>
        </div>
      </dl-dialog>

      <dl-dialog
        .open=${this._sheet === "import"}
        .narrow=${this.narrow}
        heading="Import a profile"
        @dl-dialog-closed=${this._closeSheet}
      >
        <p class="secondary">
          Paste the YAML of a profile. It is stored and nothing is written to a device. If
          it names devices this network does not have, the import is refused whole rather
          than half done.
        </p>
        <textarea
          .value=${this._text}
          aria-label="Profile YAML"
          @input=${(e) => {
			this._text = e.target.value;
		}}
        ></textarea>
        <div slot="actions">
          <button type="button" class="outlined" @click=${this._closeSheet}>Cancel</button>
          <button
            type="button"
            class="primary"
            ?disabled=${this._text.trim() === "" || this._busy}
            @click=${this._import}
          >
            Import
          </button>
        </div>
      </dl-dialog>

      <dl-dialog
        .open=${this._sheet === "export"}
        .narrow=${this.narrow}
        .heading=${`Export ${this._subject?.name ?? ""}`}
        @dl-dialog-closed=${this._closeSheet}
      >
        <p class="secondary">This is the file this profile would be kept as.</p>
        <textarea readonly aria-label="Exported YAML" .value=${this._exported}></textarea>
        <div slot="actions">
          <button type="button" class="outlined" @click=${this._closeSheet}>Close</button>
          <button type="button" class="primary" @click=${this._copyExport}>Copy</button>
        </div>
      </dl-dialog>

      <dl-dialog
        .open=${this._sheet === "delete"}
        .narrow=${this.narrow}
        .heading=${`Delete ${this._subject?.name ?? ""}?`}
        @dl-dialog-closed=${this._closeSheet}
      >
        <p>
          The profile and its rules are removed from Device Links. Whatever those rules
          already wrote stays on the devices and becomes unmanaged, so nothing in your house
          changes when you press this.
        </p>
        <div slot="actions">
          <button type="button" class="outlined" @click=${this._closeSheet}>Cancel</button>
          <button type="button" class="danger" @click=${this._delete}>Delete the profile</button>
        </div>
      </dl-dialog>
    `;
	}
	async _load() {
		if (this.api) {
			this._loading = !0;
			try {
				this._profiles = (await this.api.listProfiles()).profiles ?? [], this._error = null;
			} catch (e) {
				this._error = N(this.hass, M.from(e));
			} finally {
				this._loading = !1;
			}
		}
	}
	_open(e, t = null) {
		this._sheet = e, this._subject = t, this._text = "";
	}
	_closeSheet() {
		this._sheet = "none", this._subject = null, this._text = "";
	}
	async _run(e) {
		this._busy = !0, this._error = null;
		try {
			await e();
		} catch (e) {
			this._error = N(this.hass, M.from(e));
		} finally {
			this._busy = !1;
		}
	}
	async _create() {
		let e = this._text.trim();
		await this._run(async () => {
			await this.api.createProfile({
				id: Bt(),
				name: e,
				rules: []
			}), this._closeSheet(), await this._load();
		});
	}
	async _duplicate(e) {
		await this._run(async () => {
			await this.api.duplicateProfile(e.id), await this._load();
		});
	}
	async _export(e) {
		await this._run(async () => {
			let t = await this.api.exportProfile(e.id);
			this._exported = t.yaml, this._subject = e, this._sheet = "export";
		});
	}
	_copyExport() {
		navigator.clipboard?.writeText(this._exported).catch(() => void 0);
	}
	async _import() {
		let e = this._text;
		await this._run(async () => {
			let t = await this.api.importProfile(e);
			this._closeSheet(), await this._load(), t.plan !== void 0 && (this._plan = t.plan, this._planHeading = `Plan and apply: ${t.profile.name}`, this._planOpen = !0);
		});
	}
	async _activate(e) {
		await this._run(async () => {
			let t = await this.api.activateProfile(e.id);
			await this._load(), this._plan = t.plan, this._planHeading = `Plan and apply: ${e.name}`, this._planOpen = !0;
		});
	}
	async _delete() {
		let e = this._subject;
		e !== null && await this._run(async () => {
			await this.api.deleteProfile(e.id), this._closeSheet(), await this._load();
		});
	}
	_closePlan() {
		this._planOpen = !1, this._plan = null, this._load();
	}
	_afterApply() {
		this._load();
	}
};
P([A()], Y.prototype, "_profiles", void 0), P([A()], Y.prototype, "_loading", void 0), P([A()], Y.prototype, "_busy", void 0), P([A()], Y.prototype, "_error", void 0), P([A()], Y.prototype, "_sheet", void 0), P([A()], Y.prototype, "_subject", void 0), P([A()], Y.prototype, "_text", void 0), P([A()], Y.prototype, "_exported", void 0), P([A()], Y.prototype, "_planOpen", void 0), P([A()], Y.prototype, "_plan", void 0), P([A()], Y.prototype, "_planHeading", void 0), Y = P([O("device-links-profiles")], Y);
function Bt() {
	let e = globalThis.crypto?.randomUUID?.();
	return e ? e.replace(/-/g, "") : `profile${Date.now().toString(36)}`;
}
//#endregion
//#region src/dialogs/rule-editor.ts
var X = [
	"template",
	"source",
	"targets",
	"behaviour",
	"review"
], Vt = {
	template: "What should this do?",
	source: "Which control drives it?",
	targets: "What should it control?",
	behaviour: "How should it behave?",
	review: "What this will do"
}, Ht = [
	"on_off",
	"level_set",
	"level_hold",
	"scene",
	"color",
	"status_report"
], Ut = {
	remote: {
		features: [
			"on_off",
			"level_set",
			"level_hold"
		],
		direction: "one_way",
		mirror: "leave"
	},
	virtual_3way: {
		features: [
			"on_off",
			"level_set",
			"level_hold"
		],
		direction: "two_way",
		mirror: "leave"
	},
	scene_button: {
		features: ["on_off"],
		direction: "one_way",
		mirror: "leave"
	},
	off_all: {
		features: ["on_off"],
		direction: "one_way",
		mirror: "off"
	},
	status_feedback: {
		features: ["status_report"],
		direction: "one_way",
		mirror: "leave"
	},
	custom: {
		features: ["on_off"],
		direction: "one_way",
		mirror: "leave"
	}
}, Wt = [
	{
		value: "leave",
		label: "Leave the device's own setting alone",
		help: "Device Links writes no parameter. Choose this unless you know you want the other two."
	},
	{
		value: "on",
		label: "Make the control's own load follow the press",
		help: "Writes the device's mirror setting so its own load responds as well as the targets."
	},
	{
		value: "off",
		label: "Leave the control's own load out of it",
		help: "Writes the device's mirror setting so only the targets respond."
	}
], Z = class extends D {
	constructor(...e) {
		super(...e), this.components = null, this.narrow = !1, this.open = !1, this.devices = [], this.rule = null, this.initialTemplate = null, this._draft = null, this._step = "template", this._sourceDetail = null, this._loadingSource = !1, this._compiled = null, this._validating = !1, this._saving = !1, this._error = null, this._search = "";
	}
	static {
		this.styles = [H, o`
      .steps {
        display: flex;
        gap: 4px;
        flex-wrap: wrap;
        margin-bottom: 12px;
      }

      .steps > li {
        list-style: none;
        font-size: 12px;
        color: var(--secondary-text-color, #727272);
        padding: 2px 8px;
        border-radius: 12px;
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      }

      .steps > li[aria-current="step"] {
        color: var(--primary-color, #03a9f4);
        border-color: var(--primary-color, #03a9f4);
      }

      .template-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 8px;
      }

      .template-card {
        text-align: left;
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        border-radius: 8px;
        padding: 12px;
        color: inherit;
        min-height: 0;
      }

      .template-card[aria-pressed="true"] {
        border-color: var(--primary-color, #03a9f4);
        background: var(--secondary-background-color, #f5f5f5);
      }

      .template-card strong {
        display: block;
        margin-bottom: 4px;
      }

      .picker {
        max-height: 320px;
        overflow-y: auto;
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        border-radius: 8px;
        padding: 4px;
      }

      .emitter {
        color: var(--primary-text-color, #212121);
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        border-radius: 8px;
        padding: 8px 10px;
        margin-bottom: 6px;
      }

      .emitter[aria-pressed="true"] {
        border-color: var(--primary-color, #03a9f4);
        background: var(--secondary-background-color, #f5f5f5);
      }

      ha-icon {
        --mdc-icon-size: 16px;
      }
    `];
	}
	willUpdate(e) {
		e.has("open") && this.open && this._begin();
	}
	disconnectedCallback() {
		super.disconnectedCallback(), clearTimeout(this._validateTimer);
	}
	render() {
		return x`
      <dl-dialog
        .open=${this.open}
        .narrow=${this.narrow}
        .heading=${this.rule === null ? "New rule" : `Edit ${this.rule.name}`}
        @dl-dialog-closed=${this._close}
      >
        ${this._renderStepper()}
        <div slot="actions">${this._renderActions()}</div>
      </dl-dialog>
    `;
	}
	_renderStepper() {
		let e = this._draft;
		if (e === null) return x`<p class="secondary">Loading.</p>`;
		let t = X.indexOf(this._step);
		return x`
      ${this.narrow ? x`<p class="secondary">
            Step ${t + 1} of ${X.length}: ${Vt[this._step]}
          </p>` : x`<ol class="steps">
            ${X.map((e, t) => x`
                <li aria-current=${e === this._step ? "step" : "false"}>
                  ${t + 1}. ${Vt[e]}
                </li>
              `)}
          </ol>`}
      ${this._error === null ? C : x`<div class="notice error" role="alert">${this._error}</div>`}
      ${this._renderStep(e)}
    `;
	}
	_renderStep(e) {
		switch (this._step) {
			case "template": return this._renderTemplateStep(e);
			case "source": return this._renderSourceStep(e);
			case "targets": return this._renderTargetsStep(e);
			case "behaviour": return this._renderBehaviourStep(e);
			default: return this._renderReviewStep(e);
		}
	}
	_renderTemplateStep(e) {
		return x`
      <div class="template-grid">
        ${Object.keys(Ut).map((t) => x`
            <button
              type="button"
              class="template-card"
              aria-pressed=${e.template === t ? "true" : "false"}
              @click=${() => this._chooseTemplate(t)}
            >
              <strong>${z(t)}</strong>
              <span class="secondary">${Ct(t)}</span>
            </button>
          `)}
      </div>
    `;
	}
	_chooseTemplate(e) {
		let t = Ut[e];
		this._update({
			template: e,
			features: [...t.features],
			direction: t.direction,
			mirror_source: t.mirror,
			name: this._draft?.name || z(e)
		}), this._step = "source";
	}
	_renderSourceStep(e) {
		let t = this._deviceFor(e.source.device);
		return t === null ? x`
        ${this._renderSearch()}
        <div class="picker">${this._renderDeviceList(this._sourceCandidates(), (e) => this._chooseSource(e))}</div>
      ` : x`
      <div class="row" style="margin-bottom: 12px">
        <strong>${t.name}</strong>
        <span class="chip muted">${R(t.backend)}</span>
        <button type="button" class="link" @click=${() => this._clearSource()}>
          Choose a different device
        </button>
      </div>
      ${this._loadingSource ? x`<p class="secondary">Reading what this device offers.</p>` : this._renderEmitters(e)}
    `;
	}
	_renderEmitters(e) {
		let t = this._sourceDetail?.emitters ?? [];
		return t.length === 0 ? x`<p class="secondary">
        This device reports no controls that can drive another device.
      </p>` : x`
      <div>
        ${t.map((t) => this._renderEmitter(e, t))}
      </div>
    `;
	}
	_renderEmitter(e, t) {
		if (t.is_lifeline) return x`
        <div class="emitter unavailable">
          <div class="row">
            <strong>${t.label}</strong>
            <span class="chip muted">System link</span>
          </div>
          <p class="secondary" style="margin: 4px 0 0">
            This is the device's lifeline, which is how it reports to Home Assistant.
            Device Links never writes to it.
          </p>
        </div>
      `;
		let n = this._usage(t), r = e.source.emitter_id === t.emitter_id, i = Object.keys(t.actions);
		return x`
      <button
        type="button"
        class="emitter"
        aria-pressed=${r ? "true" : "false"}
        @click=${() => this._chooseEmitter(t)}
      >
        <div class="row">
          <strong>${t.label}</strong>
          ${n === null ? C : x`<span class="chip ${n.free === 0 ? "warn" : "muted"}">
                ${n.used} of ${n.capacity} used in group ${n.group}
              </span>`}
          ${t.semantics === "unknown" ? x`<span class="chip warn">Unverified</span>` : C}
        </div>
        <div class="chips" style="margin-top: 6px">
          ${i.map((e) => x`<span class="chip">
              ${Lt(this.components, St(e))}${L(e)}
            </span>`)}
        </div>
        ${n !== null && n.free === 0 ? x`<p class="secondary" style="margin: 6px 0 0">
              This group is full. Anything added here is blocked until an entry comes off it.
            </p>` : C}
      </button>
    `;
	}
	_usage(e) {
		return At(e, this._sourceDetail?.links ?? []);
	}
	_sourceCandidates() {
		return this._filtered(this.devices.filter((e) => e.emitters > 0 && e.device_id !== null));
	}
	_chooseSource(e) {
		this._update({
			backend: e.backend,
			source: {
				device: e.identity,
				endpoint: null,
				emitter_id: ""
			}
		}), this._sourceDetail = null, this._loadSource(e);
	}
	_clearSource() {
		this._update({ source: {
			device: "",
			endpoint: null,
			emitter_id: ""
		} }), this._sourceDetail = null;
	}
	async _loadSource(e) {
		if (this.api && e.device_id !== null) {
			this._loadingSource = !0;
			try {
				this._sourceDetail = await this.api.getDevice(e.device_id);
			} catch (e) {
				this._error = N(this.hass, M.from(e));
			} finally {
				this._loadingSource = !1;
			}
		}
	}
	_chooseEmitter(e) {
		let t = this._draft;
		if (t === null) return;
		let n = Object.keys(e.actions), r = t.features.filter((e) => n.includes(e));
		this._update({
			source: {
				...t.source,
				emitter_id: e.emitter_id
			},
			features: r.length ? r : n.slice(0, 1)
		});
	}
	_renderTargetsStep(e) {
		let t = new Set(e.targets.map((e) => e.device)), n = this._filtered(this.devices.filter((t) => t.identity !== e.source.device)), r = this._selectedEmitter(e), i = r === null ? null : this._usage(r);
		return x`
      ${i !== null && t.size > i.free ? x`<div class="notice warn">
            <p>
              ${V(i.free, "entry", "entries")} free in group ${i.group}, and
              ${V(t.size, "target")} chosen. The ones that do not fit are blocked
              rather than written, and the plan will say which.
            </p>
          </div>` : C}
      ${this._renderSearch()}
      <div class="picker">
        <ul class="list">
          ${n.map((e) => x`
              <li>
                <label class="choice">
                  <input
                    type="checkbox"
                    .checked=${t.has(e.identity)}
                    @change=${(t) => this._toggleTarget(e, t)}
                  />
                  <span class="grow">
                    <span>${e.name}</span>
                    <span class="chip muted">${R(e.backend)}</span>
                    ${e.available ? C : x`<span class="chip warn">Not answering</span>`}
                    ${e.is_long_range ? x`<span class="chip error">Long Range</span>` : C}
                  </span>
                </label>
              </li>
            `)}
        </ul>
        ${n.length === 0 ? x`<p class="empty">No device matches that search.</p>` : C}
      </div>
    `;
	}
	_toggleTarget(e, t) {
		let n = this._draft;
		if (n === null) return;
		let r = t.target.checked, i = n.targets.filter((t) => t.device !== e.identity);
		r && i.push({
			device: e.identity,
			endpoint: null
		}), this._update({ targets: i });
	}
	_renderBehaviourStep(e) {
		let t = this._selectedEmitter(e), n = t?.actions ?? {};
		return x`
      <label class="field" style="margin-bottom: 16px">
        <span>Name</span>
        <input
          type="text"
          .value=${e.name}
          @input=${(e) => this._update({ name: e.target.value })}
        />
      </label>

      <h3>What it sends</h3>
      ${Ht.map((r) => {
			let i = n[r], a = i !== void 0;
			return x`
          <label class="choice ${a ? "" : "disabled"}">
            <input
              type="checkbox"
              .checked=${e.features.includes(r)}
              ?disabled=${!a}
              @change=${(e) => this._toggleFeature(r, e)}
            />
            <span>
              <span>${L(r)}</span>
              ${a ? x`<span class="secondary"> (group ${i})</span>` : x`<span class="secondary">
                    ${t === null ? " (choose a control first)" : ` (${t.label} does not send this)`}
                  </span>`}
            </span>
          </label>
        `;
		})}

      <h3 style="margin-top: 16px">Direction</h3>
      <label class="choice">
        <input
          type="radio"
          name="direction"
          .checked=${e.direction === "one_way"}
          @change=${() => this._update({ direction: "one_way" })}
        />
        <span>One way. The control drives the targets.</span>
      </label>
      <label class="choice">
        <input
          type="radio"
          name="direction"
          .checked=${e.direction === "two_way"}
          @change=${() => this._update({ direction: "two_way" })}
        />
        <span>
          Two way. Each target also drives the control, using the first control on it that
          carries the same features.
        </span>
      </label>

      <h3 style="margin-top: 16px">The control's own load</h3>
      ${Wt.map((t) => x`
          <label class="choice">
            <input
              type="radio"
              name="mirror"
              .checked=${e.mirror_source === t.value}
              @change=${() => this._update({ mirror_source: t.value })}
            />
            <span>
              <span>${t.label}</span>
              <span class="secondary" style="display: block">${t.help}</span>
            </span>
          </label>
        `)}
      ${this._renderSettingPreview()}
    `;
	}
	_renderSettingPreview() {
		let e = this._compiled?.settings ?? [];
		return e.length === 0 ? C : x`
      <div class="notice">
        ${e.map((e) => x`<p>
            This writes parameter ${e.parameter}
            ${e.bitmask === null ? "" : `(bitmask ${e.bitmask})`} on the control
            to ${e.value}.
          </p>`)}
      </div>
    `;
	}
	_toggleFeature(e, t) {
		let n = this._draft;
		if (n === null) return;
		let r = t.target.checked, i = n.features.filter((t) => t !== e);
		r && i.push(e), this._update({ features: i });
	}
	_renderReviewStep(e) {
		let t = this._compiled;
		return x`
      <div class="notice">
        <p>
          <strong>${e.name}</strong>, ${z(e.template)}, from
          ${this._nameOf(e.source.device)} to
          ${e.targets.map((e) => this._nameOf(e.device)).join(", ") || "nothing yet"}.
        </p>
      </div>
      ${this._validating ? x`<p class="secondary">Compiling.</p>` : C}
      ${t === null ? C : this._renderDiagnostics(t)}
      ${t === null ? C : this._renderCompiled(t)}
    `;
	}
	_renderDiagnostics(e) {
		return x`
      ${e.errors.map((e) => x`<div class="notice error" role="alert">
          <p><strong>Problem.</strong> ${Ze(this.hass, e)}</p>
        </div>`)}
      ${e.warnings.map((e) => x`<div class="notice warn" role="status">
          <p><strong>Warning.</strong> ${Ze(this.hass, e)}</p>
        </div>`)}
      ${e.errors.length > 0 ? x`<p class="secondary">
            This rule compiles to no links, so there is nothing to apply. You can still save
            it: it will show as blocked in the rules table until whatever is wrong is fixed.
          </p>` : C}
    `;
	}
	_renderCompiled(e) {
		return e.links.length === 0 ? x`<p>No links.</p>` : x`
      <h3>${V(e.links.length, "link")}</h3>
      <ul class="list">
        ${e.links.map((e) => x`<li>${Mt(e)}</li>`)}
      </ul>
      ${e.settings.length === 0 ? C : x`
            <h3 style="margin-top: 12px">Device settings</h3>
            <ul class="list">
              ${e.settings.map((e) => x`<li>
                  ${e.capability}: parameter ${e.parameter}
                  ${e.bitmask === null ? "" : `(bitmask ${e.bitmask})`} set to
                  ${e.value}
                </li>`)}
            </ul>
          `}
    `;
	}
	_renderSearch() {
		return x`
      <label class="field" style="margin-bottom: 8px">
        <span>Search devices</span>
        <input
          type="search"
          .value=${this._search}
          @input=${(e) => {
			this._search = e.target.value;
		}}
        />
      </label>
    `;
	}
	_renderDeviceList(e, t) {
		return e.length === 0 ? x`<p class="empty">No device matches that search.</p>` : x`
      <ul class="list">
        ${e.map((e) => x`
            <li>
              <button type="button" class="selectable" @click=${() => t(e)}>
                <span class="row">
                  <span class="grow">${e.name}</span>
                  <span class="chip muted">${R(e.backend)}</span>
                  <span class="chip muted">${V(e.emitters, "control")}</span>
                  ${e.available ? C : x`<span class="chip warn">Not answering</span>`}
                </span>
              </button>
            </li>
          `)}
      </ul>
    `;
	}
	_filtered(e) {
		let t = this._search.trim().toLowerCase();
		return t ? e.filter((e) => `${e.name} ${e.protocol_id}`.toLowerCase().includes(t)) : e;
	}
	_deviceFor(e) {
		return this.devices.find((t) => t.identity === e) ?? null;
	}
	_nameOf(e) {
		return this._deviceFor(e)?.name ?? e;
	}
	_selectedEmitter(e) {
		return this._sourceDetail?.emitters.find((t) => t.emitter_id === e.source.emitter_id) ?? null;
	}
	_renderActions() {
		let e = this._draft, t = X.indexOf(this._step);
		if (e === null) return x`<button type="button" class="outlined" @click=${this._close}>Close</button>`;
		if (this._step === "review") {
			let e = (this._compiled?.errors.length ?? 0) > 0;
			return x`
        <button type="button" class="outlined" @click=${() => this._goTo(t - 1)}>Back</button>
        <button type="button" class="outlined" ?disabled=${this._saving} @click=${() => this._save(!1)}>
          ${e ? "Save anyway" : "Save"}
        </button>
        <button
          type="button"
          class="primary"
          ?disabled=${this._saving || e}
          title=${e ? "This rule compiles to no links, so there is nothing to apply." : ""}
          @click=${() => this._save(!0)}
        >
          Save and apply
        </button>
      `;
		}
		return x`
      <button type="button" class="outlined" @click=${this._close}>Cancel</button>
      ${t === 0 ? C : x`<button type="button" class="outlined" @click=${() => this._goTo(t - 1)}>
            Back
          </button>`}
      <button
        type="button"
        class="primary"
        ?disabled=${!this._canLeave(this._step, e)}
        @click=${() => this._goTo(t + 1)}
      >
        Next
      </button>
    `;
	}
	_canLeave(e, t) {
		switch (e) {
			case "template": return !0;
			case "source": return t.source.device !== "" && t.source.emitter_id !== "";
			case "targets": return t.targets.length > 0;
			case "behaviour": return t.features.length > 0 && t.name.trim() !== "";
			default: return !0;
		}
	}
	_goTo(e) {
		let t = X[Math.min(Math.max(e, 0), X.length - 1)];
		t !== void 0 && (this._step = t, t === "review" && this._validate());
	}
	_begin() {
		if (this._error = null, this._compiled = null, this._search = "", this._sourceDetail = null, this.rule === null) {
			let e = this.initialTemplate ?? "remote", t = Ut[e];
			this._draft = {
				id: Gt(),
				name: this.initialTemplate === null ? "" : z(e),
				template: e,
				backend: "zwave",
				enabled: !0,
				direction: t.direction,
				mirror_source: t.mirror,
				features: [...t.features],
				source: {
					device: "",
					endpoint: null,
					emitter_id: ""
				},
				targets: []
			}, this._step = "template";
			return;
		}
		this._draft = {
			...this.rule,
			features: [...this.rule.features],
			targets: [...this.rule.targets]
		}, this._step = "template";
		let e = this._deviceFor(this.rule.source.device);
		e !== null && this._loadSource(e).then(() => this._validate());
	}
	_update(e) {
		this._draft !== null && (this._draft = {
			...this._draft,
			...e
		}, this._scheduleValidate());
	}
	_scheduleValidate() {
		clearTimeout(this._validateTimer), this._validateTimer = setTimeout(() => this._validate(), 300);
	}
	_validate() {
		let e = this._draft;
		if (this.api && e !== null) {
			if (e.source.device === "" || e.source.emitter_id === "" || !e.targets.length) {
				this._compiled = null;
				return;
			}
			this._validating = !0, this.api.validateRule(e).then((e) => {
				this._compiled = e, this._error = null;
			}).catch((e) => {
				this._error = N(this.hass, M.from(e));
			}).finally(() => {
				this._validating = !1;
			});
		}
	}
	async _save(e) {
		let t = this._draft;
		if (this.api && t !== null) {
			this._saving = !0, this._error = null;
			try {
				await this.api.upsertRule(t, this.profileId), this.dispatchEvent(new CustomEvent("dl-rule-saved", {
					detail: {
						rule: t,
						apply: e
					},
					bubbles: !0,
					composed: !0
				}));
			} catch (e) {
				this._error = N(this.hass, M.from(e));
			} finally {
				this._saving = !1;
			}
		}
	}
	_close() {
		this.dispatchEvent(new CustomEvent("dl-editor-closed", {
			bubbles: !0,
			composed: !0
		}));
	}
};
P([k({ attribute: !1 })], Z.prototype, "hass", void 0), P([k({ attribute: !1 })], Z.prototype, "api", void 0), P([k({ attribute: !1 })], Z.prototype, "components", void 0), P([k({ type: Boolean })], Z.prototype, "narrow", void 0), P([k({ type: Boolean })], Z.prototype, "open", void 0), P([k({ attribute: !1 })], Z.prototype, "devices", void 0), P([k({ attribute: !1 })], Z.prototype, "rule", void 0), P([k({ type: String })], Z.prototype, "profileId", void 0), P([k({ attribute: !1 })], Z.prototype, "initialTemplate", void 0), P([A()], Z.prototype, "_draft", void 0), P([A()], Z.prototype, "_step", void 0), P([A()], Z.prototype, "_sourceDetail", void 0), P([A()], Z.prototype, "_loadingSource", void 0), P([A()], Z.prototype, "_compiled", void 0), P([A()], Z.prototype, "_validating", void 0), P([A()], Z.prototype, "_saving", void 0), P([A()], Z.prototype, "_error", void 0), P([A()], Z.prototype, "_search", void 0), Z = P([O("dl-rule-editor")], Z);
function Gt() {
	let e = globalThis.crypto?.randomUUID?.();
	return e ? e.replace(/-/g, "") : `rule${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
}
//#endregion
//#region src/views/rules.ts
var Kt = [
	"remote",
	"virtual_3way",
	"scene_button",
	"off_all",
	"status_feedback",
	"custom"
], qt = [
	"in_sync",
	"drift",
	"pending",
	"blocked",
	"disabled",
	"unknown"
], Q = class extends U {
	constructor(...e) {
		super(...e), this._profile = null, this._rules = [], this._devices = [], this._templates = [...Kt], this._emitterLabels = {}, this._loading = !0, this._error = null, this._search = "", this._backendFilter = "", this._stateFilter = "", this._editorOpen = !1, this._editing = null, this._editorTemplate = null, this._planOpen = !1, this._planHeading = "Plan and apply", this._confirmDelete = null, this._staged = null, this._appliedDuringPlan = !1;
	}
	static {
		this.styles = H;
	}
	connectedCallback() {
		super.connectedCallback(), this._load();
	}
	willUpdate(e) {
		if (e.has("selected") && this.selected !== null) {
			this._search = "";
			let e = this.selected, t = this._rules.find((t) => t.rule.id === e);
			t !== void 0 && this._openEditor(t.rule);
		}
	}
	render() {
		return x`
      <div class="content">
        ${this._error === null ? C : x`<div class="notice error" role="alert">${this._error}</div>`}
        <div class="card">
          ${this._renderToolbar()}
          ${this._renderBody()}
        </div>
      </div>
      ${this._renderDeleteConfirm()}
      <dl-rule-editor
        .hass=${this.hass}
        .api=${this.api}
        .components=${this.components}
        .narrow=${this.narrow}
        .open=${this._editorOpen}
        .devices=${this._devices}
        .rule=${this._editing}
        .initialTemplate=${this._editorTemplate}
        @dl-editor-closed=${this._closeEditor}
        @dl-rule-saved=${this._onSaved}
      ></dl-rule-editor>
      <dl-plan-dialog
        .hass=${this.hass}
        .api=${this.api}
        .components=${this.components}
        .narrow=${this.narrow}
        .open=${this._planOpen}
        .scope=${this._planScope}
        .heading=${this._planHeading}
        @dl-plan-closed=${this._closePlan}
        @dl-plan-applied=${this._afterApply}
      ></dl-plan-dialog>
    `;
	}
	_renderToolbar() {
		return x`
      <div class="spread">
        <div class="grow">
          <h2>Rules</h2>
          <p class="secondary">
            ${this._profile === null ? "No profile is active, so no rule is in force." : `In ${this._profile.name}. ${V(this._rules.length, "rule")}.`}
          </p>
        </div>
        <button type="button" class="primary" @click=${() => this._openEditor(null)}>
          New rule
        </button>
      </div>
      <div class="toolbar">
        <label class="field grow">
          <span>Search</span>
          <input
            type="search"
            .value=${this._search}
            placeholder="Rule, device or target"
            @input=${(e) => {
			this._search = e.target.value;
		}}
          />
        </label>
        <label class="field">
          <span>Protocol</span>
          <select
            .value=${this._backendFilter}
            @change=${(e) => {
			this._backendFilter = e.target.value;
		}}
          >
            <option value="">Any</option>
            <option value="zwave">Z-Wave</option>
            <option value="zigbee2mqtt">Zigbee</option>
            <option value="matter">Matter</option>
          </select>
        </label>
        <label class="field">
          <span>Status</span>
          <select
            .value=${this._stateFilter}
            @change=${(e) => {
			this._stateFilter = e.target.value;
		}}
          >
            <option value="">Any</option>
            ${qt.map((e) => x`<option value=${e}>${B(e)}</option>`)}
          </select>
        </label>
      </div>
    `;
	}
	_renderBody() {
		if (this._loading) return x`<p class="secondary">Loading.</p>`;
		if (this._rules.length === 0) return this._renderEmpty();
		let e = this._filtered();
		return e.length === 0 ? x`<p class="empty">No rule matches those filters.</p>` : this.narrow ? x`<ul class="list">${e.map((e) => this._renderCard(e))}</ul>` : x`
      <div class="scroll-x">
        <table>
          <thead>
            <tr>
              <th>Rule</th>
              <th>Source</th>
              <th>Targets</th>
              <th>Sends</th>
              <th>Status</th>
              <th>On</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            ${e.map((e) => this._renderRow(e))}
          </tbody>
        </table>
      </div>
    `;
	}
	_renderCard(e) {
		let t = e.rule;
		return x`
      <li>
        <div class="row">
          <strong class="grow">${t.name}</strong>
          <span class="chip ${wt(e.state)}" title=${Tt(e.state)}>
            ${B(e.state)}
          </span>
        </div>
        <p class="secondary" style="margin: 4px 0">
          ${this._nameOf(t.source.device)},
          ${this._emitterLabel(t.source.device, t.source.emitter_id)} to
          ${t.targets.map((e) => this._nameOf(e.device)).join(", ")}
        </p>
        <div class="chips" style="margin-bottom: 8px">
          <span class="chip muted">${z(t.template)}</span>
          ${t.features.map((e) => x`<span class="chip">
              ${Lt(this.components, St(e))}${L(e)}
            </span>`)}
        </div>
        <label class="choice">
          <input
            type="checkbox"
            role="switch"
            .checked=${t.enabled}
            @change=${(t) => this._toggle(e, t)}
          />
          <span>Enabled</span>
        </label>
        <div class="row">
          <button type="button" class="outlined" @click=${() => this._openEditor(t)}>Edit</button>
          <button
            type="button"
            class="outlined"
            @click=${() => this._openPlan({ rule_ids: [t.id] }, t.name)}
          >
            Plan
          </button>
          <button type="button" class="danger" @click=${() => this._askDelete(e)}>Delete</button>
        </div>
      </li>
    `;
	}
	_renderRow(e) {
		let t = e.rule;
		return x`
      <tr>
        <td>
          <strong>${t.name}</strong>
          <div class="chips" style="margin-top: 4px">
            <span class="chip muted">${z(t.template)}</span>
            <span class="chip muted">${R(t.backend)}</span>
          </div>
        </td>
        <td>
          <div>${this._nameOf(t.source.device)}</div>
          <div class="secondary">${this._emitterLabel(t.source.device, t.source.emitter_id)}</div>
        </td>
        <td>
          <div class="chips">
            ${t.targets.map((e) => x`<span class="chip">${this._nameOf(e.device)}</span>`)}
          </div>
        </td>
        <td>
          <div class="chips">
            ${t.features.map((e) => x`<span class="chip" title=${L(e)}>
                ${Lt(this.components, St(e))}${L(e)}
              </span>`)}
          </div>
          ${t.direction === "two_way" ? x`<span class="secondary">Two way</span>` : C}
        </td>
        <td>
          <span class="chip ${wt(e.state)}" title=${Tt(e.state)}>
            ${B(e.state)}
          </span>
          ${e.links_total > 0 ? x`<div class="secondary">${e.links_in_sync} of ${e.links_total} links</div>` : C}
        </td>
        <td>
          <label class="choice">
            <input
              type="checkbox"
              role="switch"
              aria-label=${`Enable ${t.name}`}
              .checked=${t.enabled}
              @change=${(t) => this._toggle(e, t)}
            />
          </label>
        </td>
        <td class="actions">
          <div class="row nowrap">
            <button type="button" class="outlined" @click=${() => this._openEditor(t)}>
              Edit
            </button>
            <button
              type="button"
              class="outlined"
              @click=${() => this._openPlan({ rule_ids: [t.id] }, t.name)}
            >
              Plan
            </button>
            <button type="button" class="danger" @click=${() => this._askDelete(e)}>
              Delete
            </button>
          </div>
        </td>
      </tr>
    `;
	}
	_renderEmpty() {
		return x`
      <p>No rules yet. Start from what you want the control to do.</p>
      <div
        class="chips"
        style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 8px"
      >
        ${this._templates.map((e) => x`
            <button
              type="button"
              class="selectable"
              style="border-color: var(--divider-color, rgba(0, 0, 0, 0.12))"
              @click=${() => this._openEditor(null, e)}
            >
              <strong>${z(e)}</strong>
              <div class="secondary">${Ct(e)}</div>
            </button>
          `)}
      </div>
    `;
	}
	_renderDeleteConfirm() {
		let e = this._confirmDelete;
		return x`
      <dl-dialog
        .open=${e !== null}
        .narrow=${this.narrow}
        .heading=${e === null ? "" : `Delete ${e.rule.name}?`}
        @dl-dialog-closed=${() => {
			this._confirmDelete = null;
		}}
      >
        <p>
          The rule is removed from the profile. What it already wrote stays on the devices
          and becomes unmanaged, which means it is reported rather than removed.
        </p>
        <p class="secondary">
          To take those links off as well, disable the rule first and apply that, then delete it.
        </p>
        <div slot="actions">
          <button
            type="button"
            class="outlined"
            @click=${() => {
			this._confirmDelete = null;
		}}
          >
            Cancel
          </button>
          <button type="button" class="danger" @click=${this._delete}>Delete the rule</button>
        </div>
      </dl-dialog>
    `;
	}
	_filtered() {
		let e = this._search.trim().toLowerCase();
		return this._rules.filter((t) => this._backendFilter && t.rule.backend !== this._backendFilter || this._stateFilter && t.state !== this._stateFilter ? !1 : !e || [
			t.rule.name,
			this._nameOf(t.rule.source.device),
			...t.rule.targets.map((e) => this._nameOf(e.device))
		].join(" ").toLowerCase().includes(e));
	}
	_nameOf(e) {
		return this._devices.find((t) => t.identity === e)?.name ?? e;
	}
	_emitterLabel(e, t) {
		return this._emitterLabels[`${e}/${t}`] ?? t;
	}
	async _load() {
		if (this.api) {
			this._loading = !0;
			try {
				let [e, t, n] = await Promise.all([
					this.api.listProfiles(),
					this.api.listDevices(),
					this.api.listTemplates()
				]);
				this._devices = t ?? [], n?.length && (this._templates = n.map((e) => e.id));
				let r = (e.profiles ?? []).find((e) => e.is_active) ?? null;
				this._profile = r, this._rules = r === null ? [] : (await this.api.getProfile(r.id)).rules ?? [], this._error = null, this._loadEmitterLabels();
			} catch (e) {
				this._error = N(this.hass, M.from(e));
			} finally {
				this._loading = !1;
			}
		}
	}
	async _loadEmitterLabels() {
		if (!this.api) return;
		let e = /* @__PURE__ */ new Map();
		for (let t of this._rules) {
			let n = this._devices.find((e) => e.identity === t.rule.source.device);
			n?.device_id != null && e.set(n.identity, n.device_id);
		}
		let t = { ...this._emitterLabels };
		await Promise.all([...e].map(async ([e, n]) => {
			try {
				let r = await this.api.getDevice(n);
				for (let n of r.emitters) t[`${e}/${n.emitter_id}`] = n.label;
			} catch {}
		})), this._emitterLabels = t;
	}
	_openEditor(e, t = null) {
		this._editing = e, this._editorTemplate = t, this._editorOpen = !0;
	}
	_closeEditor() {
		this._editorOpen = !1, this._editing = null, this._editorTemplate = null;
	}
	_onSaved(e) {
		let t = e.detail;
		this._closeEditor(), this._load(), t.apply && this._openPlan({ rule_ids: [t.rule.id] }, t.rule.name);
	}
	async _toggle(e, t) {
		if (!this.api) return;
		let n = t.target.checked, r = e.rule.enabled, i = {
			...e.rule,
			enabled: n
		};
		try {
			await this.api.upsertRule(i, this._profile?.id), this._staged = {
				rule: e.rule,
				wasEnabled: r
			}, this._appliedDuringPlan = !1, await this._load(), this._openPlan({ rule_ids: [e.rule.id] }, `${n ? "Enable" : "Disable"} ${e.rule.name}`);
		} catch (e) {
			this._error = N(this.hass, M.from(e)), await this._load();
		}
	}
	_openPlan(e, t) {
		this._planScope = e, this._planHeading = t === void 0 ? "Plan and apply" : `Plan and apply: ${t}`, this._planOpen = !0;
	}
	async _closePlan(e) {
		this._planOpen = !1;
		let t = e?.detail, n = this._staged;
		this._staged = null;
		let r = !this._appliedDuringPlan && (t?.changes ?? 1) > 0;
		if (n !== null && r && this.api) try {
			await this.api.upsertRule({
				...n.rule,
				enabled: n.wasEnabled
			}, this._profile?.id);
		} catch (e) {
			this._error = N(this.hass, M.from(e));
		}
		this._appliedDuringPlan = !1, this._load();
	}
	_afterApply() {
		this._appliedDuringPlan = !0, this._load();
	}
	_askDelete(e) {
		this._confirmDelete = e;
	}
	async _delete() {
		let e = this._confirmDelete;
		if (this.api && e !== null) {
			this._confirmDelete = null;
			try {
				await this.api.deleteRule(e.rule.id, this._profile?.id), await this._load();
			} catch (e) {
				this._error = N(this.hass, M.from(e));
			}
		}
	}
};
P([A()], Q.prototype, "_profile", void 0), P([A()], Q.prototype, "_rules", void 0), P([A()], Q.prototype, "_devices", void 0), P([A()], Q.prototype, "_templates", void 0), P([A()], Q.prototype, "_emitterLabels", void 0), P([A()], Q.prototype, "_loading", void 0), P([A()], Q.prototype, "_error", void 0), P([A()], Q.prototype, "_search", void 0), P([A()], Q.prototype, "_backendFilter", void 0), P([A()], Q.prototype, "_stateFilter", void 0), P([A()], Q.prototype, "_editorOpen", void 0), P([A()], Q.prototype, "_editing", void 0), P([A()], Q.prototype, "_editorTemplate", void 0), P([A()], Q.prototype, "_planOpen", void 0), P([A()], Q.prototype, "_planScope", void 0), P([A()], Q.prototype, "_planHeading", void 0), P([A()], Q.prototype, "_confirmDelete", void 0), Q = P([O("device-links-rules")], Q);
//#endregion
//#region src/panel.ts
var Jt = "0.0.1", $ = class extends D {
	constructor(...e) {
		super(...e), this.narrow = !1, this.componentLoader = () => at(), this._components = null, this._selected = null, this._api = null;
	}
	static {
		this.styles = o`
    :host {
      display: block;
      height: 100%;
      background: var(--primary-background-color, #fafafa);
      color: var(--primary-text-color, #212121);
      font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif);
    }

    .plain-bar {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 12px 16px;
      background: var(--app-header-background-color, var(--primary-color, #03a9f4));
      color: var(--app-header-text-color, #fff);
      font-size: 20px;
    }

    .plain-tabs {
      display: flex;
      gap: 4px;
      flex-wrap: wrap;
      padding: 8px 16px;
      border-bottom: 1px solid var(--divider-color, #e0e0e0);
    }

    .plain-tabs button {
      font: inherit;
      color: inherit;
      background: none;
      border: none;
      border-bottom: 2px solid transparent;
      padding: 8px 12px;
      cursor: pointer;
    }

    .plain-tabs button[aria-current="page"] {
      border-bottom-color: var(--primary-color, #03a9f4);
      font-weight: 500;
    }

    .plain-tabs button:focus-visible {
      outline: 2px solid var(--primary-color, #03a9f4);
      outline-offset: 2px;
    }

    .banner {
      margin: 16px;
    }

    .banner-plain {
      margin: 16px;
      padding: 12px 16px;
      border-radius: 8px;
      border: 1px solid var(--warning-color, #ffa600);
      background: var(--card-background-color, #fff);
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }

    .loading {
      padding: 32px 16px;
      text-align: center;
      color: var(--secondary-text-color, #727272);
    }

    .view {
      display: block;
    }
  `;
	}
	get tab() {
		return lt(this.route?.path);
	}
	get api() {
		return this._api;
	}
	connectedCallback() {
		super.connectedCallback(), this._loadComponents(), this._openClient();
	}
	disconnectedCallback() {
		super.disconnectedCallback(), this._api?.close(), this._api = null;
	}
	willUpdate(e) {
		e.has("hass") && this._openClient();
	}
	_openClient() {
		this.hass && (this._api === null ? this._api = new et(this.hass) : this._api.hass = this.hass);
	}
	async _loadComponents() {
		this._components === null && (this._components = await this.componentLoader());
	}
	render() {
		return x`
      ${this._renderBar()}
      ${this._renderVersionBanner()}
      ${this._components === null ? x`<div class="loading">Loading Home Assistant components</div>` : this._renderView()}
    `;
	}
	_renderBar() {
		let e = this._components;
		return e?.has("ha-top-app-bar-fixed") ? x`
      <ha-top-app-bar-fixed>
        ${e.has("ha-menu-button") ? x`<ha-menu-button
              slot="navigationIcon"
              .hass=${this.hass}
              .narrow=${this.narrow}
            ></ha-menu-button>` : C}
        <div slot="title">Device Links</div>
        ${this._renderTabs()}
      </ha-top-app-bar-fixed>
    ` : x`
        <header class="plain-bar">
          <span>Device Links</span>
        </header>
        ${this._renderTabs()}
      `;
	}
	_renderTabs() {
		let e = this._components;
		return !e?.has("ha-tab-group") || !e.has("ha-tab-group-tab") ? x`
        <nav class="plain-tabs" aria-label="Device Links sections">
          ${I.map((e) => x`
              <button
                type="button"
                aria-current=${e.id === this.tab ? "page" : "false"}
                @click=${() => this._selectTab(e.id)}
              >
                ${e.label}
              </button>
            `)}
        </nav>
      ` : x`
      <ha-tab-group slot="tabs" aria-label="Device Links sections">
        ${I.map((t) => x`
            <ha-tab-group-tab
              slot="nav"
              panel=${t.id}
              .active=${t.id === this.tab}
              @click=${() => this._selectTab(t.id)}
            >
              ${this.narrow && e.has("ha-icon") ? x`<ha-icon .icon=${t.icon} aria-label=${t.label}></ha-icon>` : t.label}
            </ha-tab-group-tab>
          `)}
      </ha-tab-group>
    `;
	}
	_selectTab(e, t = null) {
		if (this._selected = t, e === this.tab) return;
		let n = this.route?.prefix ?? "/device_links";
		history.pushState(null, "", `${n}/${e}`), this.dispatchEvent(new CustomEvent("location-changed", {
			bubbles: !0,
			composed: !0
		})), this.route = {
			prefix: n,
			path: `/${e}`
		};
	}
	get backendVersion() {
		let e = this.panel?.config?.version;
		return typeof e == "string" && e ? e : null;
	}
	get versionMismatch() {
		let e = this.backendVersion;
		return e !== null && e !== "0.0.1";
	}
	_renderVersionBanner() {
		if (!this.versionMismatch) return C;
		let e = `Device Links was updated to ${this.backendVersion} while this page was open. This panel is still running version ${Jt}. Reload the page to pick up the new one.`;
		return this._components?.has("ha-alert") ? x`
        <ha-alert class="banner" alert-type="info" title="A newer version is installed">
          ${e}
          <button type="button" slot="action" @click=${() => this._reload()}>Reload</button>
        </ha-alert>
      ` : x`
      <div class="banner-plain" role="status">
        <span>${e}</span>
        <button type="button" @click=${() => this._reload()}>Reload</button>
      </div>
    `;
	}
	_reload() {
		location.reload();
	}
	_renderView() {
		let e = I.find((e) => e.id === this.tab) ?? I[0];
		return e ? Ke`
      <${We(e.tagName)}
        class="view"
        .hass=${this.hass}
        .api=${this._api}
        .components=${this._components}
        .narrow=${this.narrow}
        .selected=${this._selected}
        @dl-navigate=${this._onNavigate}
      ></${We(e.tagName)}>
    ` : x`<div class="loading">No view is registered.</div>`;
	}
	_onNavigate(e) {
		let t = e.detail;
		t?.tab && this._selectTab(t.tab, t.select ?? null);
	}
};
P([k({ attribute: !1 })], $.prototype, "hass", void 0), P([k({
	type: Boolean,
	reflect: !0
})], $.prototype, "narrow", void 0), P([k({ attribute: !1 })], $.prototype, "route", void 0), P([k({ attribute: !1 })], $.prototype, "panel", void 0), P([k({ attribute: !1 })], $.prototype, "componentLoader", void 0), P([A()], $.prototype, "_components", void 0), P([A()], $.prototype, "_selected", void 0), $ = P([O("device-links-panel")], $);
//#endregion
export { Jt as BUNDLE_VERSION, $ as DeviceLinksPanel };
