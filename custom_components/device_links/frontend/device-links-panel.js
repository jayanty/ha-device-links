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
})(e) : e, { is: l, defineProperty: u, getOwnPropertyDescriptor: ee, getOwnPropertyNames: te, getOwnPropertySymbols: ne, getPrototypeOf: re } = Object, ie = globalThis, ae = ie.trustedTypes, oe = ae ? ae.emptyScript : "", se = ie.reactiveElementPolyfillSupport, d = (e, t) => e, ce = {
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
}, le = (e, t) => !l(e, t), ue = {
	attribute: !0,
	type: String,
	converter: ce,
	reflect: !1,
	useDefault: !1,
	hasChanged: le
};
Symbol.metadata ??= Symbol("metadata"), ie.litPropertyMetadata ??= /* @__PURE__ */ new WeakMap();
var f = class extends HTMLElement {
	static addInitializer(e) {
		this._$Ei(), (this.l ??= []).push(e);
	}
	static get observedAttributes() {
		return this.finalize(), this._$Eh && [...this._$Eh.keys()];
	}
	static createProperty(e, t = ue) {
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
		return this.elementProperties.get(e) ?? ue;
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
			let i = (n.converter?.toAttribute === void 0 ? ce : n.converter).toAttribute(t, n.type);
			this._$Em = e, i == null ? this.removeAttribute(r) : this.setAttribute(r, i), this._$Em = null;
		}
	}
	_$AK(e, t) {
		let n = this.constructor, r = n._$Eh.get(e);
		if (r !== void 0 && this._$Em !== r) {
			let e = n.getPropertyOptions(r), i = typeof e.converter == "function" ? { fromAttribute: e.converter } : e.converter?.fromAttribute === void 0 ? ce : e.converter;
			this._$Em = r;
			let a = i.fromAttribute(t, e.type);
			this[r] = a ?? this._$Ej?.get(r) ?? a, this._$Em = null;
		}
	}
	requestUpdate(e, t, n, r = !1, i) {
		if (e !== void 0) {
			let a = this.constructor;
			if (!1 === r && (i = this[e]), n ??= a.getPropertyOptions(e), !((n.hasChanged ?? le)(i, t) || n.useDefault && n.reflect && i === this._$Ej?.get(e) && !this.hasAttribute(a._$Eu(e, n)))) return;
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
f.elementStyles = [], f.shadowRootOptions = { mode: "open" }, f[d("elementProperties")] = /* @__PURE__ */ new Map(), f[d("finalized")] = /* @__PURE__ */ new Map(), se?.({ ReactiveElement: f }), (ie.reactiveElementVersions ??= []).push("2.1.2");
//#endregion
//#region node_modules/lit-html/lit-html.js
var de = globalThis, fe = (e) => e, pe = de.trustedTypes, me = pe ? pe.createPolicy("lit-html", { createHTML: (e) => e }) : void 0, he = "$lit$", p = `lit$${Math.random().toFixed(9).slice(2)}$`, ge = "?" + p, _e = `<${ge}>`, m = document, h = () => m.createComment(""), g = (e) => e === null || typeof e != "object" && typeof e != "function", ve = Array.isArray, ye = (e) => ve(e) || typeof e?.[Symbol.iterator] == "function", be = "[ 	\n\f\r]", xe = /<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g, Se = /-->/g, Ce = />/g, _ = RegExp(`>|${be}(?:([^\\s"'>=/]+)(${be}*=${be}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`, "g"), we = /'/g, Te = /"/g, Ee = /^(?:script|style|textarea|title)$/i, v = ((e) => (t, ...n) => ({
	_$litType$: e,
	strings: t,
	values: n
}))(1), y = Symbol.for("lit-noChange"), b = Symbol.for("lit-nothing"), De = /* @__PURE__ */ new WeakMap(), x = m.createTreeWalker(m, 129);
function Oe(e, t) {
	if (!ve(e) || !e.hasOwnProperty("raw")) throw Error("invalid template strings array");
	return me === void 0 ? t : me.createHTML(t);
}
var ke = (e, t) => {
	let n = e.length - 1, r = [], i, a = t === 2 ? "<svg>" : t === 3 ? "<math>" : "", o = xe;
	for (let t = 0; t < n; t++) {
		let n = e[t], s, c, l = -1, u = 0;
		for (; u < n.length && (o.lastIndex = u, c = o.exec(n), c !== null);) u = o.lastIndex, o === xe ? c[1] === "!--" ? o = Se : c[1] === void 0 ? c[2] === void 0 ? c[3] !== void 0 && (o = _) : (Ee.test(c[2]) && (i = RegExp("</" + c[2], "g")), o = _) : o = Ce : o === _ ? c[0] === ">" ? (o = i ?? xe, l = -1) : c[1] === void 0 ? l = -2 : (l = o.lastIndex - c[2].length, s = c[1], o = c[3] === void 0 ? _ : c[3] === "\"" ? Te : we) : o === Te || o === we ? o = _ : o === Se || o === Ce ? o = xe : (o = _, i = void 0);
		let ee = o === _ && e[t + 1].startsWith("/>") ? " " : "";
		a += o === xe ? n + _e : l >= 0 ? (r.push(s), n.slice(0, l) + he + n.slice(l) + p + ee) : n + p + (l === -2 ? t : ee);
	}
	return [Oe(e, a + (e[n] || "<?>") + (t === 2 ? "</svg>" : t === 3 ? "</math>" : "")), r];
}, Ae = class e {
	constructor({ strings: t, _$litType$: n }, r) {
		let i;
		this.parts = [];
		let a = 0, o = 0, s = t.length - 1, c = this.parts, [l, u] = ke(t, n);
		if (this.el = e.createElement(l, r), x.currentNode = this.el.content, n === 2 || n === 3) {
			let e = this.el.content.firstChild;
			e.replaceWith(...e.childNodes);
		}
		for (; (i = x.nextNode()) !== null && c.length < s;) {
			if (i.nodeType === 1) {
				if (i.hasAttributes()) for (let e of i.getAttributeNames()) if (e.endsWith(he)) {
					let t = u[o++], n = i.getAttribute(e).split(p), r = /([.?@])?(.*)/.exec(t);
					c.push({
						type: 1,
						index: a,
						name: r[2],
						strings: n,
						ctor: r[1] === "." ? Pe : r[1] === "?" ? Fe : r[1] === "@" ? Ie : Ne
					}), i.removeAttribute(e);
				} else e.startsWith(p) && (c.push({
					type: 6,
					index: a
				}), i.removeAttribute(e));
				if (Ee.test(i.tagName)) {
					let e = i.textContent.split(p), t = e.length - 1;
					if (t > 0) {
						i.textContent = pe ? pe.emptyScript : "";
						for (let n = 0; n < t; n++) i.append(e[n], h()), x.nextNode(), c.push({
							type: 2,
							index: ++a
						});
						i.append(e[t], h());
					}
				}
			} else if (i.nodeType === 8) {
				if (i.data === ge) c.push({
					type: 2,
					index: a
				});
				else {
					let e = -1;
					for (; (e = i.data.indexOf(p, e + 1)) !== -1;) c.push({
						type: 7,
						index: a
					}), e += p.length - 1;
				}
			}
			a++;
		}
	}
	static createElement(e, t) {
		let n = m.createElement("template");
		return n.innerHTML = e, n;
	}
};
function S(e, t, n = e, r) {
	if (t === y) return t;
	let i = r === void 0 ? n._$Cl : n._$Co?.[r], a = g(t) ? void 0 : t._$litDirective$;
	return i?.constructor !== a && (i?._$AO?.(!1), a === void 0 ? i = void 0 : (i = new a(e), i._$AT(e, n, r)), r === void 0 ? n._$Cl = i : (n._$Co ??= [])[r] = i), i !== void 0 && (t = S(e, i._$AS(e, t.values), i, r)), t;
}
var je = class {
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
		let { el: { content: t }, parts: n } = this._$AD, r = (e?.creationScope ?? m).importNode(t, !0);
		x.currentNode = r;
		let i = x.nextNode(), a = 0, o = 0, s = n[0];
		for (; s !== void 0;) {
			if (a === s.index) {
				let t;
				s.type === 2 ? t = new Me(i, i.nextSibling, this, e) : s.type === 1 ? t = new s.ctor(i, s.name, s.strings, this, e) : s.type === 6 && (t = new Le(i, this, e)), this._$AV.push(t), s = n[++o];
			}
			a !== s?.index && (i = x.nextNode(), a++);
		}
		return x.currentNode = m, r;
	}
	p(e) {
		let t = 0;
		for (let n of this._$AV) n !== void 0 && (n.strings === void 0 ? n._$AI(e[t]) : (n._$AI(e, n, t), t += n.strings.length - 2)), t++;
	}
}, Me = class e {
	get _$AU() {
		return this._$AM?._$AU ?? this._$Cv;
	}
	constructor(e, t, n, r) {
		this.type = 2, this._$AH = b, this._$AN = void 0, this._$AA = e, this._$AB = t, this._$AM = n, this.options = r, this._$Cv = r?.isConnected ?? !0;
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
		e = S(this, e, t), g(e) ? e === b || e == null || e === "" ? (this._$AH !== b && this._$AR(), this._$AH = b) : e !== this._$AH && e !== y && this._(e) : e._$litType$ === void 0 ? e.nodeType === void 0 ? ye(e) ? this.k(e) : this._(e) : this.T(e) : this.$(e);
	}
	O(e) {
		return this._$AA.parentNode.insertBefore(e, this._$AB);
	}
	T(e) {
		this._$AH !== e && (this._$AR(), this._$AH = this.O(e));
	}
	_(e) {
		this._$AH !== b && g(this._$AH) ? this._$AA.nextSibling.data = e : this.T(m.createTextNode(e)), this._$AH = e;
	}
	$(e) {
		let { values: t, _$litType$: n } = e, r = typeof n == "number" ? this._$AC(e) : (n.el === void 0 && (n.el = Ae.createElement(Oe(n.h, n.h[0]), this.options)), n);
		if (this._$AH?._$AD === r) this._$AH.p(t);
		else {
			let e = new je(r, this), n = e.u(this.options);
			e.p(t), this.T(n), this._$AH = e;
		}
	}
	_$AC(e) {
		let t = De.get(e.strings);
		return t === void 0 && De.set(e.strings, t = new Ae(e)), t;
	}
	k(t) {
		ve(this._$AH) || (this._$AH = [], this._$AR());
		let n = this._$AH, r, i = 0;
		for (let a of t) i === n.length ? n.push(r = new e(this.O(h()), this.O(h()), this, this.options)) : r = n[i], r._$AI(a), i++;
		i < n.length && (this._$AR(r && r._$AB.nextSibling, i), n.length = i);
	}
	_$AR(e = this._$AA.nextSibling, t) {
		for (this._$AP?.(!1, !0, t); e !== this._$AB;) {
			let t = fe(e).nextSibling;
			fe(e).remove(), e = t;
		}
	}
	setConnected(e) {
		this._$AM === void 0 && (this._$Cv = e, this._$AP?.(e));
	}
}, Ne = class {
	get tagName() {
		return this.element.tagName;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	constructor(e, t, n, r, i) {
		this.type = 1, this._$AH = b, this._$AN = void 0, this.element = e, this.name = t, this._$AM = r, this.options = i, n.length > 2 || n[0] !== "" || n[1] !== "" ? (this._$AH = Array(n.length - 1).fill(/* @__PURE__ */ new String()), this.strings = n) : this._$AH = b;
	}
	_$AI(e, t = this, n, r) {
		let i = this.strings, a = !1;
		if (i === void 0) e = S(this, e, t, 0), a = !g(e) || e !== this._$AH && e !== y, a && (this._$AH = e);
		else {
			let r = e, o, s;
			for (e = i[0], o = 0; o < i.length - 1; o++) s = S(this, r[n + o], t, o), s === y && (s = this._$AH[o]), a ||= !g(s) || s !== this._$AH[o], s === b ? e = b : e !== b && (e += (s ?? "") + i[o + 1]), this._$AH[o] = s;
		}
		a && !r && this.j(e);
	}
	j(e) {
		e === b ? this.element.removeAttribute(this.name) : this.element.setAttribute(this.name, e ?? "");
	}
}, Pe = class extends Ne {
	constructor() {
		super(...arguments), this.type = 3;
	}
	j(e) {
		this.element[this.name] = e === b ? void 0 : e;
	}
}, Fe = class extends Ne {
	constructor() {
		super(...arguments), this.type = 4;
	}
	j(e) {
		this.element.toggleAttribute(this.name, !!e && e !== b);
	}
}, Ie = class extends Ne {
	constructor(e, t, n, r, i) {
		super(e, t, n, r, i), this.type = 5;
	}
	_$AI(e, t = this) {
		if ((e = S(this, e, t, 0) ?? b) === y) return;
		let n = this._$AH, r = e === b && n !== b || e.capture !== n.capture || e.once !== n.once || e.passive !== n.passive, i = e !== b && (n === b || r);
		r && this.element.removeEventListener(this.name, this, n), i && this.element.addEventListener(this.name, this, e), this._$AH = e;
	}
	handleEvent(e) {
		typeof this._$AH == "function" ? this._$AH.call(this.options?.host ?? this.element, e) : this._$AH.handleEvent(e);
	}
}, Le = class {
	constructor(e, t, n) {
		this.element = e, this.type = 6, this._$AN = void 0, this._$AM = t, this.options = n;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	_$AI(e) {
		S(this, e);
	}
}, Re = de.litHtmlPolyfillSupport;
Re?.(Ae, Me), (de.litHtmlVersions ??= []).push("3.3.3");
var ze = (e, t, n) => {
	let r = n?.renderBefore ?? t, i = r._$litPart$;
	if (i === void 0) {
		let e = n?.renderBefore ?? null;
		r._$litPart$ = i = new Me(t.insertBefore(h(), e), e, void 0, n ?? {});
	}
	return i._$AI(e), i;
}, Be = globalThis, C = class extends f {
	constructor() {
		super(...arguments), this.renderOptions = { host: this }, this._$Do = void 0;
	}
	createRenderRoot() {
		let e = super.createRenderRoot();
		return this.renderOptions.renderBefore ??= e.firstChild, e;
	}
	update(e) {
		let t = this.render();
		this.hasUpdated || (this.renderOptions.isConnected = this.isConnected), super.update(e), this._$Do = ze(t, this.renderRoot, this.renderOptions);
	}
	connectedCallback() {
		super.connectedCallback(), this._$Do?.setConnected(!0);
	}
	disconnectedCallback() {
		super.disconnectedCallback(), this._$Do?.setConnected(!1);
	}
	render() {
		return y;
	}
};
C._$litElement$ = !0, C.finalized = !0, Be.litElementHydrateSupport?.({ LitElement: C });
var Ve = Be.litElementPolyfillSupport;
Ve?.({ LitElement: C }), (Be.litElementVersions ??= []).push("4.2.2");
//#endregion
//#region node_modules/@lit/reactive-element/decorators/custom-element.js
var w = (e) => (t, n) => {
	n === void 0 ? customElements.define(e, t) : n.addInitializer(() => {
		customElements.define(e, t);
	});
}, He = {
	attribute: !0,
	type: String,
	converter: ce,
	reflect: !1,
	hasChanged: le
}, Ue = (e = He, t, n) => {
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
function T(e) {
	return (t, n) => typeof n == "object" ? Ue(e, t, n) : ((e, t, n) => {
		let r = t.hasOwnProperty(n);
		return t.constructor.createProperty(n, e), r ? Object.getOwnPropertyDescriptor(t, n) : void 0;
	})(e, t, n);
}
//#endregion
//#region node_modules/@lit/reactive-element/decorators/state.js
function E(e) {
	return T({
		...e,
		state: !0,
		attribute: !1
	});
}
//#endregion
//#region node_modules/@lit/reactive-element/decorators/base.js
var We = (e, t, n) => (n.configurable = !0, n.enumerable = !0, Reflect.decorate && typeof t != "object" && Object.defineProperty(e, t, n), n);
//#endregion
//#region node_modules/@lit/reactive-element/decorators/query.js
function Ge(e, t) {
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
			return We(n, r, { get() {
				let n = e.call(this);
				return n === void 0 && (n = a(this), (n !== null || this.hasUpdated) && t.call(this, n)), n;
			} });
		}
		return We(n, r, { get() {
			return a(this);
		} });
	};
}
//#endregion
//#region node_modules/lit-html/static.js
var Ke = Symbol.for(""), qe = (e) => {
	if (e?.r === Ke) return e?._$litStatic$;
}, Je = (e) => ({
	_$litStatic$: e,
	r: Ke
}), Ye = /* @__PURE__ */ new Map(), Xe = ((e) => (t, ...n) => {
	let r = n.length, i, a, o = [], s = [], c, l = 0, u = !1;
	for (; l < r;) {
		for (c = t[l]; l < r && (a = n[l], (i = qe(a)) !== void 0);) c += i + t[++l], u = !0;
		l !== r && s.push(a), o.push(c), l++;
	}
	if (l === r && o.push(t[r]), u) {
		let e = o.join("$$lit$$");
		(t = Ye.get(e)) === void 0 && (o.raw = o, Ye.set(e, t = o)), n = s;
	}
	return e(t, ...n);
})(v), Ze = "component.device_links", Qe = ["exceptions", "issues"];
function $e(e, t) {
	return t ? e.replace(/\{(\w+)\}/g, (e, n) => {
		let r = t[n];
		return r == null ? e : String(r);
	}) : e;
}
function et(e, t, n) {
	for (let r of Qe) {
		let i = e?.localize(`${Ze}.${r}.${t}.message`, { ...n ?? {} });
		if (i) return i;
	}
	let r = {
		backend_not_loaded: "The {backend} integration is not loaded, so the group {group} link from {device} to {target} was not written. Set that protocol integration up again, then apply.",
		blocked_by_plan: "The plan refused a change on {device} without saying why. That is a fault in Device Links rather than in the device; please report it with the diagnostics file.",
		button_semantics_unknown: "{emitter} on {device} may toggle rather than always sending off, so an off-all button here can turn the lights back on every second press. Test it before you rely on it.",
		check_failed: "The Z-Wave driver could not be asked whether group {group} on {device} may reach {target}, so nothing was written. Check that Z-Wave JS is running, then try again.",
		device_unavailable: "{device} stopped answering, so its group {group} link to {target} was left alone. It will be planned again once the device can be read.",
		diff_needs_one_other_side: "A comparison needs exactly one other side: another profile, or a snapshot. This asked for neither or for both.",
		feature_unavailable_color: "{emitter} does not send colour commands, so the colour part of this rule was left out.",
		feature_unavailable_level_hold: "{emitter} does not send hold-to-dim, so holding the control will do nothing. The rest of the rule still works.",
		feature_unavailable_level_set: "{emitter} does not send a brightness level, so dimming was left out of this rule. The rest of it still works.",
		feature_unavailable_on_off: "{emitter} does not send an on or off command, so this rule cannot switch anything with it. Choose a control that does, or take on/off out of the rule.",
		feature_unavailable_scene: "{emitter} does not send scene commands, so the scene part of this rule was left out.",
		feature_unavailable_status_report: "{emitter} does not report its own state, so the status feedback part of this rule was left out.",
		group_full: "Group {group} on {device} is full ({used} of {capacity}). Remove an entry it holds, or point this rule at a group with room, before adding {target}.",
		group_not_offered: "No control of {device} uses association group {group}. The groups it offers are: {groups}.",
		hybrid_button_led_one_target: "Keeping {emitter} in sync works with one target, and this rule has {count}. One button has one light on it, so several targets would each be telling it something different and it would show whichever spoke last. Split this into one rule per target, or turn the option off.",
		hybrid_no_button_indication: "The control {emitter} on {device} has no button indication Device Links knows how to write, so the leg that would make its LED follow a light cannot be made. Only a curated device profile can say which indicator belongs to which button, and guessing would light the wrong one.",
		hybrid_no_scene: "The control {emitter} on {device} does not report a scene number when it is pressed, as far as Device Links knows, so a leg that has to react to a press on it cannot be made. Guessing the number would make the leg fire when a different button was pressed.",
		hybrid_opt_in_unused: "The rule {rule} asks Home Assistant to carry {kind}, and does not ask for the feature that option acts on, so it does nothing. Add the feature, or turn the option off.",
		hybrid_reverse_carries_both: "This rule is two way, so the leg back from each target to {emitter} still carries both on and off. Only the direction you authored is limited to one of them.",
		hybrid_scene_unverified: "The scene number {emitter} on {device} reports has not been observed, only inferred from the device's own button numbering, so a leg that reacts to a press on it may react to a different button. Press it once with the rule enabled and check that the right thing happened.",
		hybrid_self_load_not_targeted: "This rule asks Home Assistant to act on the control's own load on {device}, and does not list that device as a target, so there is nothing for the leg to act on. Add the device to the targets.",
		import_unknown_devices: "This profile names devices that are not on this network: {devices}. The rules waiting for them are: {rules}. Nothing was imported, so nothing was lost.",
		job_running: "An apply is already running. Wait for it to finish and plan again: a plan made before it started would be out of date by the time it ran.",
		level_hold_without_on_off: "{emitter} can dim on hold but cannot switch on or off, so the light can be dimmed and not turned on. Add on/off to the rule if the control supports it.",
		lifeline_is_protected: "Group {group} on {device} is its lifeline, which is how the device reports to Home Assistant at all. Device Links never writes to it.",
		link_write_failed: "{device} did not accept the group {group} link to {target}. The error the backend reported is in the job details.",
		link_write_raised: "Writing the group {group} link from {device} to {target} failed unexpectedly, so it was not written. The error is in the log.",
		matter_acl_full: "{target} has no room for another access grant: {used} of {capacity} entries in its access list are in use, and the ones Device Links did not create are not ours to remove. Remove a controller or app that no longer needs {target}, using the app that added it, then apply again. Until then the {cluster} binding from {device} is not written.",
		matter_acl_not_targetable: "{target} cannot grant access to one cluster on one endpoint, and Device Links never grants more than that, so the {cluster} binding from {device} was not written.",
		matter_acl_subjects_full: "The access grant on {target} already lists as many controls as it allows, and its access list is full at {used} of {capacity} entries, so the {cluster} binding from {device} was not written. Point fewer controls at {target}, or remove a controller it no longer needs.",
		matter_acl_unreadable: "The access list on {target} does not say which fabric this Home Assistant is on, so the {cluster} binding from {device} was not written and nothing on the device was changed.",
		matter_binding_full: "The control this rule uses on {device} already holds {used} bindings, which is as many as Device Links writes to one endpoint. Remove a link from that control before adding another to {target}.",
		matter_binding_not_confirmed: "{device} accepted the {cluster} binding to {target} and does not report it, so it was not written after all. Apply again, and check that {device} is reachable.",
		matter_grant_not_confirmed: "{target} did not confirm the access grant that the {cluster} binding from {device} needs, so no binding was written and nothing is half done. The details are in the job result.",
		matter_group_target: "{target} is a Matter group, and Device Links does not write group bindings: a Matter group needs its key handed to every member when a device is commissioned. Point the rule at the devices themselves.",
		matter_no_binding_cluster: "The control this rule uses on {device} has no Binding cluster, so there is nowhere on it to keep a link to {target}. This device cannot be a Matter binding source.",
		matter_node_offline: "{device} or {target} is not answering, so the {cluster} binding was not written. Apply again once the device is awake and reachable.",
		matter_self_binding: "A device cannot be bound to itself, so {device} cannot control itself over the radio.",
		matter_source_cannot_send: "The control this rule uses on {device} does not send {cluster}, so binding it to {target} would do nothing. Choose a control that sends it.",
		matter_target_cannot_receive: "{target} does not act on {cluster}, so the binding from {device} would be accepted and then do nothing. Choose an endpoint of {target} that does.",
		matter_target_endpoint_required: "A Matter binding always names an endpoint of the target, and this rule names {target} as a whole, so the {cluster} binding from {device} was not written. Point the rule at one endpoint.",
		matter_unknown_cluster: "The control this rule uses on {device} does not name a Matter cluster, so nothing could be written to {target}. A rule written for another protocol reads this way.",
		matter_unknown_device: "The Matter fabric does not report {target}, so the {cluster} binding from {device} was not written. It may have been removed from the fabric.",
		matter_write_failed: "The Matter fabric refused a write for the {cluster} binding from {device} to {target}. The error it reported is in the job details.",
		matter_writes_disabled: "Matter writes are turned off, so the {cluster} binding from {device} to {target} was not written. Turn on Matter binding in the Device Links options when you are ready to let it write to your Matter devices.",
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
		self_association_use_hybrid_leg: "{device} cannot control itself over the radio: a device cannot be a member of its own association group. Home Assistant can carry that part instead. Turn on hybrid legs in the Device Links options, then tick “Also turn off this device's own load” on this rule. That part runs in Home Assistant and stops when Home Assistant does; the rest of the rule does not.",
		setting_not_applied: "{device} accepted the change to {setting} and then reported its old value, so the setting did not stick.",
		setting_not_reported: "{device} did not report {setting} back after it was written, so the change could not be confirmed.",
		setting_write_failed: "{setting} could not be written to {device}. The error is in the log; nothing else about the rule was changed.",
		settings_not_available: "{device} has no {setting} setting that Device Links knows how to write, so that part of the rule was not applied. The rest of it is unaffected; contributing a profile entry for this model would add it.",
		source_is_long_range: "{device} joined over Z-Wave Long Range, which cannot use associations at all. Re-include it as classic Z-Wave if you want to link it.",
		stale_plan: "{device} changed after this plan was made, so its group {group} link to {target} was not written. Plan again to see what is needed now.",
		storage_no_migration: "The stored profiles are at schema version {found} and this version of Device Links reads version {supported}, and there is no way to migrate between them. Restore the file from a backup, or move it aside and start again.",
		storage_unreadable: "The stored profiles could not be read: {error}. The file was left exactly as it is, so nothing has been lost.",
		storage_version_too_new: "The stored profiles were written by a newer version of Device Links (schema version {found}; this one reads {supported}). Update Home Assistant, or restore the file from a backup.",
		swap_across_backends: "A {old} device cannot be swapped for a {new} one. Every link a rule makes lives in one protocol, so the replacement would change the address of every link and which targets can be reached at all. Write the rules again for the new device.",
		swap_device_not_referenced: "No rule of the active profile refers to {device}, so a swap would change nothing.",
		swap_duplicate_target_merged: "The rule {rule} already sent to {device}, so the two are now one target.",
		swap_feature_lost: "{device} cannot carry {feature} for the rule {rule}, so that part of the rule stops working after the swap.",
		swap_mapping_incomplete: "Nothing has been chosen to take over from these controls: {controls}. Pick one for each before applying the swap.",
		swap_not_possible: "This swap cannot be made: {reasons}.",
		swap_replacement_unavailable: "{device} is not answering, so nothing can be written to it and this swap was not applied. Nothing was changed on either device.",
		swap_replacement_unreadable: "{device} has not been read yet, so what it can do is unknown and nothing can be moved onto it. Refresh it and try again.",
		swap_same_device: "{device} is already the device the rules name, so there is nothing to swap it for.",
		swap_target_endpoint_moved: "The rule {rule} now sends to endpoint {endpoint} of {device}, which is where that device receives.",
		swap_unknown_old_device: "No rule of the active profile refers to the device {device}.",
		swap_would_lose_work: "This swap would leave part of these rules unwritten: {rules}. Look at what the preview says is lost, then confirm it.",
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
		unknown_snapshot: "No snapshot with the id {snapshot} is kept. Only the last 20 are, so an older one has been dropped to make room.",
		unmanaged_not_selected: "The group {group} entry on {device} pointing at {target} was not created by Device Links, so it was left alone. Tick it in the plan if you want it removed.",
		unsupported_operation: "Device Links cannot carry out {operation} on {device} yet, so it was reported rather than attempted.",
		verify_missing: "The group {group} link from {device} to {target} was written and is not on the device, so it counts as drifted. Apply again, or look at the group in Z-Wave JS.",
		verify_not_confirmed: "{device} did not confirm the group {group} link to {target} on a fresh read, so it is reported as unconfirmed rather than as applied. Press Verify when the device is awake and reachable.",
		verify_still_present: "The group {group} entry on {device} pointing at {target} was removed and is still on the device, so it counts as drifted.",
		verify_unreadable: "{device} could not be read after the write, so the group {group} link to {target} cannot be confirmed. Press Verify when the device is reachable.",
		zigbee_bind_failed: "The Zigbee bridge refused to bind {cluster} from {device} to {target}. The error it reported is in the job details.",
		zigbee_bridge_offline: "Zigbee2MQTT on {topic} is offline, so the {cluster} binding from {device} to {target} was not written. It will be planned again once the bridge is back.",
		zigbee_clusters_failed: "{device} bound some of what was asked for and not all of it: {clusters} did not bind, so the link to {target} is incomplete. The bridge reports a partial failure as a success, so this is reported as failed rather than as applied. Apply again, and check that {target} is reachable.",
		zigbee_coordinator_binding_protected: "The {cluster} binding on {device} points at the Zigbee coordinator, which is how the device reports to Home Assistant at all. Device Links never writes to those.",
		zigbee_foreign_group: "The Zigbee group {target} was not created by Device Links, so the {cluster} binding from {device} was not written to it. Only groups named with the dl_ prefix are ours to use.",
		zigbee_group_failed: "The Zigbee group {group} could not be set up, so the {cluster} binding from {device} to {target} was not written. Check Zigbee2MQTT and apply again.",
		zigbee_no_response: "The Zigbee bridge did not answer within {seconds} seconds, so it is not known whether the {cluster} binding from {device} to {target} was made. Look at the device again, or apply once more: an apply that is already done writes nothing.",
		zigbee_self_binding: "A device cannot be bound to itself, so {device} cannot control itself over the radio.",
		zigbee_settings_not_written: "Device Links can read what {device} exposes but does not write Zigbee device settings yet, so {setting} was left alone. Change it in Zigbee2MQTT for now.",
		zigbee_source_cannot_send: "The control this rule uses on {device} does not send {cluster}, so binding it to {target} would do nothing. Choose a control that sends it.",
		zigbee_target_cannot_receive: "{target} does not act on {cluster}, so the binding from {device} would be accepted and then do nothing. Choose an endpoint of {target} that does.",
		zigbee_target_endpoint_required: "A Zigbee binding always names an endpoint of the target, and this rule names {target} as a whole, so the {cluster} binding from {device} was not written. Point the rule at one endpoint.",
		zigbee_unknown_device: "Zigbee2MQTT does not report {target}, so the {cluster} binding from {device} was not written. It may have been removed from the network.",
		zigbee_wake_the_device: "{device} was not listening, so the {cluster} binding to {target} is queued rather than written. Wake the device and apply again."
	}[t];
	return r === void 0 ? null : $e(r, n);
}
function D(e, t) {
	if (!t) return "";
	let n = et(e, t.translation_key, t.placeholders);
	return n === null ? `Device Links reported "${t.translation_key.replace(/_/g, " ")}", and this panel has no wording for it yet.` : n;
}
//#endregion
//#region src/api.ts
var O = {
	profilesList: "device_links/profiles/list",
	profilesGet: "device_links/profiles/get",
	profilesCreate: "device_links/profiles/create",
	profilesUpdate: "device_links/profiles/update",
	profilesDelete: "device_links/profiles/delete",
	profilesActivate: "device_links/profiles/activate",
	profilesDuplicate: "device_links/profiles/duplicate",
	profilesDiff: "device_links/profiles/diff",
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
	snapshotsList: "device_links/snapshots/list",
	snapshotsRollback: "device_links/snapshots/rollback",
	swapCandidates: "device_links/swap/candidates",
	swapPreview: "device_links/swap/preview",
	swapApply: "device_links/swap/apply"
}, k = class e extends Error {
	constructor(e, t = {}) {
		super(e), this.name = "DeviceLinksApiError", this.code = t.code ?? "unknown_error", this.translationKey = t.translationKey ?? null, this.translationDomain = t.translationDomain ?? null, this.placeholders = t.placeholders ?? {};
	}
	static from(t) {
		return t instanceof e ? t : tt(t) ? new e(t.message || "Device Links could not answer.", {
			code: t.code,
			translationKey: t.translation_key ?? null,
			translationDomain: t.translation_domain ?? null,
			placeholders: t.translation_placeholders ?? null
		}) : t instanceof Error ? new e(t.message || "Device Links could not answer.", { code: "connection_error" }) : new e("Device Links could not answer, and gave no reason. The connection to Home Assistant may have dropped.", { code: "connection_error" });
	}
};
function tt(e) {
	if (typeof e != "object" || !e) return !1;
	let t = e;
	return typeof t.code == "string" && typeof t.message == "string";
}
function A(e, t) {
	if (t.translationKey) {
		let n = et(e, t.translationKey, t.placeholders);
		if (n !== null) return n;
	}
	return $e(t.message, t.placeholders);
}
function nt(e) {
	let t = {};
	return e?.rule_ids?.length && (t.rule_ids = [...e.rule_ids]), e?.device_ids?.length && (t.device_ids = [...e.device_ids]), t;
}
var rt = class {
	constructor(e) {
		this.open = /* @__PURE__ */ new Set(), this.hass = e;
	}
	async listProfiles() {
		return this.send(O.profilesList);
	}
	async getProfile(e) {
		return this.send(O.profilesGet, { profile_id: e });
	}
	async createProfile(e) {
		return (await this.send(O.profilesCreate, { profile: e })).profile;
	}
	async updateProfile(e) {
		return (await this.send(O.profilesUpdate, { profile: e })).profile;
	}
	async deleteProfile(e) {
		await this.send(O.profilesDelete, { profile_id: e });
	}
	async activateProfile(e) {
		return this.send(O.profilesActivate, { profile_id: e });
	}
	async duplicateProfile(e, t) {
		return (await this.send(O.profilesDuplicate, {
			profile_id: e,
			...t === void 0 ? {} : { name: t }
		})).profile;
	}
	async diffProfile(e, t) {
		return this.send(O.profilesDiff, {
			profile_id: e,
			..."profileId" in t ? { other_profile_id: t.profileId } : { snapshot_id: t.snapshotId }
		});
	}
	async exportProfile(e) {
		return this.send(O.profilesExport, { ...e === void 0 ? {} : { profile_id: e } });
	}
	async importProfile(e) {
		return this.send(O.profilesImport, { yaml: e });
	}
	async validateRule(e) {
		return this.send(O.rulesValidate, { rule: e });
	}
	async upsertRule(e, t) {
		return this.send(O.rulesUpsert, {
			rule: e,
			...t === void 0 ? {} : { profile_id: t }
		});
	}
	async deleteRule(e, t) {
		await this.send(O.rulesDelete, {
			rule_id: e,
			...t === void 0 ? {} : { profile_id: t }
		});
	}
	async setRuleEnabled(e, t) {
		return this.send(O.rulesSetEnabled, {
			rule_id: e,
			enabled: t
		});
	}
	async listDevices() {
		return (await this.send(O.devicesList)).devices;
	}
	async getDevice(e) {
		return this.send(O.devicesGet, { device_id: e });
	}
	async refreshDevice(e, t = !1) {
		return this.send(O.devicesRefresh, {
			device_id: e,
			deep: t
		});
	}
	async listTemplates() {
		return (await this.send(O.templatesList)).templates;
	}
	async plan(e, t) {
		return this.send(O.plan, {
			...nt(e),
			...t?.length ? { remove_unmanaged: [...t] } : {}
		});
	}
	async apply(e) {
		return this.send(O.apply, {
			plan_token: e.planToken,
			...nt(e.scope),
			...e.removeUnmanaged?.length ? { remove_unmanaged: [...e.removeUnmanaged] } : {}
		});
	}
	async verify(e) {
		return this.send(O.verify, nt(e));
	}
	async listJobs() {
		return this.send(O.jobsList);
	}
	async getJob(e) {
		return this.send(O.jobsGet, { job_id: e });
	}
	async cancelJob() {
		return (await this.send(O.jobsCancel)).cancelled;
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
		}, { type: O.jobsSubscribe }).then((e) => {
			r = e, n.closed && i();
		}).catch((e) => {
			n.closed = !0, this.open.delete(n), t?.(k.from(e));
		}), n;
	}
	close() {
		for (let e of [...this.open]) e.unsubscribe();
	}
	async setUnmanagedIgnored(e, t) {
		return (await this.send(O.unmanagedIgnore, {
			fingerprints: [...e],
			ignored: t
		})).ignored;
	}
	async removeUnmanaged(e) {
		return this.send(O.unmanagedRemove, { fingerprints: [...e] });
	}
	async listSnapshots() {
		return (await this.send(O.snapshotsList)).snapshots;
	}
	async rollbackSnapshot(e, t = {}) {
		return this.send(O.snapshotsRollback, {
			snapshot_id: e,
			...t.planToken === void 0 ? {} : { plan_token: t.planToken },
			...t.removeUnmanaged?.length ? { remove_unmanaged: [...t.removeUnmanaged] } : {}
		});
	}
	async swapCandidates() {
		return (await this.send(O.swapCandidates)).replacements;
	}
	async swapPreview(e) {
		return this.send(O.swapPreview, {
			old_identity: e.oldIdentity,
			new_device_id: e.newDeviceId,
			...e.mapping === void 0 ? {} : { mapping: e.mapping }
		});
	}
	async swapApply(e) {
		return this.send(O.swapApply, {
			old_identity: e.oldIdentity,
			new_device_id: e.newDeviceId,
			plan_token: e.planToken,
			...e.mapping === void 0 ? {} : { mapping: e.mapping },
			...e.acceptLossy ? { accept_lossy: !0 } : {}
		});
	}
	async send(e, t = {}) {
		try {
			return await this.hass.connection.sendMessagePromise({
				type: e,
				...t
			});
		} catch (e) {
			throw k.from(e);
		}
	}
};
//#endregion
//#region \0@oxc-project+runtime@0.148.0/helpers/esm/decorate.js
function j(e, t, n, r) {
	var i = arguments.length, a = i < 3 ? t : r === null ? r = Object.getOwnPropertyDescriptor(t, n) : r, o;
	if (typeof Reflect == "object" && typeof Reflect.decorate == "function") a = Reflect.decorate(e, t, n, r);
	else for (var s = e.length - 1; s >= 0; s--) (o = e[s]) && (a = (i < 3 ? o(a) : i > 3 ? o(t, n, a) : o(t, n)) || a);
	return i > 3 && a && Object.defineProperty(t, n, a), a;
}
//#endregion
//#region src/components/two-pane.ts
var it = class extends C {
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
		return v`
      <div class="pane ${e ? "hidden" : ""}"><slot name="list"></slot></div>
      <div class="pane ${t ? "hidden" : ""}"><slot name="detail"></slot></div>
    `;
	}
};
j([T({
	type: Boolean,
	reflect: !0
})], it.prototype, "narrow", void 0), j([T({
	type: Boolean,
	attribute: "show-detail"
})], it.prototype, "showDetail", void 0), it = j([w("dl-two-pane")], it);
//#endregion
//#region src/ha-components.ts
var at = [
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
], ot = {
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
}, st = 5e3, ct = class {
	constructor(e, t) {
		this.defined = e, this.missing = t;
	}
	has(e) {
		return this.defined.has(e);
	}
	tag(e) {
		return this.defined.has(e) ? e : ot[e] ?? "div";
	}
};
async function lt(e = at, t = {}) {
	let n = t.registry ?? globalThis.customElements;
	await ut(t.loadHelpers ?? (() => window.loadCardHelpers?.()));
	let r = t.timeoutMs ?? st, i = /* @__PURE__ */ new Set(), a = [];
	return await Promise.all(e.map(async (e) => {
		await dt(n, e, r) ? i.add(e) : a.push(e);
	})), a.sort(), a.length && console.warn(`Device Links: these Home Assistant components did not load, so plain elements are used instead: ${a.join(", ")}`), new ct(i, a);
}
async function ut(e) {
	try {
		let t = await e();
		if (!t) return;
		await (await t.createCardElement({
			type: "entities",
			entities: []
		})).constructor.getConfigElement?.();
	} catch {}
}
async function dt(e, t, n) {
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
var M = [
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
], ft = M[0]?.id ?? "overview";
function pt(e) {
	let t = (e ?? "").split("/").filter(Boolean)[0];
	return M.some((e) => e.id === t) ? t : ft;
}
//#endregion
//#region src/format.ts
var mt = {
	on_off: "On and off",
	level_set: "Brightness",
	level_hold: "Hold to dim",
	scene: "Scenes",
	color: "Colour",
	status_report: "Status feedback"
}, ht = {
	on_off: "mdi:power",
	level_set: "mdi:brightness-6",
	level_hold: "mdi:gesture-tap-hold",
	scene: "mdi:palette-outline",
	color: "mdi:invert-colors",
	status_report: "mdi:arrow-left-right"
}, gt = {
	zwave: "Z-Wave",
	zigbee2mqtt: "Zigbee",
	matter: "Matter"
}, _t = {
	remote: "Remote control",
	virtual_3way: "Virtual 3-way",
	scene_button: "Scene button",
	off_all: "Off all",
	status_feedback: "Status feedback",
	custom: "Custom"
}, vt = {
	remote: "One control drives one or more lights, on, off and dimming.",
	virtual_3way: "Two switches control each other, so either one works like the other.",
	scene_button: "A scene button sends one command to the devices you pick.",
	off_all: "One press turns a set of devices off.",
	status_feedback: "A device reports its state back to the control that drives it.",
	custom: "Choose the control, the targets and the features yourself."
}, yt = {
	in_sync: "In sync",
	drift: "Drift",
	pending: "Pending",
	blocked: "Blocked",
	disabled: "Disabled",
	unknown: "Unknown"
}, bt = {
	in_sync: "ok",
	drift: "error",
	pending: "warn",
	blocked: "error",
	disabled: "muted",
	unknown: "muted"
}, xt = {
	in_sync: "Every link this rule asks for is on the devices.",
	drift: "The devices do not hold what this rule asks for. Something changed them.",
	pending: "This rule has links waiting to be written. Plan and apply to write them.",
	blocked: "This rule compiles to nothing. Open it to see why.",
	disabled: "This rule is off, so its links are not on the devices.",
	unknown: "A device this rule uses could not be read, so its state cannot be judged."
}, St = {
	completed: "Completed",
	partial: "Partly done",
	cancelled: "Cancelled",
	interrupted: "Interrupted"
}, Ct = {
	completed: "ok",
	partial: "warn",
	cancelled: "muted",
	interrupted: "error"
}, wt = {
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
}, Tt = {
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
function N(e) {
	return mt[e] ?? e;
}
function Et(e) {
	return ht[e] ?? "mdi:link-variant";
}
function P(e) {
	return e === null ? "Unknown protocol" : gt[e] ?? e;
}
function F(e) {
	return _t[e] ?? e;
}
function Dt(e) {
	return vt[e] ?? "";
}
function I(e) {
	return yt[e] ?? e;
}
function Ot(e) {
	return bt[e] ?? "muted";
}
function kt(e) {
	return xt[e] ?? "";
}
function At(e) {
	return St[e] ?? e;
}
function jt(e) {
	return Ct[e] ?? "muted";
}
function Mt(e) {
	return wt[e] ?? e;
}
function Nt(e) {
	return Tt[e] ?? "muted";
}
function Pt(e, t) {
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
function Ft(e) {
	let t = e.name || e.identity;
	return e.endpoint === null || e.endpoint === 0 ? t : `${t} (endpoint ${e.endpoint})`;
}
function L(e) {
	return `${N(e.feature)} from ${Ft(e.source)} group ${e.emitter_group} to ${Ft(e.target)}`;
}
var It = {
	on_only: "turns on, and never off",
	off_only: "turns off, and never on",
	self_load: "turns off this device's own load",
	button_led: "keeps this button's LED in sync with"
};
function Lt(e) {
	let t = `${e.source.name} ${e.emitter_id}`;
	return e.kind === "self_load" ? `When ${t} is pressed, Home Assistant ${It[e.kind]}` : e.kind === "button_led" ? `Home Assistant ${It[e.kind]} ${e.target.name}, on ${t}` : `When ${t} is pressed, Home Assistant ${It[e.kind]} ${e.target.name}`;
}
function Rt(e) {
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
function zt(e, t) {
	let n = Rt(e);
	if (n === null) return e;
	let r = mt[n.feature] ?? n.feature, i = n.targetEndpoint ? `${t(n.target)} (endpoint ${n.targetEndpoint})` : t(n.target);
	return `${r} from ${t(n.source)} group ${n.group} to ${i}`;
}
function R(e, t, n) {
	return `${e} ${e === 1 ? t : n ?? `${t}s`}`;
}
function Bt(e, t) {
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
function Vt(e, t = Date.now()) {
	let n = new Date(e).getTime();
	if (Number.isNaN(n)) return "";
	let r = Math.max(0, Math.round((t - n) / 1e3));
	if (r < 60) return "just now";
	let i = Math.round(r / 60);
	if (i < 60) return `${R(i, "minute")} ago`;
	let a = Math.round(i / 60);
	return a < 24 ? `${R(a, "hour")} ago` : `${R(Math.round(a / 24), "day")} ago`;
}
//#endregion
//#region src/styles.ts
var z = o`
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
`, B = class extends C {
	constructor(...e) {
		super(...e), this.narrow = !1, this.selected = null, this.hybridAllowed = !1;
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
j([T({ attribute: !1 })], B.prototype, "hass", void 0), j([T({ attribute: !1 })], B.prototype, "api", void 0), j([T({ attribute: !1 })], B.prototype, "components", void 0), j([T({ type: Boolean })], B.prototype, "narrow", void 0), j([T({ attribute: !1 })], B.prototype, "selected", void 0), j([T({ type: Boolean })], B.prototype, "hybridAllowed", void 0);
//#endregion
//#region src/views/activity.ts
var V = class extends B {
	constructor(...e) {
		super(...e), this._jobs = [], this._running = null, this._selectedId = null, this._detail = null, this._devices = [], this._loading = !0, this._error = null, this._cancelling = !1, this._snapshots = [], this._rollingBack = null, this._comparing = null, this._activeProfileId = "", this._returning = [], this._unreadable = [], this._subscription = null;
	}
	static {
		this.styles = z;
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
		return v`
      <div class="content">
        ${this._error === null ? b : v`<div class="notice error" role="alert">${this._error}</div>`}
        ${this._renderRunning()}
        <dl-two-pane .narrow=${this.narrow} ?show-detail=${this._selectedId !== null}>
          <div slot="list" class="card">${this._renderList()}</div>
          <div slot="detail" class="card">${this._renderDetail()}</div>
        </dl-two-pane>
        ${this._renderSnapshots()}
      </div>
      <dl-plan-dialog
        .hass=${this.hass}
        .api=${this.api}
        .components=${this.components}
        .narrow=${this.narrow}
        .open=${this._rollingBack !== null}
        .flow=${this._rollbackFlow()}
        .heading=${"Restore a snapshot"}
        @dl-plan-closed=${this._closeRollback}
        @dl-plan-applied=${this._afterRollback}
      ></dl-plan-dialog>
      <dl-diff-dialog
        .hass=${this.hass}
        .api=${this.api}
        .narrow=${this.narrow}
        .open=${this._comparing !== null}
        .heading=${"What this snapshot holds that the active profile does not"}
        .profileId=${this._activeProfileId}
        .against=${this._comparing === null ? null : { snapshotId: this._comparing.id }}
        @dl-diff-closed=${() => {
			this._comparing = null;
		}}
      ></dl-diff-dialog>
    `;
	}
	_renderRunning() {
		let e = this._running;
		return e === null ? b : v`
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
		return this._loading ? v`<p class="secondary">Loading.</p>` : this._jobs.length === 0 ? v`<p class="empty">Nothing has been applied yet.</p>` : v`
      <h3>${R(this._jobs.length, "job")}</h3>
      <ul class="list">
        ${this._jobs.map((e) => v`
            <li>
              <button
                type="button"
                class="selectable"
                aria-current=${e.id === this._selectedId ? "true" : "false"}
                @click=${() => this._select(e.id)}
              >
                <span class="row">
                  <span class="chip ${jt(e.status)}">${At(e.status)}</span>
                  <span class="grow truncate">${e.scope}</span>
                </span>
                <span class="secondary">
                  ${Bt(e.created_at, this.hass?.language)} &middot;
                  ${R(e.total, "link")}
                </span>
              </button>
            </li>
          `)}
      </ul>
    `;
	}
	_renderDetail() {
		let e = this._detail;
		return e === null ? v`<p class="empty">Choose a job to see what it did.</p>` : v`
      ${this.narrow ? v`<button type="button" class="link" @click=${this._clear}>Back to the list</button>` : b}
      <div class="row" style="margin: 8px 0">
        <span class="chip ${jt(e.status)}">${At(e.status)}</span>
        <strong class="grow">${e.scope}</strong>
      </div>
      <p class="secondary">
        ${Bt(e.created_at, this.hass?.language)} (${Vt(e.created_at)}) &middot;
        ${R(e.total, "link")}
      </p>
      <div class="chips" style="margin-bottom: 12px">
        ${[...this._outcomeCounts(e)].map(([e, t]) => v`<span class="chip ${Nt(e)}">${Mt(e)} ${t}</span>`)}
      </div>
      ${e.results.length === 0 ? v`<p class="secondary">This job touched no links.</p>` : v`<ul class="list">${e.results.map((e) => this._renderResult(e))}</ul>`}
    `;
	}
	_renderResult(e) {
		return v`
      <li>
        <div class="row">
          <span class="chip ${Nt(e.status)}">${Mt(e.status)}</span>
          <span class="grow">${zt(e.fingerprint, (e) => this._nameOf(e))}</span>
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
		return this._snapshots.length === 0 ? b : v`
      <div class="card">
        <h3>Snapshots</h3>
        <p class="secondary">
          Taken before an apply, so what a device held can be put back. Restoring one shows
          you the whole plan first, and takes off what has been added since as well as
          putting back what has gone.
        </p>
        <div class="scroll-x">
          <table>
            <thead>
              <tr>
                <th>Taken</th>
                <th>Why</th>
                <th>Devices</th>
                <th>Links</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              ${this._snapshots.map((e) => v`
                  <tr>
                    <td>${Bt(e.created_at, this.hass?.language)}</td>
                    <td>${e.reason}</td>
                    <td>${e.devices.length}</td>
                    <td>${e.links}</td>
                    <td>
                      <button
                        type="button"
                        class="outlined"
                        @click=${() => this._openDiff(e)}
                      >
                        Compare
                      </button>
                      <button
                        type="button"
                        class="outlined"
                        @click=${() => this._openRollback(e)}
                      >
                        Restore
                      </button>
                    </td>
                  </tr>
                `)}
            </tbody>
          </table>
        </div>
      </div>
    `;
	}
	_openDiff(e) {
		this._comparing = e;
	}
	_openRollback(e) {
		this._forgetLastPlan(), this._rollingBack = e;
	}
	_closeRollback() {
		this._rollingBack = null, this._forgetLastPlan();
	}
	_forgetLastPlan() {
		this._returning = [], this._unreadable = [];
	}
	_afterRollback() {
		this._load();
	}
	_rollbackFlow() {
		let e = this._rollingBack, t = this.api;
		return e === null || !t ? null : {
			plan: async (n) => {
				let r = await t.rollbackSnapshot(e.id, { removeUnmanaged: n });
				return this._returning = r.returns_on_next_apply.map((e) => e.rule_name ?? "a rule"), this._unreadable = r.unreadable_devices, r.plan;
			},
			apply: async (n, r) => {
				let i = await t.rollbackSnapshot(e.id, {
					planToken: n,
					removeUnmanaged: r
				}), a = i.status === "preview" ? "nothing_to_do" : i.status;
				return {
					job_id: i.job_id,
					status: a
				};
			},
			notices: () => this._rollbackNotices()
		};
	}
	_rollbackNotices() {
		let e = [], t = [...new Set(this._returning)].sort();
		return t.length > 0 && e.push(`Some of these removals belong to rules that are still on: ${t.join(", ")}. They will be written again the next time those rules are applied, and until then those rules read as drifted. Turn a rule off first if you want its links gone for good.`), this._unreadable.length > 0 && e.push(`${R(this._unreadable.length, "device")} this snapshot covers cannot be read right now, so nothing is planned for them and whatever they hold stays as it is.`), e;
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
				let [e, t, n, r] = await Promise.all([
					this.api.listJobs(),
					this.api.listDevices(),
					this.api.listSnapshots(),
					this.api.listProfiles()
				]);
				if (this._jobs = e.jobs ?? [], this._running = e.running ?? null, this._devices = t ?? [], this._snapshots = n ?? [], this._activeProfileId = r.active_profile_id ?? "", this._error = null, this._selectedId === null && !this.narrow) {
					let e = this._jobs[0];
					e !== void 0 && this._select(e.id);
				}
			} catch (e) {
				this._error = A(this.hass, k.from(e));
			} finally {
				this._loading = !1;
			}
		}
	}
	_select(e) {
		this._selectedId = e, this._detail = this._jobs.find((t) => t.id === e) ?? null, this.api && this.api.getJob(e).then((t) => {
			this._selectedId === e && (this._detail = t);
		}).catch((e) => {
			this._error = A(this.hass, k.from(e));
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
			this._error = A(this.hass, e);
		}));
	}
	async _cancel() {
		if (this.api) {
			this._cancelling = !0;
			try {
				await this.api.cancelJob();
			} catch (e) {
				this._error = A(this.hass, k.from(e)), this._cancelling = !1;
			}
		}
	}
};
j([E()], V.prototype, "_jobs", void 0), j([E()], V.prototype, "_running", void 0), j([E()], V.prototype, "_selectedId", void 0), j([E()], V.prototype, "_detail", void 0), j([E()], V.prototype, "_devices", void 0), j([E()], V.prototype, "_loading", void 0), j([E()], V.prototype, "_error", void 0), j([E()], V.prototype, "_cancelling", void 0), j([E()], V.prototype, "_snapshots", void 0), j([E()], V.prototype, "_rollingBack", void 0), j([E()], V.prototype, "_comparing", void 0), j([E()], V.prototype, "_activeProfileId", void 0), j([E()], V.prototype, "_returning", void 0), j([E()], V.prototype, "_unreadable", void 0), V = j([w("device-links-activity")], V);
//#endregion
//#region src/components/dialog.ts
var H = class extends C {
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
		return this.open ? v`
      <div class="scrim" @click=${this._onScrim}></div>
      <div class="dialog" role="dialog" aria-modal="true" aria-label=${this.heading} tabindex="-1">
        <header>
          <h2>${this.heading}</h2>
          ${this.dismissible ? v`<button
                class="close"
                type="button"
                aria-label="Close"
                title="Close"
                @click=${this._close}
              >
                &#10005;
              </button>` : b}
        </header>
        <div class="body"><slot></slot></div>
        <footer><slot name="actions"></slot></footer>
      </div>
    ` : b;
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
j([T({
	type: Boolean,
	reflect: !0
})], H.prototype, "open", void 0), j([T({ type: String })], H.prototype, "heading", void 0), j([T({
	type: Boolean,
	reflect: !0
})], H.prototype, "narrow", void 0), j([T({ type: Boolean })], H.prototype, "dismissible", void 0), j([Ge(".dialog")], H.prototype, "_surface", void 0), H = j([w("dl-dialog")], H);
//#endregion
//#region src/dialogs/plan-dialog.ts
var U = class extends C {
	constructor(...e) {
		super(...e), this.components = null, this.narrow = !1, this.open = !1, this.heading = "Plan and apply", this.initialPlan = null, this.initialRemoveUnmanaged = [], this.flow = null, this._plan = null, this._phase = "loading", this._error = null, this._stale = !1, this._removeUnmanaged = [], this._progress = null, this._finished = null, this._cancelling = !1, this._jobId = null, this._subscription = null;
	}
	static {
		this.styles = [z, o`
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
		return v`
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
		return this._error === null ? this._phase === "loading" ? v`<p class="secondary">Working out what would change.</p>` : this._phase === "applying" ? this._renderProgress() : this._phase === "finished" ? this._renderResult() : this._renderPlan() : v`
        <div class="notice error" role="alert">
          <p>${this._error}</p>
          ${this._stale ? v`<p class="secondary">
                Nothing was written. Plan again to see what would happen now.
              </p>` : b}
        </div>
      `;
	}
	_renderPlan() {
		let e = this._plan;
		return e === null ? v`<p class="secondary">No plan yet.</p>` : e.is_empty && e.counts.unmanaged === 0 ? v`
        ${this._renderNotices(e)}
        <p>Nothing to do. Every link this covers is already on the devices.</p>
        ${e.unchanged_count > 0 ? v`<p class="secondary">
              ${R(e.unchanged_count, "link")} checked and left alone.
            </p>` : b}
      ` : v`
      ${this._renderNotices(e)} ${this._renderSummary(e)}
      ${e.devices.map((e) => this._renderDevice(e))}
      ${this._renderHybridLegs(e)}
    `;
	}
	_renderHybridLegs(e) {
		return e.hybrid_legs.length === 0 ? b : v`
      <section class="device">
        <header>
          <h3>Run by Home Assistant</h3>
          <span class="chip warn">HA-executed</span>
        </header>
        <p class="secondary">
          Already running, and not part of this apply. These stop working while Home
          Assistant is off; everything above is written into the devices and does not.
        </p>
        ${e.hybrid_legs.map((e) => v`<div class="item">${Lt(e)}</div>`)}
      </section>
    `;
	}
	_renderNotices(e) {
		let t = this.flow?.notices?.(e) ?? [];
		return t.length === 0 ? b : v`
      <div class="notice warn" role="note">
        ${t.map((e) => v`<p>${e}</p>`)}
      </div>
    `;
	}
	_renderSummary(e) {
		let t = e.counts;
		return v`
      <div class="summary">
        <p>
          ${R(this._changeCount(e), "change")} on
          ${R(e.devices.length, "device")}.
          ${e.unchanged_count > 0 ? v`<span class="secondary">
                ${R(e.unchanged_count, "link")} already correct.
              </span>` : b}
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
		return t === 0 ? b : v`<span class="chip ${n}">${e} ${t}</span>`;
	}
	_renderUnmanagedControls(e) {
		let t = this._selectableUnmanaged(e);
		if (t.length === 0) return b;
		if (!this._acceptsUnmanaged()) return v`
        <div class="notice">
          <p>
            ${R(t.length, "link")} on these devices belong to no rule. This
            job does not touch them, so they are listed and left exactly as they are.
          </p>
        </div>
      `;
		let n = this._removeUnmanaged.length;
		return v`
      <div class="notice">
        <p>
          ${R(t.length, "link")} on these devices belong to no rule. They are
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
		return v`
      <section class="device">
        <header>
          <h3>${e.name}</h3>
          <span class="chip muted">${P(e.backend)}</span>
          ${e.available ? b : v`<span class="chip warn" title="This device is not answering right now">
                Not answering
              </span>`}
        </header>
        ${e.available ? b : v`<p class="secondary">
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
		return t.length === 0 ? b : v`
      <div class="bucket">
        <h4>${e}</h4>
        ${t.map((e) => this._renderItem(e))}
      </div>
    `;
	}
	_renderItem(e) {
		let t = e.reason === null ? null : D(this.hass, e.reason);
		return v`
      <div class="item">
        <div>${this._describeItem(e)}</div>
        ${t === null ? b : v`<p class="reason">${t}</p>`}
        ${e.op === "pending" ? v`<p class="reason">
              Battery devices only accept changes while they are awake. Press a button on
              it, or wait for it to check in.
            </p>` : b}
      </div>
    `;
	}
	_describeItem(e) {
		if (e.link !== null) return L(e.link);
		if (e.setting !== null) {
			let t = e.setting, n = t.bitmask === null ? "" : ` (bitmask ${t.bitmask})`;
			return `Set ${t.capability}, parameter ${t.parameter}${n}, to ${t.value}`;
		}
		return "A change this panel has no wording for yet.";
	}
	_renderUnmanaged(e) {
		return e.length === 0 ? b : v`
      <div class="bucket">
        <h4>Not managed by any rule</h4>
        ${e.map((e) => this._renderUnmanagedLink(e))}
      </div>
    `;
	}
	_renderUnmanagedLink(e) {
		return e.is_system ? v`
        <div class="unmanaged-item">
          <span class="chip muted">System link</span>
          <span>${L(e)}</span>
        </div>
      ` : this._acceptsUnmanaged() ? v`
      <label class="unmanaged-item">
        <input
          type="checkbox"
          .checked=${this._removeUnmanaged.includes(e.fingerprint)}
          ?disabled=${this._phase !== "plan"}
          @change=${(t) => this._toggleUnmanaged(e, t)}
        />
        <span>
          Also remove: ${L(e)}
          ${e.ignored ? v`<span class="chip muted">Ignored</span>` : b}
        </span>
      </label>
    ` : v`
        <div class="unmanaged-item">
          <span class="chip muted">Left alone</span>
          <span>${L(e)}</span>
        </div>
      `;
	}
	_renderProgress() {
		let e = this._progress, t = e?.total ?? 0, n = e?.completed ?? 0;
		return v`
      <p>Writing to your devices. Leave this open until it finishes.</p>
      <div class="bar"><div style=${`width: ${t === 0 ? 0 : Math.round(n / t * 100)}%`}></div></div>
      <p class="secondary">
        ${t === 0 ? "Starting" : `${n} of ${t} done`}
        ${e?.devices_in_flight.length ? v`<span> &middot; now on ${e.devices_in_flight.join(", ")}</span>` : b}
      </p>
      ${this._cancelling ? v`<p class="secondary">
            Stopping. What is already in flight still finishes.
          </p>` : b}
    `;
	}
	_renderResult() {
		let e = this._finished;
		if (e === null) return v`<p>The job finished.</p>`;
		let t = Object.entries(e.results);
		return v`
      <div class="row">
        <span class="chip ${jt(e.status)}">${At(e.status)}</span>
        <span class="secondary">${R(e.total, "link")} attempted</span>
      </div>
      <div class="chips" style="margin-top: 12px">
        ${t.map(([e, t]) => v`<span class="chip ${Nt(e)}">
              ${Mt(e)} ${t}
            </span>`)}
      </div>
      ${e.status === "completed" ? b : v`<p class="secondary" style="margin-top: 12px">
            Activity has the per-link detail, including what each device said.
          </p>`}
    `;
	}
	_renderActions() {
		if (this._error !== null) return v`
        <button type="button" class="outlined" @click=${this._requestClose}>Close</button>
        <button type="button" class="primary" @click=${this._replan}>Plan again</button>
      `;
		if (this._phase === "applying") return v`
        <button type="button" class="danger" @click=${this._cancel} ?disabled=${this._cancelling}>
          Stop
        </button>
      `;
		if (this._phase === "finished") return v`
        <button type="button" class="outlined" @click=${this._replan}>Plan again</button>
        <button type="button" class="primary" @click=${this._requestClose}>Close</button>
      `;
		let e = this._plan === null ? 0 : this._changeCount(this._plan);
		return v`
      <button type="button" class="outlined" @click=${this._requestClose}>Cancel</button>
      <button
        type="button"
        class="primary"
        ?disabled=${this._phase !== "plan" || e === 0}
        @click=${this._apply}
      >
        ${e === 0 ? "Nothing to apply" : `Apply ${R(e, "change")}`}
      </button>
    `;
	}
	_acceptsUnmanaged() {
		return this.flow === null || this.flow.acceptsUnmanaged !== !1;
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
				this._plan = this.flow === null ? await this.api.plan(this.scope, this._removeUnmanaged) : await this.flow.plan(this._removeUnmanaged), this._phase = "plan";
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
				let t = this.flow === null ? await this.api.apply({
					planToken: e.token,
					...this.scope === void 0 ? {} : { scope: this.scope },
					removeUnmanaged: this._removeUnmanaged
				}) : await this.flow.apply(e.token, this._removeUnmanaged);
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
			this._error = A(this.hass, e);
		});
	}
	_unsubscribe() {
		this._subscription?.unsubscribe(), this._subscription = null;
	}
	_fail(e) {
		let t = k.from(e);
		this._error = A(this.hass, t), this._stale = t.translationKey === "plan_out_of_date", this._phase = "plan";
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
j([T({ attribute: !1 })], U.prototype, "hass", void 0), j([T({ attribute: !1 })], U.prototype, "api", void 0), j([T({ attribute: !1 })], U.prototype, "components", void 0), j([T({ type: Boolean })], U.prototype, "narrow", void 0), j([T({ type: Boolean })], U.prototype, "open", void 0), j([T({ attribute: !1 })], U.prototype, "scope", void 0), j([T({ type: String })], U.prototype, "heading", void 0), j([T({ attribute: !1 })], U.prototype, "initialPlan", void 0), j([T({ attribute: !1 })], U.prototype, "initialRemoveUnmanaged", void 0), j([T({ attribute: !1 })], U.prototype, "flow", void 0), j([E()], U.prototype, "_plan", void 0), j([E()], U.prototype, "_phase", void 0), j([E()], U.prototype, "_error", void 0), j([E()], U.prototype, "_stale", void 0), j([E()], U.prototype, "_removeUnmanaged", void 0), j([E()], U.prototype, "_progress", void 0), j([E()], U.prototype, "_finished", void 0), j([E()], U.prototype, "_cancelling", void 0), U = j([w("dl-plan-dialog")], U);
//#endregion
//#region src/dialogs/swap-wizard.ts
var W = [
	"old",
	"new",
	"mapping",
	"review"
], Ht = {
	old: "Which device has gone?",
	new: "What has replaced it?",
	mapping: "Which control takes over from which?",
	review: "What this would do"
}, Ut = {
	same_emitter_id: "The replacement has a control with the same id, so this is the same button.",
	same_features: "The only control on the replacement that carries everything the rules ask for.",
	chosen: "You chose this one.",
	unmapped: "Nothing on the replacement was an obvious match, so this is yours to pick."
}, G = class extends C {
	constructor(...e) {
		super(...e), this.components = null, this.narrow = !1, this.open = !1, this.devices = [], this.oldIdentity = null, this._step = "old", this._replacements = [], this._old = null, this._new = null, this._newEmitters = [], this._mapping = {}, this._preview = null, this._accepted = !1, this._busy = !1, this._error = null, this._planOpen = !1, this._search = "";
	}
	static {
		this.styles = [z, o`
      .picker {
        max-height: 320px;
        overflow-y: auto;
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        border-radius: 8px;
        padding: 4px;
      }

      .rewrite {
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        border-radius: 8px;
        padding: 10px 12px;
        margin-bottom: 8px;
      }

      .rewrite h4 {
        margin: 0 0 4px;
        overflow-wrap: anywhere;
      }

      .mapping {
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        border-radius: 8px;
        padding: 10px 12px;
        margin-bottom: 8px;
      }
    `];
	}
	willUpdate(e) {
		e.has("open") && this.open && this._begin();
	}
	render() {
		return v`
      <dl-dialog
        .open=${this.open && !this._planOpen}
        .narrow=${this.narrow}
        heading="Replace a device"
        @dl-dialog-closed=${this._close}
      >
        ${this._renderStep()}
        <div slot="actions">${this._renderActions()}</div>
      </dl-dialog>
      <dl-plan-dialog
        .hass=${this.hass}
        .api=${this.api}
        .components=${this.components}
        .narrow=${this.narrow}
        .open=${this._planOpen}
        .heading=${"Replace a device"}
        .flow=${this._flow()}
        @dl-plan-closed=${this._closePlan}
        @dl-plan-applied=${this._afterApply}
      ></dl-plan-dialog>
    `;
	}
	_renderStep() {
		return v`
      <p class="secondary">
        Step ${W.indexOf(this._step) + 1} of ${W.length}: ${Ht[this._step]}
      </p>
      ${this._error === null ? b : v`<div class="notice error" role="alert">${this._error}</div>`}
      ${this._step === "old" ? this._renderOldStep() : this._step === "new" ? this._renderNewStep() : this._step === "mapping" ? this._renderMappingStep() : this._renderReviewStep()}
    `;
	}
	_renderOldStep() {
		return this._busy ? v`<p class="secondary">Looking for devices your rules name that are not there.</p>` : this._replacements.length === 0 ? v`
        <p class="empty">
          Every device your rules name is on the network. Nothing needs replacing.
        </p>
      ` : v`
      <p class="secondary">
        These are devices the active profile's rules name that are not on the network, or
        that have come back answering as a different model.
      </p>
      <ul class="list">
        ${this._replacements.map((e) => v`
            <li>
              <button
                type="button"
                class="selectable"
                aria-current=${e.old.identity === this._old ? "true" : "false"}
                @click=${() => this._chooseOld(e)}
              >
                <span class="row">
                  <span class="grow">${e.old.name}</span>
                  <span class="chip muted">${P(e.old.backend)}</span>
                </span>
                <span class="chips" style="margin-top: 4px">
                  <span class="chip warn">
                    ${e.changed_in_place ? "Answering as a different model" : "Not on the network"}
                  </span>
                  <span class="chip muted">
                    ${R(e.rule_ids.length, "rule")} name it
                  </span>
                </span>
              </button>
            </li>
          `)}
      </ul>
    `;
	}
	_chooseOld(e) {
		this._old = e.old.identity, this._forget(), this._step = "new";
	}
	_forget() {
		this._new = null, this._newEmitters = [], this._mapping = {}, this._preview = null, this._accepted = !1;
	}
	_renderNewStep() {
		let e = this._replacements.find((e) => e.old.identity === this._old)?.candidates ?? [], t = this._filtered(this.devices.filter((t) => t.identity !== this._old && t.device_id !== null && !e.some((e) => e.identity === t.identity)));
		return v`
      ${e.length === 0 ? v`<p class="secondary">
            Nothing on the network looks like the device that has gone, so pick the
            replacement yourself. A different model is fine: the next step asks which of
            its controls takes over from which.
          </p>` : v`<p class="secondary">
            Same model as the device that has gone, and not named by any rule.
          </p>`}
      ${e.length === 0 ? b : v`<ul class="list">
            ${e.map((e) => this._renderCandidate(e))}
          </ul>`}
      <label class="field" style="margin: 8px 0">
        <span>Any other device</span>
        <input
          type="search"
          .value=${this._search}
          placeholder="Name or address"
          @input=${(e) => {
			this._search = e.target.value;
		}}
        />
      </label>
      <div class="picker">
        <ul class="list">${t.map((e) => this._renderCandidate(e))}</ul>
        ${t.length === 0 ? v`<p class="empty">No device matches that search.</p>` : b}
      </div>
    `;
	}
	_renderCandidate(e) {
		return v`
      <li>
        <button
          type="button"
          class="selectable"
          aria-current=${e.identity === this._new?.identity ? "true" : "false"}
          @click=${() => this._chooseNew(e)}
        >
          <span class="row">
            <span class="grow">${e.name}</span>
            <span class="chip muted">${P(e.backend)}</span>
            ${e.available ? b : v`<span class="chip warn">Not answering</span>`}
          </span>
        </button>
      </li>
    `;
	}
	_chooseNew(e) {
		this._new = e, this._mapping = {}, this._accepted = !1, this._loadReplacement(e);
	}
	_renderMappingStep() {
		let e = this._preview?.proposal;
		return this._busy || e === void 0 ? v`<p class="secondary">Working out what would take over from what.</p>` : e.errors.length > 0 ? v`
        ${e.errors.map((e) => v`<div class="notice error" role="alert">
            ${D(this.hass, e)}
          </div>`)}
      ` : e.mappings.length === 0 ? v`
        <p>
          No rule drives anything <em>from</em> ${e.old.name}, so there are no
          controls to map. The swap only has to re-point the rules that target it.
        </p>
      ` : v`
      ${e.same_model ? v`<p class="secondary">
            The replacement is the same model, so every control maps across on its own.
            Change any of them if this device is wired differently.
          </p>` : v`<p class="secondary">
            The replacement is a different model, so each control the rules use has to be
            matched to one on the new device.
          </p>`}
      ${e.mappings.map((e) => this._renderMapping(e))}
    `;
	}
	_renderMapping(e) {
		let t = e.features_needed.filter((t) => !e.features_carried.includes(t));
		return v`
      <div class="mapping">
        <div class="row">
          <strong class="grow">${e.old_emitter_id}</strong>
          <span class="chip muted">
            ${e.features_needed.map((e) => N(e)).join(", ")}
          </span>
        </div>
        <label class="field" style="margin-top: 6px">
          <span>Takes over from it</span>
          <select
            @change=${(t) => this._chooseMapping(e, t.target.value)}
          >
            <option value="" ?selected=${e.new_emitter_id === null}>
              Choose a control
            </option>
            ${this._newEmitters.filter((e) => !e.is_lifeline).map((t) => v`
                  <option
                    value=${t.emitter_id}
                    ?selected=${t.emitter_id === e.new_emitter_id}
                  >
                    ${t.label}
                  </option>
                `)}
          </select>
        </label>
        <p class="secondary" style="margin: 6px 0 0">${Ut[e.basis]}</p>
        ${t.length === 0 ? b : v`<p class="secondary">
              This control does not carry
              ${t.map((e) => N(e)).join(", ")}, so those parts of
              the rules using it stop working.
            </p>`}
      </div>
    `;
	}
	_chooseMapping(e, t) {
		let n = { ...this._mapping };
		t === "" ? delete n[e.old_emitter_id] : n[e.old_emitter_id] = t, this._mapping = n, this._accepted = !1, this._loadPreview();
	}
	_renderReviewStep() {
		let e = this._preview;
		if (this._busy || e === null) return v`<p class="secondary">Working out what this would do.</p>`;
		let t = e.proposal;
		return v`
      <p>
        <strong>${t.old.name}</strong> becomes
        <strong>${t.new.name}</strong> in
        ${R(t.rewrites.length, "rule")}.
      </p>
      ${this._renderReachability(e)}
      ${t.errors.map((e) => v`<div class="notice error" role="alert">
            <p>${D(this.hass, e)}</p>
          </div>`)}
      ${t.unmapped.length === 0 ? b : v`<div class="notice error" role="alert">
            <p>
              ${t.unmapped.join(", ")} still has nothing chosen to take over from it,
              so this swap cannot be applied. Go back and pick a control.
            </p>
          </div>`}
      ${t.rewrites.map((e) => this._renderRewrite(e))}
      ${this._renderLossGate(e)}
    `;
	}
	_renderReachability(e) {
		let t = [];
		return e.new_reachable || t.push(`${e.proposal.new.name} is not answering. Nothing can be written to it, so this swap would take the links off the old device and put none on the new one. It is refused until the replacement answers.`), e.old_reachable || t.push(e.old_listed ? `${e.proposal.old.name} is not answering, so the entries it still holds cannot be taken off. They stay on it until it comes back or is excluded from the network.` : `${e.proposal.old.name} has left the network, so nothing can be removed from it. Whatever it still holds stays there.`), t.length === 0 ? b : v`
      <div class="notice warn" role="status">${t.map((e) => v`<p>${e}</p>`)}</div>
    `;
	}
	_renderRewrite(e) {
		return v`
      <section class="rewrite">
        <h4>${e.name}</h4>
        ${e.is_lossy ? v`<span class="chip warn">Does less than it did</span>` : v`<span class="chip ok">Carried across whole</span>`}
        ${e.losses.map((e) => v`<p class="secondary">${D(this.hass, e)}</p>`)}
        ${e.notes.map((e) => v`<p class="secondary">${D(this.hass, e)}</p>`)}
        ${e.errors.map((e) => v`<p class="secondary">${D(this.hass, e)}</p>`)}
      </section>
    `;
	}
	_renderLossGate(e) {
		return e.proposal.is_lossy ? v`
      <label class="choice">
        <input
          type="checkbox"
          .checked=${this._accepted}
          @change=${(e) => {
			this._accepted = e.target.checked;
		}}
        />
        <span>
          I have read what these rules will no longer do, and I want to swap anyway.
        </span>
      </label>
    ` : b;
	}
	_renderActions() {
		let e = W.indexOf(this._step), t = e === 0 || e === 1 && this.oldIdentity !== null ? b : v`<button type="button" class="outlined" @click=${() => this._goTo(e - 1)}>
          Back
        </button>`;
		return this._step === "review" ? v`
        <button type="button" class="outlined" @click=${this._close}>Cancel</button>
        ${t}
        <button
          type="button"
          class="primary"
          ?disabled=${!this._canApply()}
          @click=${() => {
			this._planOpen = !0;
		}}
        >
          Show the plan
        </button>
      ` : v`
      <button type="button" class="outlined" @click=${this._close}>Cancel</button>
      ${t}
      <button
        type="button"
        class="primary"
        ?disabled=${!this._canLeave()}
        @click=${() => this._goTo(e + 1)}
      >
        Next
      </button>
    `;
	}
	_canLeave() {
		return this._step === "old" ? this._old !== null : this._step === "new" ? this._new !== null : this._preview !== null && this._preview.proposal.unmapped.length === 0;
	}
	_canApply() {
		let e = this._preview;
		return e === null || !e.proposal.is_applicable || !e.new_reachable ? !1 : !e.proposal.is_lossy || this._accepted;
	}
	_goTo(e) {
		let t = W[Math.min(Math.max(e, 0), W.length - 1)];
		t !== void 0 && (this._step = t, (t === "mapping" || t === "review") && this._loadPreview());
	}
	_begin() {
		this._error = null, this._preview = null, this._new = null, this._newEmitters = [], this._mapping = {}, this._accepted = !1, this._search = "", this._old = this.oldIdentity, this._step = this.oldIdentity === null ? "old" : "new", this._loadCandidates();
	}
	async _loadCandidates() {
		if (this.api) {
			this._busy = !0;
			try {
				this._replacements = await this.api.swapCandidates(), this._error = null;
			} catch (e) {
				this._error = A(this.hass, k.from(e));
			} finally {
				this._busy = !1;
			}
		}
	}
	async _loadReplacement(e) {
		if (this.api && e.device_id !== null) {
			this._busy = !0;
			try {
				this._newEmitters = (await this.api.getDevice(e.device_id)).emitters, this._error = null;
			} catch (e) {
				this._error = A(this.hass, k.from(e));
			} finally {
				this._busy = !1;
			}
		}
	}
	async _loadPreview() {
		let e = this._old, t = this._new;
		if (this.api && e !== null && t?.device_id != null) {
			this._busy = !0;
			try {
				this._preview = await this.api.swapPreview({
					oldIdentity: e,
					newDeviceId: t.device_id,
					mapping: this._mapping
				}), this._error = null;
			} catch (e) {
				this._preview = null, this._error = A(this.hass, k.from(e));
			} finally {
				this._busy = !1;
			}
		}
	}
	_flow() {
		let e = this.api, t = this._old, n = this._new;
		if (!e || t === null || n?.device_id == null) return null;
		let r = n.device_id, i = this._mapping;
		return {
			plan: async () => {
				let n = await e.swapPreview({
					oldIdentity: t,
					newDeviceId: r,
					mapping: i
				});
				return this._losses(n) !== this._losses(this._preview) && (this._accepted = !1), this._preview = n, n.plan;
			},
			apply: async (n) => {
				let a = await e.swapApply({
					oldIdentity: t,
					newDeviceId: r,
					planToken: n,
					mapping: i,
					acceptLossy: this._accepted
				});
				return {
					job_id: a.job_id,
					status: a.status
				};
			},
			notices: () => this._planNotices(),
			acceptsUnmanaged: !1
		};
	}
	_losses(e) {
		return (e?.proposal.rewrites ?? []).flatMap((e) => e.losses.map((e) => e.translation_key)).sort().join("|");
	}
	_planNotices() {
		let e = this._preview;
		if (e === null) return [];
		let t = [];
		return e.removes.length > 0 && !e.old_reachable && t.push(`${R(e.removes.length, "link")} on ${e.proposal.old.name} cannot be removed, because it is not answering. The rules are re-pointed either way.`), e.proposal.is_lossy && t.push("Some of these rules will do less than they did. You confirmed that on the previous screen."), t;
	}
	_filtered(e) {
		let t = this._search.trim().toLowerCase();
		return t ? e.filter((e) => `${e.name} ${e.protocol_id}`.toLowerCase().includes(t)) : e;
	}
	_closePlan() {
		this._planOpen = !1;
	}
	_afterApply() {
		this._planOpen = !1, this.dispatchEvent(new CustomEvent("dl-swap-applied", {
			bubbles: !0,
			composed: !0
		}));
	}
	_close() {
		this.dispatchEvent(new CustomEvent("dl-swap-closed", {
			bubbles: !0,
			composed: !0
		}));
	}
};
j([T({ attribute: !1 })], G.prototype, "hass", void 0), j([T({ attribute: !1 })], G.prototype, "api", void 0), j([T({ attribute: !1 })], G.prototype, "components", void 0), j([T({ type: Boolean })], G.prototype, "narrow", void 0), j([T({ type: Boolean })], G.prototype, "open", void 0), j([T({ attribute: !1 })], G.prototype, "devices", void 0), j([T({ attribute: !1 })], G.prototype, "oldIdentity", void 0), j([E()], G.prototype, "_step", void 0), j([E()], G.prototype, "_replacements", void 0), j([E()], G.prototype, "_old", void 0), j([E()], G.prototype, "_new", void 0), j([E()], G.prototype, "_newEmitters", void 0), j([E()], G.prototype, "_mapping", void 0), j([E()], G.prototype, "_preview", void 0), j([E()], G.prototype, "_accepted", void 0), j([E()], G.prototype, "_busy", void 0), j([E()], G.prototype, "_error", void 0), j([E()], G.prototype, "_planOpen", void 0), j([E()], G.prototype, "_search", void 0), G = j([w("dl-swap-wizard")], G);
//#endregion
//#region src/components/icon.ts
function Wt(e, t) {
	return e?.has("ha-icon") ? v`<ha-icon .icon=${t} aria-hidden="true"></ha-icon>` : b;
}
//#endregion
//#region src/views/devices.ts
var K = class extends B {
	constructor(...e) {
		super(...e), this._devices = [], this._detail = null, this._selectedId = null, this._search = "", this._loading = !0, this._busy = !1, this._error = null, this._confidence = "cached", this._incoming = null, this._incomingState = "idle", this._planOpen = !1, this._planRemove = [], this._planHeading = "Plan and apply", this._swapping = null, this._linkIndex = [], this._ignored = /* @__PURE__ */ new Set();
	}
	static {
		this.styles = z;
	}
	connectedCallback() {
		super.connectedCallback(), this._load();
	}
	willUpdate(e) {
		e.has("selected") && this.selected !== null && this._select(this.selected);
	}
	render() {
		return v`
      <div class="content">
        ${this._error === null ? b : v`<div class="notice error" role="alert">${this._error}</div>`}
        <dl-two-pane .narrow=${this.narrow} ?show-detail=${this._selectedId !== null}>
          <div slot="list" class="card">${this._renderList()}</div>
          <div slot="detail" class="card">${this._renderDetail()}</div>
        </dl-two-pane>
      </div>
      <dl-swap-wizard
        .hass=${this.hass}
        .api=${this.api}
        .components=${this.components}
        .narrow=${this.narrow}
        .open=${this._swapping !== null}
        .devices=${this._devices}
        .oldIdentity=${this._swapping === "" ? null : this._swapping}
        @dl-swap-closed=${this._closeSwap}
        @dl-swap-applied=${this._afterSwap}
      ></dl-swap-wizard>
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
		return v`
      <button
        type="button"
        class="outlined"
        style="margin-bottom: 8px"
        @click=${() => {
			this._swapping = "";
		}}
      >
        Replace a device that has gone
      </button>
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
      ${this._loading ? v`<p class="secondary">Loading.</p>` : e.length === 0 ? v`<p class="empty">No device matches that search.</p>` : v`
              <ul class="list">
                ${e.map((e) => this._renderListRow(e))}
              </ul>
            `}
    `;
	}
	_renderListRow(e) {
		return v`
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
            <span class="chip muted">${P(e.backend)}</span>
          </span>
          <span class="chips" style="margin-top: 4px">
            <span class="chip muted">${R(e.links, "link")}</span>
            <span class="chip muted">${R(e.emitters, "control")}</span>
            ${e.available ? b : v`<span class="chip warn">Not answering</span>`}
            ${e.is_long_range ? v`<span class="chip error">Long Range</span>` : b}
            ${e.device_id === null ? v`<span class="chip muted">No Home Assistant device</span>` : b}
          </span>
        </button>
      </li>
    `;
	}
	_renderDetail() {
		let e = this._detail;
		if (e === null) return v`<p class="empty">Choose a device to see what is on it.</p>`;
		let t = e.device;
		return v`
      ${this.narrow ? v`<button type="button" class="link" @click=${this._clear}>Back to the list</button>` : b}
      <div class="spread" style="margin-top: 8px">
        <div class="grow">
          <h2>${t.name}</h2>
          <div class="chips">
            <span class="chip muted">${P(t.backend)}</span>
            <span class="chip muted">${t.protocol_id}</span>
            ${t.available ? b : v`<span class="chip warn">Not answering</span>`}
            ${t.is_long_range ? v`<span class="chip error">Long Range</span>` : b}
          </div>
        </div>
        <div class="row">
          <button type="button" class="outlined" ?disabled=${this._busy} @click=${() => this._refresh(!1)}>
            Refresh
          </button>
          <button type="button" class="outlined" ?disabled=${this._busy} @click=${() => this._refresh(!0)}>
            Deep verify
          </button>
          <button
            type="button"
            class="outlined"
            @click=${() => {
			this._swapping = t.identity;
		}}
          >
            Replace device
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
		return e.available ? this._confidence === "confirmed" ? v`
        <div class="notice">
          <p>Read from the device itself just now.</p>
        </div>
      ` : this._confidence === "unconfirmed" ? v`
        <div class="notice warn">
          <p>
            The deep verify did not come back confirmed. The device may have been asleep or
            simply did not report a value, so what follows is still the last known state
            rather than a fresh reading. It is not evidence that anything is wrong.
          </p>
        </div>
      ` : v`
      <p class="secondary">
        From the driver's cache. Deep verify reads the device itself.
      </p>
    ` : v`
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
		return v`
      <h3 style="margin-top: 16px">Outgoing</h3>
      <p class="secondary">What this device sends, and to whom.</p>
      ${e.emitters.length === 0 ? v`<p class="secondary">This device offers no controls that reach another device.</p>` : e.emitters.map((n) => this._renderEmitter(e, n, t))}
      ${this._renderOrphans(e, t)}
    `;
	}
	_renderEmitter(e, t, n) {
		let r = new Set(t.group_ids.length ? t.group_ids : Object.values(t.actions).filter((e) => e !== void 0)), i = e.links.filter((e) => r.has(e.emitter_group));
		for (let e of i) n.add(e.fingerprint);
		let a = Pt(t, e.links), o = Object.keys(t.actions);
		return v`
      <div class="card" style="margin-top: 8px">
        <div class="row">
          <strong class="grow">${t.label}</strong>
          ${t.is_lifeline ? v`<span class="chip muted" title="Device Links never writes to a lifeline">
                System link
              </span>` : b}
          ${a === null ? b : v`<span class="chip ${a.free === 0 ? "warn" : "muted"}">
                ${a.used} of ${a.capacity} used in group ${a.group}
              </span>`}
        </div>
        <div class="chips" style="margin: 6px 0">
          ${o.map((e) => v`<span class="chip">
                ${Wt(this.components, Et(e))}${N(e)}
              </span>`)}
          ${t.semantics === "unknown" ? v`<span class="chip warn" title="What this control sends has not been observed">
                Unverified
              </span>` : b}
        </div>
        ${i.length === 0 ? v`<p class="secondary">Nothing on it.</p>` : v`<ul class="list">${i.map((e) => this._renderEntry(e))}</ul>`}
      </div>
    `;
	}
	_renderOrphans(e, t) {
		let n = e.links.filter((e) => !t.has(e.fingerprint));
		return n.length === 0 ? b : v`
      <div class="card" style="margin-top: 8px">
        <div class="row">
          <strong class="grow">Other groups</strong>
          <span class="chip muted">${R(n.length, "entry", "entries")}</span>
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
		return v`
      <li>
        <div class="spread">
          <div class="grow">
            <div class="row">
              <span>${Ft(e.target)}</span>
              <span class="chip muted">${N(e.feature)}</span>
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
		return e.is_system || !t ? b : v`
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
		return v`
      <h3 style="margin-top: 16px">Incoming</h3>
      <p class="secondary">What reaches this device from somewhere else.</p>
      ${this._incomingState === "loading" ? v`<p class="secondary">Reading every device to find what controls this one.</p>` : this._incomingState === "error" ? v`<p class="secondary">
              The other devices could not all be read, so this list may be short.
            </p>` : b}
      ${this._renderIncomingList(t)}
    `;
	}
	_renderIncomingList(e) {
		let t = (this._incoming ?? []).filter((t) => t.target.identity === e);
		return this._incomingState === "loading" ? v`` : t.length === 0 ? v`<p class="secondary">Nothing controls this device over the radio.</p>` : v`
      <ul class="list">
        ${t.map((e) => v`
            <li>
              <div class="row">
                <span class="grow">${Ft(e.source)}</span>
                <span class="chip muted">group ${e.emitter_group}</span>
                <span class="chip muted">${N(e.feature)}</span>
                ${e.is_system ? v`<span class="chip muted">System link</span>` : b}
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
		return t.length === 0 ? b : v`
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
            ${t.map(([e, t]) => v`
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
				this._error = A(this.hass, k.from(e));
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
				this._error = A(this.hass, k.from(e));
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
				this._error = A(this.hass, k.from(e));
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
				this._error = A(this.hass, k.from(e));
			} finally {
				this._busy = !1;
			}
		}
	}
	_planRemoval(e) {
		let t = this._detail?.device.device_id;
		this._planScope = t == null ? void 0 : { device_ids: [t] }, this._planRemove = [e.fingerprint], this._planHeading = `Remove a link from ${this._detail?.device.name ?? "this device"}`, this._planOpen = !0;
	}
	_closeSwap() {
		this._swapping = null;
	}
	_afterSwap() {
		this._swapping = null, this._linkIndex = [], this._incomingState = "idle", this._load(), this._selectedId !== null && this._select(this._selectedId);
	}
	_closePlan() {
		this._planOpen = !1, this._planRemove = [];
	}
	_afterApply() {
		this._load(), this._selectedId !== null && this._select(this._selectedId);
	}
};
j([E()], K.prototype, "_devices", void 0), j([E()], K.prototype, "_detail", void 0), j([E()], K.prototype, "_selectedId", void 0), j([E()], K.prototype, "_search", void 0), j([E()], K.prototype, "_loading", void 0), j([E()], K.prototype, "_busy", void 0), j([E()], K.prototype, "_error", void 0), j([E()], K.prototype, "_confidence", void 0), j([E()], K.prototype, "_incoming", void 0), j([E()], K.prototype, "_incomingState", void 0), j([E()], K.prototype, "_planOpen", void 0), j([E()], K.prototype, "_planScope", void 0), j([E()], K.prototype, "_planRemove", void 0), j([E()], K.prototype, "_planHeading", void 0), j([E()], K.prototype, "_swapping", void 0), K = j([w("device-links-devices")], K);
//#endregion
//#region src/views/overview.ts
var Gt = [
	"blocked",
	"drift",
	"pending",
	"unknown"
], Kt = [
	"in_sync",
	"drift",
	"pending",
	"blocked",
	"disabled",
	"unknown"
], q = class extends B {
	constructor(...e) {
		super(...e), this._profile = null, this._rules = [], this._devices = [], this._jobs = [], this._loading = !0, this._error = null, this._verifying = !1, this._verifiedAt = null, this._verifiedDevices = 0, this._planOpen = !1, this._planHeading = "Plan and apply";
	}
	static {
		this.styles = z;
	}
	connectedCallback() {
		super.connectedCallback(), this._load();
	}
	render() {
		return v`
      <div class="content">
        ${this._error === null ? b : v`<div class="notice error" role="alert">${this._error}</div>`}
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
		return v`
      <div class="card">
        <div class="spread">
          <div class="grow">
            <h2>${this._profile?.name ?? "No profile is active"}</h2>
            <p class="secondary">
              ${this._profile === null ? "Activate a profile in the Profiles tab, or make one there." : `${R(this._profile.rules, "rule")}, ${this._profile.enabled_rules} enabled.`}
            </p>
            <div class="chips">
              ${Kt.map((t) => (e.get(t) ?? 0) === 0 ? b : v`<span class="chip ${Ot(t)}" title=${kt(t)}>
                      ${I(t)} ${e.get(t)}
                    </span>`)}
              ${this._loading ? v`<span class="chip muted">Loading</span>` : this._rules.length === 0 ? v`<span class="chip muted">No rules yet</span>` : b}
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
          ${this._verifiedAt === null ? "Verify reads every device in the active profile and changes nothing." : `Verified ${Vt(this._verifiedAt)}: ${R(this._verifiedDevices, "device")} re-read.`}
        </p>
      </div>
    `;
	}
	_renderAttention() {
		let e = this._rules.filter((e) => Gt.includes(e.state)), t = this._devices.filter((e) => !e.available);
		return e.length === 0 && t.length === 0 ? v`
        <div class="card">
          <h3>Needs attention</h3>
          <p class="secondary">
            ${this._loading ? "Looking." : "Nothing. Every rule holds what it asks for, and every device answered."}
          </p>
        </div>
      ` : v`
      <div class="card">
        <h3>Needs attention</h3>
        <ul class="list">
          ${e.slice().sort((e, t) => Gt.indexOf(e.state) - Gt.indexOf(t.state)).map((e) => this._renderAttentionRule(e))}
          ${t.length === 0 ? b : v`
                <li>
                  <div class="spread">
                    <div class="grow">
                      <div class="row">
                        <span class="chip warn">Not answering</span>
                        <strong>${R(t.length, "device")}</strong>
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
		return v`
      <li>
        <div class="spread">
          <div class="grow">
            <div class="row">
              <span class="chip ${Ot(e.state)}">${I(e.state)}</span>
              <strong>${e.rule.name}</strong>
            </div>
            <p class="secondary" style="margin: 4px 0 0">
              ${kt(e.state)}
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
		return v`
      <div class="card">
        <div class="spread">
          <h3>Recent activity</h3>
          <button type="button" class="link" @click=${() => this.goTo("activity")}>
            See all
          </button>
        </div>
        ${this._jobs.length === 0 ? v`<p class="secondary">Nothing has been applied yet.</p>` : v`
              <ul class="list">
                ${this._jobs.slice(0, 5).map((e) => v`
                    <li>
                      <button
                        type="button"
                        class="selectable"
                        @click=${() => this.goTo("activity", e.id)}
                      >
                        <span class="row">
                          <span class="chip ${jt(e.status)}">
                            ${At(e.status)}
                          </span>
                          <span class="grow truncate">${e.scope}</span>
                          <span class="secondary">${R(e.total, "link")}</span>
                          <span class="secondary">${Bt(e.created_at, this.hass?.language)}</span>
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
				this._error = A(this.hass, k.from(e));
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
				this._error = A(this.hass, k.from(e));
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
j([E()], q.prototype, "_profile", void 0), j([E()], q.prototype, "_rules", void 0), j([E()], q.prototype, "_devices", void 0), j([E()], q.prototype, "_jobs", void 0), j([E()], q.prototype, "_loading", void 0), j([E()], q.prototype, "_error", void 0), j([E()], q.prototype, "_verifying", void 0), j([E()], q.prototype, "_verifiedAt", void 0), j([E()], q.prototype, "_verifiedDevices", void 0), j([E()], q.prototype, "_planOpen", void 0), j([E()], q.prototype, "_planScope", void 0), j([E()], q.prototype, "_planHeading", void 0), q = j([w("device-links-overview")], q);
//#endregion
//#region src/dialogs/diff-dialog.ts
var qt = {
	added: {
		label: "Added",
		tone: "ok"
	},
	removed: {
		label: "Removed",
		tone: "warn"
	},
	changed: {
		label: "Changed",
		tone: "info"
	},
	unchanged: {
		label: "Unchanged",
		tone: "muted"
	}
}, J = class extends C {
	constructor(...e) {
		super(...e), this.narrow = !1, this.open = !1, this.heading = "Compare", this.profileId = "", this.against = null, this._diff = null, this._error = null, this._loading = !1, this._showUnchanged = !1;
	}
	static {
		this.styles = [z, o`
      .rule {
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        border-radius: 8px;
        padding: 10px 12px;
        margin-bottom: 8px;
      }

      .rule header {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
      }

      .rule h4 {
        margin: 0;
        flex: 1;
        overflow-wrap: anywhere;
      }

      .change {
        padding: 2px 0;
        overflow-wrap: anywhere;
      }
    `];
	}
	willUpdate(e) {
		e.has("open") && (this.open ? this._load() : (this._diff = null, this._error = null, this._showUnchanged = !1));
	}
	render() {
		return v`
      <dl-dialog
        .open=${this.open}
        .narrow=${this.narrow}
        .heading=${this.heading}
        @dl-dialog-closed=${this._close}
      >
        ${this._renderBody()}
        <div slot="actions">
          <button type="button" class="primary" @click=${this._close}>Close</button>
        </div>
      </dl-dialog>
    `;
	}
	_renderBody() {
		if (this._error !== null) return v`<div class="notice error" role="alert">${this._error}</div>`;
		if (this._loading) return v`<p class="secondary">Working out what differs.</p>`;
		let e = this._diff;
		return e === null ? v`<p class="secondary">Nothing compared yet.</p>` : e.is_empty ? v`
        <p>These two describe the same thing. Nothing would change.</p>
        ${this._renderScope(e)}
      ` : v`
      ${this._renderSummary(e)} ${this._renderScope(e)} ${this._renderRules(e)}
      ${this._renderLinks(e)}
    `;
	}
	_renderSummary(e) {
		let t = e.counts;
		return v`
      <div class="chips" style="margin-bottom: 12px">
        ${this._chip("Rules added", t.rules_added)}
        ${this._chip("Rules removed", t.rules_removed)}
        ${this._chip("Rules changed", t.rules_changed)}
        ${this._chip("Links added", t.links_added)}
        ${this._chip("Links removed", t.links_removed)}
      </div>
    `;
	}
	_chip(e, t) {
		return t ? v`<span class="chip info">${e} ${t}</span>` : b;
	}
	_renderScope(e) {
		return e.devices.length === 0 ? b : v`
      <p class="secondary">
        This snapshot covers ${R(e.devices.length, "device")}, so it is the whole
        of what this comparison can speak for. Nothing here says anything about the rest of
        your network.
      </p>
    `;
	}
	_renderRules(e) {
		let t = e.rules.filter((e) => e.kind !== "unchanged");
		return t.length === 0 ? b : v`
      <h3>Rules</h3>
      ${t.map((e) => this._renderRule(e))}
    `;
	}
	_renderRule(e) {
		let t = qt[e.kind];
		return v`
      <section class="rule">
        <header>
          <h4>${e.name}</h4>
          <span class="chip ${t.tone}">${t.label}</span>
          ${e.writes_nothing_new && e.kind === "changed" ? v`<span class="chip muted" title="Nothing would be written to a device">
                No device change
              </span>` : b}
        </header>
        ${e.fields.length === 0 ? b : v`<p class="secondary">Different: ${e.fields.join(", ")}.</p>`}
        ${e.links_added.map((e) => v`<div class="change">
            <span class="chip ok">Add</span> ${L(e)}
          </div>`)}
        ${e.links_removed.map((e) => v`<div class="change">
            <span class="chip warn">Remove</span> ${L(e)}
          </div>`)}
        ${e.links_unchanged > 0 ? v`<p class="secondary">
              ${R(e.links_unchanged, "link")} the same on both sides.
            </p>` : b}
      </section>
    `;
	}
	_renderLinks(e) {
		let t = e.links.filter((e) => this._showUnchanged || e.kind !== "unchanged");
		if (e.links.length === 0) return b;
		let n = e.links.length - e.links.filter((e) => e.kind !== "unchanged").length;
		return v`
      <h3 style="margin-top: 12px">Links</h3>
      <p class="secondary">What would actually be written to the devices.</p>
      ${t.map((e) => this._renderLink(e))}
      ${n === 0 ? b : v`<button
            type="button"
            class="link"
            @click=${() => {
			this._showUnchanged = !this._showUnchanged;
		}}
          >
            ${this._showUnchanged ? "Hide the links that are the same" : `Show ${R(n, "link")} that are the same`}
          </button>`}
    `;
	}
	_renderLink(e) {
		let t = qt[e.kind];
		return v`
      <div class="change">
        <span class="chip ${t.tone}">${t.label}</span> ${L(e.link)}
      </div>
    `;
	}
	async _load() {
		let e = this.against;
		if (this.api && this.profileId !== "" && e !== null) {
			this._loading = !0, this._error = null;
			try {
				this._diff = await this.api.diffProfile(this.profileId, e);
			} catch (e) {
				this._error = A(this.hass, k.from(e));
			} finally {
				this._loading = !1;
			}
		}
	}
	_close() {
		this.dispatchEvent(new CustomEvent("dl-diff-closed", {
			bubbles: !0,
			composed: !0
		}));
	}
};
j([T({ attribute: !1 })], J.prototype, "hass", void 0), j([T({ attribute: !1 })], J.prototype, "api", void 0), j([T({ type: Boolean })], J.prototype, "narrow", void 0), j([T({ type: Boolean })], J.prototype, "open", void 0), j([T({ type: String })], J.prototype, "heading", void 0), j([T({ type: String })], J.prototype, "profileId", void 0), j([T({ attribute: !1 })], J.prototype, "against", void 0), j([E()], J.prototype, "_diff", void 0), j([E()], J.prototype, "_error", void 0), j([E()], J.prototype, "_loading", void 0), j([E()], J.prototype, "_showUnchanged", void 0), J = j([w("dl-diff-dialog")], J);
//#endregion
//#region src/views/profiles.ts
var Y = class extends B {
	constructor(...e) {
		super(...e), this._profiles = [], this._loading = !0, this._busy = !1, this._error = null, this._sheet = "none", this._subject = null, this._text = "", this._exported = "", this._planOpen = !1, this._plan = null, this._planHeading = "Plan and apply", this._diffAgainst = null;
	}
	static {
		this.styles = z;
	}
	connectedCallback() {
		super.connectedCallback(), this._load();
	}
	render() {
		return v`
      <div class="content">
        ${this._error === null ? b : v`<div class="notice error" role="alert">${this._error}</div>`}
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
      <dl-diff-dialog
        .hass=${this.hass}
        .api=${this.api}
        .narrow=${this.narrow}
        .open=${this._diffAgainst !== null}
        .heading=${`Compare ${this._subject?.name ?? ""} with ${this._nameOf(this._diffAgainst)}`}
        .profileId=${this._subject?.id ?? ""}
        .against=${this._diffAgainst === null ? null : { profileId: this._diffAgainst }}
        @dl-diff-closed=${() => {
			this._diffAgainst = null;
		}}
      ></dl-diff-dialog>
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
		return this._loading ? v`<p class="secondary">Loading.</p>` : this._profiles.length === 0 ? v`<p class="empty">No profiles yet.</p>` : v`
      <ul class="list">
        ${this._profiles.map((e) => this._renderRow(e))}
      </ul>
    `;
	}
	_renderRow(e) {
		return v`
      <li>
        <div class="spread">
          <div class="grow">
            <div class="row">
              <strong>${e.name}</strong>
              ${e.is_active ? v`<span class="chip ok">Active</span>` : b}
            </div>
            <p class="secondary" style="margin: 4px 0 0">
              ${R(e.rules, "rule")}, ${e.enabled_rules} enabled.
            </p>
          </div>
          <div class="row">
            ${e.is_active ? v`<button type="button" class="outlined" @click=${() => this.goTo("rules")}>
                  Open rules
                </button>` : v`<button
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
              ?disabled=${this._busy || this._profiles.length < 2}
              title=${this._profiles.length < 2 ? "There is only one profile, so there is nothing to compare it with." : ""}
              @click=${() => this._open("compare", e)}
            >
              Compare
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
		return v`
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
        .open=${this._sheet === "compare"}
        .narrow=${this.narrow}
        .heading=${`Compare ${this._subject?.name ?? ""} with`}
        @dl-dialog-closed=${this._closeSheet}
      >
        <p class="secondary">
          Nothing is written and nothing is activated. This only says what would differ.
        </p>
        <ul class="list">
          ${this._profiles.filter((e) => e.id !== this._subject?.id).map((e) => v`
                <li>
                  <button
                    type="button"
                    class="selectable"
                    @click=${() => this._compareWith(e)}
                  >
                    <span class="row">
                      <span class="grow">${e.name}</span>
                      <span class="chip muted">${R(e.rules, "rule")}</span>
                    </span>
                  </button>
                </li>
              `)}
        </ul>
        <div slot="actions">
          <button type="button" class="outlined" @click=${this._closeSheet}>Cancel</button>
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
				this._error = A(this.hass, k.from(e));
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
			this._error = A(this.hass, k.from(e));
		} finally {
			this._busy = !1;
		}
	}
	async _create() {
		let e = this._text.trim();
		await this._run(async () => {
			await this.api.createProfile({
				id: Jt(),
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
	_compareWith(e) {
		this._sheet = "none", this._diffAgainst = e.id;
	}
	_nameOf(e) {
		return this._profiles.find((t) => t.id === e)?.name ?? "";
	}
	_closePlan() {
		this._planOpen = !1, this._plan = null, this._load();
	}
	_afterApply() {
		this._load();
	}
};
j([E()], Y.prototype, "_profiles", void 0), j([E()], Y.prototype, "_loading", void 0), j([E()], Y.prototype, "_busy", void 0), j([E()], Y.prototype, "_error", void 0), j([E()], Y.prototype, "_sheet", void 0), j([E()], Y.prototype, "_subject", void 0), j([E()], Y.prototype, "_text", void 0), j([E()], Y.prototype, "_exported", void 0), j([E()], Y.prototype, "_planOpen", void 0), j([E()], Y.prototype, "_plan", void 0), j([E()], Y.prototype, "_planHeading", void 0), j([E()], Y.prototype, "_diffAgainst", void 0), Y = j([w("device-links-profiles")], Y);
function Jt() {
	let e = globalThis.crypto?.randomUUID?.();
	return e ? e.replace(/-/g, "") : `profile${Date.now().toString(36)}`;
}
//#endregion
//#region src/components/loops.ts
function Yt(e) {
	return e.length === 0 ? b : v`
    ${e.map((e) => v`
        <div class="notice warn" role="status">
          <p>
            <strong>Possible loop.</strong>
            ${e.devices.map((e) => e.name).join(", ")}
            can pass a command round between them: each one is set to repeat what it
            receives to its own associations, and together their links form a circle.
          </p>
          <p class="secondary">
            ${e.rule_names.length === 0 ? "No rule of this profile joins them, so the links that close the circle came from somewhere else." : `Made by: ${e.rule_names.join(", ")}.`}
            This is a warning, not a refusal. Turning off "make the control's own load
            follow the press" on any one of these devices breaks the circle, and so does
            making one of the rules one way.
          </p>
        </div>
      `)}
  `;
}
//#endregion
//#region src/dialogs/rule-editor.ts
var X = [
	"template",
	"source",
	"targets",
	"behaviour",
	"review"
], Xt = {
	template: "What should this do?",
	source: "Which control drives it?",
	targets: "What should it control?",
	behaviour: "How should it behave?",
	review: "What this will do"
}, Zt = [
	"on_off",
	"level_set",
	"level_hold",
	"scene",
	"color",
	"status_report"
], Qt = {
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
}, $t = [
	{
		value: "on_only",
		needs: "scene_id",
		label: "Only pass on, never off",
		help: "An association carries on and off together, so Home Assistant does this part: it hears the button press and turns the targets on."
	},
	{
		value: "off_only",
		needs: "scene_id",
		label: "Only pass off, never on",
		help: "The same the other way round. Home Assistant hears the press and turns the targets off."
	},
	{
		value: "self_load",
		needs: "scene_id",
		label: "Also turn off this device's own load",
		help: "A device cannot be in its own association group, so Home Assistant turns this device's own load off when the button is pressed. Add the device to the targets as well."
	},
	{
		value: "button_led",
		needs: "indicator_id",
		label: "Keep this button's LED in sync with the target",
		help: "Nothing on the radio can address one button's LED, so Home Assistant watches the target and lights the button to match."
	}
], en = [
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
];
function tn(e) {
	let { device: t, endpoint: n, emitter_id: r } = e.source;
	return t === "" || r === "" || n === null || e.targets.length === 0 ? null : {
		...e,
		source: {
			device: t,
			endpoint: n,
			emitter_id: r
		}
	};
}
var Z = class extends C {
	constructor(...e) {
		super(...e), this.components = null, this.narrow = !1, this.open = !1, this.devices = [], this.rule = null, this.initialTemplate = null, this.hybridAllowed = !1, this._draft = null, this._step = "template", this._sourceDetail = null, this._loadingSource = !1, this._compiled = null, this._validating = !1, this._saving = !1, this._error = null, this._search = "";
	}
	static {
		this.styles = [z, o`
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
		return v`
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
		if (e === null) return v`<p class="secondary">Loading.</p>`;
		let t = X.indexOf(this._step);
		return v`
      ${this.narrow ? v`<p class="secondary">
            Step ${t + 1} of ${X.length}: ${Xt[this._step]}
          </p>` : v`<ol class="steps">
            ${X.map((e, t) => v`
                <li aria-current=${e === this._step ? "step" : "false"}>
                  ${t + 1}. ${Xt[e]}
                </li>
              `)}
          </ol>`}
      ${this._error === null ? b : v`<div class="notice error" role="alert">${this._error}</div>`}
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
		return v`
      <div class="template-grid">
        ${Object.keys(Qt).map((t) => v`
            <button
              type="button"
              class="template-card"
              aria-pressed=${e.template === t ? "true" : "false"}
              @click=${() => this._chooseTemplate(t)}
            >
              <strong>${F(t)}</strong>
              <span class="secondary">${Dt(t)}</span>
            </button>
          `)}
      </div>
    `;
	}
	_chooseTemplate(e) {
		let t = Qt[e];
		this._update({
			template: e,
			features: [...t.features],
			direction: t.direction,
			mirror_source: t.mirror,
			name: this._draft?.name || F(e)
		}), this._step = "source";
	}
	_renderSourceStep(e) {
		let t = this._deviceFor(e.source.device);
		return t === null ? v`
        ${this._renderSearch()}
        <div class="picker">${this._renderDeviceList(this._sourceCandidates(), (e) => this._chooseSource(e))}</div>
      ` : v`
      <div class="row" style="margin-bottom: 12px">
        <strong>${t.name}</strong>
        <span class="chip muted">${P(t.backend)}</span>
        <button type="button" class="link" @click=${() => this._clearSource()}>
          Choose a different device
        </button>
      </div>
      ${this._loadingSource ? v`<p class="secondary">Reading what this device offers.</p>` : this._renderEmitters(e)}
    `;
	}
	_renderEmitters(e) {
		let t = this._sourceDetail?.emitters ?? [];
		return t.length === 0 ? v`<p class="secondary">
        This device reports no controls that can drive another device.
      </p>` : v`
      <div>
        ${t.map((t) => this._renderEmitter(e, t))}
      </div>
    `;
	}
	_renderEmitter(e, t) {
		if (t.is_lifeline) return v`
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
		return v`
      <button
        type="button"
        class="emitter"
        aria-pressed=${r ? "true" : "false"}
        @click=${() => this._chooseEmitter(t)}
      >
        <div class="row">
          <strong>${t.label}</strong>
          ${n === null ? b : v`<span class="chip ${n.free === 0 ? "warn" : "muted"}">
                ${n.used} of ${n.capacity} used in group ${n.group}
              </span>`}
          ${t.semantics === "unknown" ? v`<span class="chip warn">Unverified</span>` : b}
        </div>
        <div class="chips" style="margin-top: 6px">
          ${i.map((e) => v`<span class="chip">
              ${Wt(this.components, Et(e))}${N(e)}
            </span>`)}
        </div>
        ${n !== null && n.free === 0 ? v`<p class="secondary" style="margin: 6px 0 0">
              This group is full. Anything added here is blocked until an entry comes off it.
            </p>` : b}
      </button>
    `;
	}
	_usage(e) {
		return Pt(e, this._sourceDetail?.links ?? []);
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
				this._error = A(this.hass, k.from(e));
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
				endpoint: e.endpoint,
				emitter_id: e.emitter_id
			},
			features: r.length ? r : n.slice(0, 1)
		});
	}
	_renderTargetsStep(e) {
		let t = new Set(e.targets.map((e) => e.device)), n = this._filtered(this.devices.filter((t) => t.identity !== e.source.device)), r = this._selectedEmitter(e), i = r === null ? null : this._usage(r);
		return v`
      ${i !== null && t.size > i.free ? v`<div class="notice warn">
            <p>
              ${R(i.free, "entry", "entries")} free in group ${i.group}, and
              ${R(t.size, "target")} chosen. The ones that do not fit are blocked
              rather than written, and the plan will say which.
            </p>
          </div>` : b}
      ${this._renderSearch()}
      <div class="picker">
        <ul class="list">
          ${n.map((e) => v`
              <li>
                <label class="choice">
                  <input
                    type="checkbox"
                    .checked=${t.has(e.identity)}
                    @change=${(t) => this._toggleTarget(e, t)}
                  />
                  <span class="grow">
                    <span>${e.name}</span>
                    <span class="chip muted">${P(e.backend)}</span>
                    ${e.receiving_endpoint === null ? b : v`<span class="chip muted">
                          Endpoint ${e.receiving_endpoint}
                        </span>`}
                    ${e.available ? b : v`<span class="chip warn">Not answering</span>`}
                    ${e.is_long_range ? v`<span class="chip error">Long Range</span>` : b}
                  </span>
                </label>
              </li>
            `)}
        </ul>
        ${n.length === 0 ? v`<p class="empty">No device matches that search.</p>` : b}
      </div>
    `;
	}
	_toggleTarget(e, t) {
		let n = this._draft;
		if (n === null) return;
		let r = t.target.checked, i = n.targets.filter((t) => t.device !== e.identity);
		r && i.push({
			device: e.identity,
			endpoint: e.receiving_endpoint
		}), this._update({ targets: i });
	}
	_renderBehaviourStep(e) {
		let t = this._selectedEmitter(e), n = t?.actions ?? {};
		return v`
      <label class="field" style="margin-bottom: 16px">
        <span>Name</span>
        <input
          type="text"
          .value=${e.name}
          @input=${(e) => this._update({ name: e.target.value })}
        />
      </label>

      <h3>What it sends</h3>
      ${Zt.map((r) => {
			let i = n[r], a = i !== void 0;
			return v`
          <label class="choice ${a ? "" : "disabled"}">
            <input
              type="checkbox"
              .checked=${e.features.includes(r)}
              ?disabled=${!a}
              @change=${(e) => this._toggleFeature(r, e)}
            />
            <span>
              <span>${N(r)}</span>
              ${a ? v`<span class="secondary"> (group ${i})</span>` : v`<span class="secondary">
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
      ${en.map((t) => v`
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
      ${this._renderHybridSection(e)}
    `;
	}
	_renderHybridSection(e) {
		if (!this.hybridAllowed) return b;
		let t = this._selectedEmitter(e), n = $t.filter((e) => t !== null && t[e.needs] !== null);
		return v`
      <h3 style="margin-top: 16px">
        Run in Home Assistant <span class="chip warn">HA-executed</span>
      </h3>
      <p class="secondary">
        These are the parts no radio can carry. Home Assistant does them, so they stop
        working while Home Assistant is off or restarting. The rest of this rule is written
        into the devices and keeps working either way.
      </p>
      ${n.length === 0 ? v`<p class="secondary">
            ${t === null ? "Choose a control first." : `${t.label} does not report a scene number or a button LED that Device Links knows how to use, so none of these can be offered for it.`}
          </p>` : n.map((t) => this._renderHybridChoice(e, t))}
    `;
	}
	_renderHybridChoice(e, t) {
		let n = {
			on_only: "off_only",
			off_only: "on_only"
		};
		return v`
      <label class="choice">
        <input
          type="checkbox"
          .checked=${e.hybrid.includes(t.value)}
          @change=${(e) => this._toggleHybrid(t.value, n[t.value], e)}
        />
        <span>
          <span>${t.label}</span>
          <span class="chip warn">HA-executed</span>
          <span class="secondary" style="display: block">${t.help}</span>
        </span>
      </label>
    `;
	}
	_toggleHybrid(e, t, n) {
		let r = this._draft;
		if (r === null) return;
		let i = n.target.checked, a = r.hybrid.filter((n) => n !== e && n !== t);
		i && a.push(e), this._update({ hybrid: a });
	}
	_renderSettingPreview() {
		let e = this._compiled?.settings ?? [];
		return e.length === 0 ? b : v`
      <div class="notice">
        ${e.map((e) => v`<p>
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
		return v`
      <div class="notice">
        <p>
          <strong>${e.name}</strong>, ${F(e.template)}, from
          ${this._nameOf(e.source.device)} to
          ${e.targets.map((e) => this._nameOf(e.device)).join(", ") || "nothing yet"}.
        </p>
      </div>
      ${this._validating ? v`<p class="secondary">Compiling.</p>` : b}
      ${t === null ? b : this._renderDiagnostics(t)}
      ${t === null ? b : this._renderCompiled(t)}
    `;
	}
	_renderDiagnostics(e) {
		return v`
      ${e.errors.map((e) => v`<div class="notice error" role="alert">
          <p><strong>Problem.</strong> ${D(this.hass, e)}</p>
        </div>`)}
      ${e.warnings.map((e) => v`<div class="notice warn" role="status">
          <p><strong>Warning.</strong> ${D(this.hass, e)}</p>
        </div>`)}
      ${e.errors.length > 0 ? v`<p class="secondary">
            This rule compiles to no links, so there is nothing to apply. You can still save
            it: it will show as blocked in the rules table until whatever is wrong is fixed.
          </p>` : b}
      ${Yt(e.loops)}
    `;
	}
	_renderCompiled(e) {
		return e.links.length === 0 ? v`
        <p>No links written to devices.</p>
        ${this._renderHybridLegs(e)}
      ` : v`
      <h3>${R(e.links.length, "link")}</h3>
      <ul class="list">
        ${e.links.map((e) => v`<li>${L(e)}</li>`)}
      </ul>
      ${e.settings.length === 0 ? b : v`
            <h3 style="margin-top: 12px">Device settings</h3>
            <ul class="list">
              ${e.settings.map((e) => v`<li>
                  ${e.capability}: parameter ${e.parameter}
                  ${e.bitmask === null ? "" : `(bitmask ${e.bitmask})`} set to
                  ${e.value}
                </li>`)}
            </ul>
          `}
      ${this._renderHybridLegs(e)}
    `;
	}
	_renderHybridLegs(e) {
		return e.hybrid_legs.length === 0 ? b : v`
      <h3 style="margin-top: 12px">
        ${R(e.hybrid_legs.length, "HA-executed leg")}
      </h3>
      <p class="secondary">
        Run by Home Assistant, not written to a device. These stop working while Home
        Assistant is off; everything above keeps working.
      </p>
      <ul class="list">
        ${e.hybrid_legs.map((e) => v`<li>
            <span class="chip warn">HA-executed</span> ${Lt(e)}
          </li>`)}
      </ul>
    `;
	}
	_renderSearch() {
		return v`
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
		return e.length === 0 ? v`<p class="empty">No device matches that search.</p>` : v`
      <ul class="list">
        ${e.map((e) => v`
            <li>
              <button type="button" class="selectable" @click=${() => t(e)}>
                <span class="row">
                  <span class="grow">${e.name}</span>
                  <span class="chip muted">${P(e.backend)}</span>
                  <span class="chip muted">${R(e.emitters, "control")}</span>
                  ${e.available ? b : v`<span class="chip warn">Not answering</span>`}
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
		if (e === null) return v`<button type="button" class="outlined" @click=${this._close}>Close</button>`;
		if (this._step === "review") {
			let e = (this._compiled?.errors.length ?? 0) > 0;
			return v`
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
		return v`
      <button type="button" class="outlined" @click=${this._close}>Cancel</button>
      ${t === 0 ? b : v`<button type="button" class="outlined" @click=${() => this._goTo(t - 1)}>
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
			let e = this.initialTemplate ?? "remote", t = Qt[e];
			this._draft = {
				id: nn(),
				name: this.initialTemplate === null ? "" : F(e),
				template: e,
				backend: "zwave",
				enabled: !0,
				direction: t.direction,
				mirror_source: t.mirror,
				features: [...t.features],
				hybrid: [],
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
			hybrid: [...this.rule.hybrid ?? []],
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
		if (!this.api || e === null) return;
		let t = tn(e);
		if (t === null) {
			this._compiled = null;
			return;
		}
		this._validating = !0, this.api.validateRule(t).then((e) => {
			this._compiled = e, this._error = null;
		}).catch((e) => {
			this._error = A(this.hass, k.from(e));
		}).finally(() => {
			this._validating = !1;
		});
	}
	async _save(e) {
		let t = this._draft;
		if (!this.api || t === null) return;
		let n = tn(t);
		if (n === null) {
			this._error = "This rule still needs a control and at least one target.";
			return;
		}
		this._saving = !0, this._error = null;
		try {
			await this.api.upsertRule(n, this.profileId), this.dispatchEvent(new CustomEvent("dl-rule-saved", {
				detail: {
					rule: n,
					apply: e
				},
				bubbles: !0,
				composed: !0
			}));
		} catch (e) {
			this._error = A(this.hass, k.from(e));
		} finally {
			this._saving = !1;
		}
	}
	_close() {
		this.dispatchEvent(new CustomEvent("dl-editor-closed", {
			bubbles: !0,
			composed: !0
		}));
	}
};
j([T({ attribute: !1 })], Z.prototype, "hass", void 0), j([T({ attribute: !1 })], Z.prototype, "api", void 0), j([T({ attribute: !1 })], Z.prototype, "components", void 0), j([T({ type: Boolean })], Z.prototype, "narrow", void 0), j([T({ type: Boolean })], Z.prototype, "open", void 0), j([T({ attribute: !1 })], Z.prototype, "devices", void 0), j([T({ attribute: !1 })], Z.prototype, "rule", void 0), j([T({ type: String })], Z.prototype, "profileId", void 0), j([T({ attribute: !1 })], Z.prototype, "initialTemplate", void 0), j([T({ type: Boolean })], Z.prototype, "hybridAllowed", void 0), j([E()], Z.prototype, "_draft", void 0), j([E()], Z.prototype, "_step", void 0), j([E()], Z.prototype, "_sourceDetail", void 0), j([E()], Z.prototype, "_loadingSource", void 0), j([E()], Z.prototype, "_compiled", void 0), j([E()], Z.prototype, "_validating", void 0), j([E()], Z.prototype, "_saving", void 0), j([E()], Z.prototype, "_error", void 0), j([E()], Z.prototype, "_search", void 0), Z = j([w("dl-rule-editor")], Z);
function nn() {
	let e = globalThis.crypto?.randomUUID?.();
	return e ? e.replace(/-/g, "") : `rule${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
}
//#endregion
//#region src/views/rules.ts
var rn = [
	"remote",
	"virtual_3way",
	"scene_button",
	"off_all",
	"status_feedback",
	"custom"
], an = [
	"in_sync",
	"drift",
	"pending",
	"blocked",
	"disabled",
	"unknown"
], Q = class extends B {
	constructor(...e) {
		super(...e), this._profile = null, this._rules = [], this._loops = [], this._devices = [], this._templates = [...rn], this._emitterLabels = {}, this._loading = !0, this._error = null, this._search = "", this._backendFilter = "", this._stateFilter = "", this._editorOpen = !1, this._editing = null, this._editorTemplate = null, this._planOpen = !1, this._planHeading = "Plan and apply", this._confirmDelete = null, this._staged = null, this._appliedDuringPlan = !1;
	}
	static {
		this.styles = z;
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
		return v`
      <div class="content">
        ${this._error === null ? b : v`<div class="notice error" role="alert">${this._error}</div>`}
        ${Yt(this._loops)}
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
        .hybridAllowed=${this.hybridAllowed}
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
		return v`
      <div class="spread">
        <div class="grow">
          <h2>Rules</h2>
          <p class="secondary">
            ${this._profile === null ? "No profile is active, so no rule is in force." : `In ${this._profile.name}. ${R(this._rules.length, "rule")}.`}
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
            ${an.map((e) => v`<option value=${e}>${I(e)}</option>`)}
          </select>
        </label>
      </div>
    `;
	}
	_renderBody() {
		if (this._loading) return v`<p class="secondary">Loading.</p>`;
		if (this._rules.length === 0) return this._renderEmpty();
		let e = this._filtered();
		return e.length === 0 ? v`<p class="empty">No rule matches those filters.</p>` : this.narrow ? v`<ul class="list">${e.map((e) => this._renderCard(e))}</ul>` : v`
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
		return v`
      <li>
        <div class="row">
          <strong class="grow">${t.name}</strong>
          <span class="chip ${Ot(e.state)}" title=${kt(e.state)}>
            ${I(e.state)}
          </span>
        </div>
        <p class="secondary" style="margin: 4px 0">
          ${this._nameOf(t.source.device)},
          ${this._emitterLabel(t.source.device, t.source.emitter_id)} to
          ${t.targets.map((e) => this._nameOf(e.device)).join(", ")}
        </p>
        <div class="chips" style="margin-bottom: 8px">
          <span class="chip muted">${F(t.template)}</span>
          ${t.features.map((e) => v`<span class="chip">
              ${Wt(this.components, Et(e))}${N(e)}
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
		return v`
      <tr>
        <td>
          <strong>${t.name}</strong>
          <div class="chips" style="margin-top: 4px">
            <span class="chip muted">${F(t.template)}</span>
            <span class="chip muted">${P(t.backend)}</span>
          </div>
        </td>
        <td>
          <div>${this._nameOf(t.source.device)}</div>
          <div class="secondary">${this._emitterLabel(t.source.device, t.source.emitter_id)}</div>
        </td>
        <td>
          <div class="chips">
            ${t.targets.map((e) => v`<span class="chip">${this._nameOf(e.device)}</span>`)}
          </div>
        </td>
        <td>
          <div class="chips">
            ${t.features.map((e) => v`<span class="chip" title=${N(e)}>
                ${Wt(this.components, Et(e))}${N(e)}
              </span>`)}
          </div>
          ${t.direction === "two_way" ? v`<span class="secondary">Two way</span>` : b}
        </td>
        <td>
          <span class="chip ${Ot(e.state)}" title=${kt(e.state)}>
            ${I(e.state)}
          </span>
          ${e.links_total > 0 ? v`<div class="secondary">${e.links_in_sync} of ${e.links_total} links</div>` : b}
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
		return v`
      <p>No rules yet. Start from what you want the control to do.</p>
      <div
        class="chips"
        style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 8px"
      >
        ${this._templates.map((e) => v`
            <button
              type="button"
              class="selectable"
              style="border-color: var(--divider-color, rgba(0, 0, 0, 0.12))"
              @click=${() => this._openEditor(null, e)}
            >
              <strong>${F(e)}</strong>
              <div class="secondary">${Dt(e)}</div>
            </button>
          `)}
      </div>
    `;
	}
	_renderDeleteConfirm() {
		let e = this._confirmDelete;
		return v`
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
				this._profile = r;
				let i = r === null ? null : await this.api.getProfile(r.id);
				this._rules = i?.rules ?? [], this._loops = i?.loops ?? [], this._error = null, this._loadEmitterLabels();
			} catch (e) {
				this._error = A(this.hass, k.from(e));
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
			this._error = A(this.hass, k.from(e)), await this._load();
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
			this._error = A(this.hass, k.from(e));
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
				this._error = A(this.hass, k.from(e));
			}
		}
	}
};
j([E()], Q.prototype, "_profile", void 0), j([E()], Q.prototype, "_rules", void 0), j([E()], Q.prototype, "_loops", void 0), j([E()], Q.prototype, "_devices", void 0), j([E()], Q.prototype, "_templates", void 0), j([E()], Q.prototype, "_emitterLabels", void 0), j([E()], Q.prototype, "_loading", void 0), j([E()], Q.prototype, "_error", void 0), j([E()], Q.prototype, "_search", void 0), j([E()], Q.prototype, "_backendFilter", void 0), j([E()], Q.prototype, "_stateFilter", void 0), j([E()], Q.prototype, "_editorOpen", void 0), j([E()], Q.prototype, "_editing", void 0), j([E()], Q.prototype, "_editorTemplate", void 0), j([E()], Q.prototype, "_planOpen", void 0), j([E()], Q.prototype, "_planScope", void 0), j([E()], Q.prototype, "_planHeading", void 0), j([E()], Q.prototype, "_confirmDelete", void 0), Q = j([w("device-links-rules")], Q);
//#endregion
//#region src/panel.ts
var on = "0.0.1", $ = class extends C {
	constructor(...e) {
		super(...e), this.narrow = !1, this.componentLoader = () => lt(), this._components = null, this._selected = null, this._api = null;
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
		return pt(this.route?.path);
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
		this.hass && (this._api === null ? this._api = new rt(this.hass) : this._api.hass = this.hass);
	}
	async _loadComponents() {
		this._components === null && (this._components = await this.componentLoader());
	}
	render() {
		return v`
      ${this._renderBar()}
      ${this._renderVersionBanner()}
      ${this._components === null ? v`<div class="loading">Loading Home Assistant components</div>` : this._renderView()}
    `;
	}
	_renderBar() {
		let e = this._components;
		return e?.has("ha-top-app-bar-fixed") ? v`
      <ha-top-app-bar-fixed>
        ${e.has("ha-menu-button") ? v`<ha-menu-button
              slot="navigationIcon"
              .hass=${this.hass}
              .narrow=${this.narrow}
            ></ha-menu-button>` : b}
        <div slot="title">Device Links</div>
        ${this._renderTabs()}
      </ha-top-app-bar-fixed>
    ` : v`
        <header class="plain-bar">
          <span>Device Links</span>
        </header>
        ${this._renderTabs()}
      `;
	}
	_renderTabs() {
		let e = this._components;
		return !e?.has("ha-tab-group") || !e.has("ha-tab-group-tab") ? v`
        <nav class="plain-tabs" aria-label="Device Links sections">
          ${M.map((e) => v`
              <button
                type="button"
                aria-current=${e.id === this.tab ? "page" : "false"}
                @click=${() => this._selectTab(e.id)}
              >
                ${e.label}
              </button>
            `)}
        </nav>
      ` : v`
      <ha-tab-group slot="tabs" aria-label="Device Links sections">
        ${M.map((t) => v`
            <ha-tab-group-tab
              slot="nav"
              panel=${t.id}
              .active=${t.id === this.tab}
              @click=${() => this._selectTab(t.id)}
            >
              ${this.narrow && e.has("ha-icon") ? v`<ha-icon .icon=${t.icon} aria-label=${t.label}></ha-icon>` : t.label}
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
	get hybridAllowed() {
		return this.panel?.config?.hybrid_legs === !0;
	}
	get versionMismatch() {
		let e = this.backendVersion;
		return e !== null && e !== "0.0.1";
	}
	_renderVersionBanner() {
		if (!this.versionMismatch) return b;
		let e = `Device Links was updated to ${this.backendVersion} while this page was open. This panel is still running version ${on}. Reload the page to pick up the new one.`;
		return this._components?.has("ha-alert") ? v`
        <ha-alert class="banner" alert-type="info" title="A newer version is installed">
          ${e}
          <button type="button" slot="action" @click=${() => this._reload()}>Reload</button>
        </ha-alert>
      ` : v`
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
		let e = M.find((e) => e.id === this.tab) ?? M[0];
		return e ? Xe`
      <${Je(e.tagName)}
        class="view"
        .hass=${this.hass}
        .api=${this._api}
        .components=${this._components}
        .narrow=${this.narrow}
        .selected=${this._selected}
        .hybridAllowed=${this.hybridAllowed}
        @dl-navigate=${this._onNavigate}
      ></${Je(e.tagName)}>
    ` : v`<div class="loading">No view is registered.</div>`;
	}
	_onNavigate(e) {
		let t = e.detail;
		t?.tab && this._selectTab(t.tab, t.select ?? null);
	}
};
j([T({ attribute: !1 })], $.prototype, "hass", void 0), j([T({
	type: Boolean,
	reflect: !0
})], $.prototype, "narrow", void 0), j([T({ attribute: !1 })], $.prototype, "route", void 0), j([T({ attribute: !1 })], $.prototype, "panel", void 0), j([T({ attribute: !1 })], $.prototype, "componentLoader", void 0), j([E()], $.prototype, "_components", void 0), j([E()], $.prototype, "_selected", void 0), $ = j([w("device-links-panel")], $);
//#endregion
export { on as BUNDLE_VERSION, $ as DeviceLinksPanel };
