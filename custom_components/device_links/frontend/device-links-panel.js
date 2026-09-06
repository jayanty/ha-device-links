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
})(e) : e, { is: l, defineProperty: u, getOwnPropertyDescriptor: d, getOwnPropertyNames: ee, getOwnPropertySymbols: te, getPrototypeOf: ne } = Object, f = globalThis, re = f.trustedTypes, ie = re ? re.emptyScript : "", ae = f.reactiveElementPolyfillSupport, p = (e, t) => e, m = {
	toAttribute(e, t) {
		switch (t) {
			case Boolean:
				e = e ? ie : null;
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
}, h = (e, t) => !l(e, t), g = {
	attribute: !0,
	type: String,
	converter: m,
	reflect: !1,
	useDefault: !1,
	hasChanged: h
};
Symbol.metadata ??= Symbol("metadata"), f.litPropertyMetadata ??= /* @__PURE__ */ new WeakMap();
var _ = class extends HTMLElement {
	static addInitializer(e) {
		this._$Ei(), (this.l ??= []).push(e);
	}
	static get observedAttributes() {
		return this.finalize(), this._$Eh && [...this._$Eh.keys()];
	}
	static createProperty(e, t = g) {
		if (t.state && (t.attribute = !1), this._$Ei(), this.prototype.hasOwnProperty(e) && ((t = Object.create(t)).wrapped = !0), this.elementProperties.set(e, t), !t.noAccessor) {
			let n = Symbol(), r = this.getPropertyDescriptor(e, n, t);
			r !== void 0 && u(this.prototype, e, r);
		}
	}
	static getPropertyDescriptor(e, t, n) {
		let { get: r, set: i } = d(this.prototype, e) ?? {
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
		return this.elementProperties.get(e) ?? g;
	}
	static _$Ei() {
		if (this.hasOwnProperty(p("elementProperties"))) return;
		let e = ne(this);
		e.finalize(), e.l !== void 0 && (this.l = [...e.l]), this.elementProperties = new Map(e.elementProperties);
	}
	static finalize() {
		if (this.hasOwnProperty(p("finalized"))) return;
		if (this.finalized = !0, this._$Ei(), this.hasOwnProperty(p("properties"))) {
			let e = this.properties, t = [...ee(e), ...te(e)];
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
			let i = (n.converter?.toAttribute === void 0 ? m : n.converter).toAttribute(t, n.type);
			this._$Em = e, i == null ? this.removeAttribute(r) : this.setAttribute(r, i), this._$Em = null;
		}
	}
	_$AK(e, t) {
		let n = this.constructor, r = n._$Eh.get(e);
		if (r !== void 0 && this._$Em !== r) {
			let e = n.getPropertyOptions(r), i = typeof e.converter == "function" ? { fromAttribute: e.converter } : e.converter?.fromAttribute === void 0 ? m : e.converter;
			this._$Em = r;
			let a = i.fromAttribute(t, e.type);
			this[r] = a ?? this._$Ej?.get(r) ?? a, this._$Em = null;
		}
	}
	requestUpdate(e, t, n, r = !1, i) {
		if (e !== void 0) {
			let a = this.constructor;
			if (!1 === r && (i = this[e]), n ??= a.getPropertyOptions(e), !((n.hasChanged ?? h)(i, t) || n.useDefault && n.reflect && i === this._$Ej?.get(e) && !this.hasAttribute(a._$Eu(e, n)))) return;
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
_.elementStyles = [], _.shadowRootOptions = { mode: "open" }, _[p("elementProperties")] = /* @__PURE__ */ new Map(), _[p("finalized")] = /* @__PURE__ */ new Map(), ae?.({ ReactiveElement: _ }), (f.reactiveElementVersions ??= []).push("2.1.2");
//#endregion
//#region node_modules/lit-html/lit-html.js
var v = globalThis, y = (e) => e, b = v.trustedTypes, oe = b ? b.createPolicy("lit-html", { createHTML: (e) => e }) : void 0, se = "$lit$", x = `lit$${Math.random().toFixed(9).slice(2)}$`, ce = "?" + x, le = `<${ce}>`, S = document, C = () => S.createComment(""), w = (e) => e === null || typeof e != "object" && typeof e != "function", T = Array.isArray, ue = (e) => T(e) || typeof e?.[Symbol.iterator] == "function", E = "[ 	\n\f\r]", D = /<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g, de = /-->/g, fe = />/g, O = RegExp(`>|${E}(?:([^\\s"'>=/]+)(${E}*=${E}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`, "g"), k = /'/g, A = /"/g, j = /^(?:script|style|textarea|title)$/i, M = ((e) => (t, ...n) => ({
	_$litType$: e,
	strings: t,
	values: n
}))(1), N = Symbol.for("lit-noChange"), P = Symbol.for("lit-nothing"), F = /* @__PURE__ */ new WeakMap(), I = S.createTreeWalker(S, 129);
function pe(e, t) {
	if (!T(e) || !e.hasOwnProperty("raw")) throw Error("invalid template strings array");
	return oe === void 0 ? t : oe.createHTML(t);
}
var me = (e, t) => {
	let n = e.length - 1, r = [], i, a = t === 2 ? "<svg>" : t === 3 ? "<math>" : "", o = D;
	for (let t = 0; t < n; t++) {
		let n = e[t], s, c, l = -1, u = 0;
		for (; u < n.length && (o.lastIndex = u, c = o.exec(n), c !== null);) u = o.lastIndex, o === D ? c[1] === "!--" ? o = de : c[1] === void 0 ? c[2] === void 0 ? c[3] !== void 0 && (o = O) : (j.test(c[2]) && (i = RegExp("</" + c[2], "g")), o = O) : o = fe : o === O ? c[0] === ">" ? (o = i ?? D, l = -1) : c[1] === void 0 ? l = -2 : (l = o.lastIndex - c[2].length, s = c[1], o = c[3] === void 0 ? O : c[3] === "\"" ? A : k) : o === A || o === k ? o = O : o === de || o === fe ? o = D : (o = O, i = void 0);
		let d = o === O && e[t + 1].startsWith("/>") ? " " : "";
		a += o === D ? n + le : l >= 0 ? (r.push(s), n.slice(0, l) + se + n.slice(l) + x + d) : n + x + (l === -2 ? t : d);
	}
	return [pe(e, a + (e[n] || "<?>") + (t === 2 ? "</svg>" : t === 3 ? "</math>" : "")), r];
}, L = class e {
	constructor({ strings: t, _$litType$: n }, r) {
		let i;
		this.parts = [];
		let a = 0, o = 0, s = t.length - 1, c = this.parts, [l, u] = me(t, n);
		if (this.el = e.createElement(l, r), I.currentNode = this.el.content, n === 2 || n === 3) {
			let e = this.el.content.firstChild;
			e.replaceWith(...e.childNodes);
		}
		for (; (i = I.nextNode()) !== null && c.length < s;) {
			if (i.nodeType === 1) {
				if (i.hasAttributes()) for (let e of i.getAttributeNames()) if (e.endsWith(se)) {
					let t = u[o++], n = i.getAttribute(e).split(x), r = /([.?@])?(.*)/.exec(t);
					c.push({
						type: 1,
						index: a,
						name: r[2],
						strings: n,
						ctor: r[1] === "." ? ge : r[1] === "?" ? _e : r[1] === "@" ? ve : B
					}), i.removeAttribute(e);
				} else e.startsWith(x) && (c.push({
					type: 6,
					index: a
				}), i.removeAttribute(e));
				if (j.test(i.tagName)) {
					let e = i.textContent.split(x), t = e.length - 1;
					if (t > 0) {
						i.textContent = b ? b.emptyScript : "";
						for (let n = 0; n < t; n++) i.append(e[n], C()), I.nextNode(), c.push({
							type: 2,
							index: ++a
						});
						i.append(e[t], C());
					}
				}
			} else if (i.nodeType === 8) {
				if (i.data === ce) c.push({
					type: 2,
					index: a
				});
				else {
					let e = -1;
					for (; (e = i.data.indexOf(x, e + 1)) !== -1;) c.push({
						type: 7,
						index: a
					}), e += x.length - 1;
				}
			}
			a++;
		}
	}
	static createElement(e, t) {
		let n = S.createElement("template");
		return n.innerHTML = e, n;
	}
};
function R(e, t, n = e, r) {
	if (t === N) return t;
	let i = r === void 0 ? n._$Cl : n._$Co?.[r], a = w(t) ? void 0 : t._$litDirective$;
	return i?.constructor !== a && (i?._$AO?.(!1), a === void 0 ? i = void 0 : (i = new a(e), i._$AT(e, n, r)), r === void 0 ? n._$Cl = i : (n._$Co ??= [])[r] = i), i !== void 0 && (t = R(e, i._$AS(e, t.values), i, r)), t;
}
var he = class {
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
		let { el: { content: t }, parts: n } = this._$AD, r = (e?.creationScope ?? S).importNode(t, !0);
		I.currentNode = r;
		let i = I.nextNode(), a = 0, o = 0, s = n[0];
		for (; s !== void 0;) {
			if (a === s.index) {
				let t;
				s.type === 2 ? t = new z(i, i.nextSibling, this, e) : s.type === 1 ? t = new s.ctor(i, s.name, s.strings, this, e) : s.type === 6 && (t = new ye(i, this, e)), this._$AV.push(t), s = n[++o];
			}
			a !== s?.index && (i = I.nextNode(), a++);
		}
		return I.currentNode = S, r;
	}
	p(e) {
		let t = 0;
		for (let n of this._$AV) n !== void 0 && (n.strings === void 0 ? n._$AI(e[t]) : (n._$AI(e, n, t), t += n.strings.length - 2)), t++;
	}
}, z = class e {
	get _$AU() {
		return this._$AM?._$AU ?? this._$Cv;
	}
	constructor(e, t, n, r) {
		this.type = 2, this._$AH = P, this._$AN = void 0, this._$AA = e, this._$AB = t, this._$AM = n, this.options = r, this._$Cv = r?.isConnected ?? !0;
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
		e = R(this, e, t), w(e) ? e === P || e == null || e === "" ? (this._$AH !== P && this._$AR(), this._$AH = P) : e !== this._$AH && e !== N && this._(e) : e._$litType$ === void 0 ? e.nodeType === void 0 ? ue(e) ? this.k(e) : this._(e) : this.T(e) : this.$(e);
	}
	O(e) {
		return this._$AA.parentNode.insertBefore(e, this._$AB);
	}
	T(e) {
		this._$AH !== e && (this._$AR(), this._$AH = this.O(e));
	}
	_(e) {
		this._$AH !== P && w(this._$AH) ? this._$AA.nextSibling.data = e : this.T(S.createTextNode(e)), this._$AH = e;
	}
	$(e) {
		let { values: t, _$litType$: n } = e, r = typeof n == "number" ? this._$AC(e) : (n.el === void 0 && (n.el = L.createElement(pe(n.h, n.h[0]), this.options)), n);
		if (this._$AH?._$AD === r) this._$AH.p(t);
		else {
			let e = new he(r, this), n = e.u(this.options);
			e.p(t), this.T(n), this._$AH = e;
		}
	}
	_$AC(e) {
		let t = F.get(e.strings);
		return t === void 0 && F.set(e.strings, t = new L(e)), t;
	}
	k(t) {
		T(this._$AH) || (this._$AH = [], this._$AR());
		let n = this._$AH, r, i = 0;
		for (let a of t) i === n.length ? n.push(r = new e(this.O(C()), this.O(C()), this, this.options)) : r = n[i], r._$AI(a), i++;
		i < n.length && (this._$AR(r && r._$AB.nextSibling, i), n.length = i);
	}
	_$AR(e = this._$AA.nextSibling, t) {
		for (this._$AP?.(!1, !0, t); e !== this._$AB;) {
			let t = y(e).nextSibling;
			y(e).remove(), e = t;
		}
	}
	setConnected(e) {
		this._$AM === void 0 && (this._$Cv = e, this._$AP?.(e));
	}
}, B = class {
	get tagName() {
		return this.element.tagName;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	constructor(e, t, n, r, i) {
		this.type = 1, this._$AH = P, this._$AN = void 0, this.element = e, this.name = t, this._$AM = r, this.options = i, n.length > 2 || n[0] !== "" || n[1] !== "" ? (this._$AH = Array(n.length - 1).fill(/* @__PURE__ */ new String()), this.strings = n) : this._$AH = P;
	}
	_$AI(e, t = this, n, r) {
		let i = this.strings, a = !1;
		if (i === void 0) e = R(this, e, t, 0), a = !w(e) || e !== this._$AH && e !== N, a && (this._$AH = e);
		else {
			let r = e, o, s;
			for (e = i[0], o = 0; o < i.length - 1; o++) s = R(this, r[n + o], t, o), s === N && (s = this._$AH[o]), a ||= !w(s) || s !== this._$AH[o], s === P ? e = P : e !== P && (e += (s ?? "") + i[o + 1]), this._$AH[o] = s;
		}
		a && !r && this.j(e);
	}
	j(e) {
		e === P ? this.element.removeAttribute(this.name) : this.element.setAttribute(this.name, e ?? "");
	}
}, ge = class extends B {
	constructor() {
		super(...arguments), this.type = 3;
	}
	j(e) {
		this.element[this.name] = e === P ? void 0 : e;
	}
}, _e = class extends B {
	constructor() {
		super(...arguments), this.type = 4;
	}
	j(e) {
		this.element.toggleAttribute(this.name, !!e && e !== P);
	}
}, ve = class extends B {
	constructor(e, t, n, r, i) {
		super(e, t, n, r, i), this.type = 5;
	}
	_$AI(e, t = this) {
		if ((e = R(this, e, t, 0) ?? P) === N) return;
		let n = this._$AH, r = e === P && n !== P || e.capture !== n.capture || e.once !== n.once || e.passive !== n.passive, i = e !== P && (n === P || r);
		r && this.element.removeEventListener(this.name, this, n), i && this.element.addEventListener(this.name, this, e), this._$AH = e;
	}
	handleEvent(e) {
		typeof this._$AH == "function" ? this._$AH.call(this.options?.host ?? this.element, e) : this._$AH.handleEvent(e);
	}
}, ye = class {
	constructor(e, t, n) {
		this.element = e, this.type = 6, this._$AN = void 0, this._$AM = t, this.options = n;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	_$AI(e) {
		R(this, e);
	}
}, be = v.litHtmlPolyfillSupport;
be?.(L, z), (v.litHtmlVersions ??= []).push("3.3.3");
var xe = (e, t, n) => {
	let r = n?.renderBefore ?? t, i = r._$litPart$;
	if (i === void 0) {
		let e = n?.renderBefore ?? null;
		r._$litPart$ = i = new z(t.insertBefore(C(), e), e, void 0, n ?? {});
	}
	return i._$AI(e), i;
}, V = globalThis, H = class extends _ {
	constructor() {
		super(...arguments), this.renderOptions = { host: this }, this._$Do = void 0;
	}
	createRenderRoot() {
		let e = super.createRenderRoot();
		return this.renderOptions.renderBefore ??= e.firstChild, e;
	}
	update(e) {
		let t = this.render();
		this.hasUpdated || (this.renderOptions.isConnected = this.isConnected), super.update(e), this._$Do = xe(t, this.renderRoot, this.renderOptions);
	}
	connectedCallback() {
		super.connectedCallback(), this._$Do?.setConnected(!0);
	}
	disconnectedCallback() {
		super.disconnectedCallback(), this._$Do?.setConnected(!1);
	}
	render() {
		return N;
	}
};
H._$litElement$ = !0, H.finalized = !0, V.litElementHydrateSupport?.({ LitElement: H });
var Se = V.litElementPolyfillSupport;
Se?.({ LitElement: H }), (V.litElementVersions ??= []).push("4.2.2");
//#endregion
//#region node_modules/@lit/reactive-element/decorators/custom-element.js
var U = (e) => (t, n) => {
	n === void 0 ? customElements.define(e, t) : n.addInitializer(() => {
		customElements.define(e, t);
	});
}, Ce = {
	attribute: !0,
	type: String,
	converter: m,
	reflect: !1,
	hasChanged: h
}, we = (e = Ce, t, n) => {
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
function W(e) {
	return (t, n) => typeof n == "object" ? we(e, t, n) : ((e, t, n) => {
		let r = t.hasOwnProperty(n);
		return t.constructor.createProperty(n, e), r ? Object.getOwnPropertyDescriptor(t, n) : void 0;
	})(e, t, n);
}
//#endregion
//#region node_modules/@lit/reactive-element/decorators/state.js
function Te(e) {
	return W({
		...e,
		state: !0,
		attribute: !1
	});
}
//#endregion
//#region node_modules/lit-html/static.js
var Ee = Symbol.for(""), De = (e) => {
	if (e?.r === Ee) return e?._$litStatic$;
}, Oe = (e) => ({
	_$litStatic$: e,
	r: Ee
}), ke = /* @__PURE__ */ new Map(), Ae = ((e) => (t, ...n) => {
	let r = n.length, i, a, o = [], s = [], c, l = 0, u = !1;
	for (; l < r;) {
		for (c = t[l]; l < r && (a = n[l], (i = De(a)) !== void 0);) c += i + t[++l], u = !0;
		l !== r && s.push(a), o.push(c), l++;
	}
	if (l === r && o.push(t[r]), u) {
		let e = o.join("$$lit$$");
		(t = ke.get(e)) === void 0 && (o.raw = o, ke.set(e, t = o)), n = s;
	}
	return e(t, ...n);
})(M), G = {
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
}, je = class e extends Error {
	constructor(e, t = {}) {
		super(e), this.name = "DeviceLinksApiError", this.code = t.code ?? "unknown_error", this.translationKey = t.translationKey ?? null, this.translationDomain = t.translationDomain ?? null, this.placeholders = t.placeholders ?? {};
	}
	static from(t) {
		return t instanceof e ? t : Me(t) ? new e(t.message || "Device Links could not answer.", {
			code: t.code,
			translationKey: t.translation_key ?? null,
			translationDomain: t.translation_domain ?? null,
			placeholders: t.translation_placeholders ?? null
		}) : t instanceof Error ? new e(t.message || "Device Links could not answer.", { code: "connection_error" }) : new e("Device Links could not answer, and gave no reason. The connection to Home Assistant may have dropped.", { code: "connection_error" });
	}
};
function Me(e) {
	if (typeof e != "object" || !e) return !1;
	let t = e;
	return typeof t.code == "string" && typeof t.message == "string";
}
function K(e) {
	let t = {};
	return e?.rule_ids?.length && (t.rule_ids = [...e.rule_ids]), e?.device_ids?.length && (t.device_ids = [...e.device_ids]), t;
}
var Ne = class {
	constructor(e) {
		this.open = /* @__PURE__ */ new Set(), this.hass = e;
	}
	async listProfiles() {
		return this.send(G.profilesList);
	}
	async getProfile(e) {
		return this.send(G.profilesGet, { profile_id: e });
	}
	async createProfile(e) {
		return (await this.send(G.profilesCreate, { profile: e })).profile;
	}
	async updateProfile(e) {
		return (await this.send(G.profilesUpdate, { profile: e })).profile;
	}
	async deleteProfile(e) {
		await this.send(G.profilesDelete, { profile_id: e });
	}
	async activateProfile(e) {
		return this.send(G.profilesActivate, { profile_id: e });
	}
	async duplicateProfile(e, t) {
		return (await this.send(G.profilesDuplicate, {
			profile_id: e,
			...t === void 0 ? {} : { name: t }
		})).profile;
	}
	async exportProfile(e) {
		return this.send(G.profilesExport, { ...e === void 0 ? {} : { profile_id: e } });
	}
	async importProfile(e) {
		return this.send(G.profilesImport, { yaml: e });
	}
	async validateRule(e) {
		return this.send(G.rulesValidate, { rule: e });
	}
	async upsertRule(e, t) {
		return this.send(G.rulesUpsert, {
			rule: e,
			...t === void 0 ? {} : { profile_id: t }
		});
	}
	async deleteRule(e, t) {
		await this.send(G.rulesDelete, {
			rule_id: e,
			...t === void 0 ? {} : { profile_id: t }
		});
	}
	async setRuleEnabled(e, t) {
		return this.send(G.rulesSetEnabled, {
			rule_id: e,
			enabled: t
		});
	}
	async listDevices() {
		return (await this.send(G.devicesList)).devices;
	}
	async getDevice(e) {
		return this.send(G.devicesGet, { device_id: e });
	}
	async refreshDevice(e, t = !1) {
		return this.send(G.devicesRefresh, {
			device_id: e,
			deep: t
		});
	}
	async listTemplates() {
		return (await this.send(G.templatesList)).templates;
	}
	async plan(e, t) {
		return this.send(G.plan, {
			...K(e),
			...t?.length ? { remove_unmanaged: [...t] } : {}
		});
	}
	async apply(e) {
		return this.send(G.apply, {
			plan_token: e.planToken,
			...K(e.scope),
			...e.removeUnmanaged?.length ? { remove_unmanaged: [...e.removeUnmanaged] } : {}
		});
	}
	async verify(e) {
		return this.send(G.verify, K(e));
	}
	async listJobs() {
		return this.send(G.jobsList);
	}
	async getJob(e) {
		return this.send(G.jobsGet, { job_id: e });
	}
	async cancelJob() {
		return (await this.send(G.jobsCancel)).cancelled;
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
		}, { type: G.jobsSubscribe }).then((e) => {
			r = e, n.closed && i();
		}).catch((e) => {
			n.closed = !0, this.open.delete(n), t?.(je.from(e));
		}), n;
	}
	close() {
		for (let e of [...this.open]) e.unsubscribe();
	}
	async setUnmanagedIgnored(e, t) {
		return (await this.send(G.unmanagedIgnore, {
			fingerprints: [...e],
			ignored: t
		})).ignored;
	}
	async removeUnmanaged(e) {
		return this.send(G.unmanagedRemove, { fingerprints: [...e] });
	}
	async listSnapshots() {
		return (await this.send(G.snapshotsList)).snapshots;
	}
	async send(e, t = {}) {
		try {
			return await this.hass.connection.sendMessagePromise({
				type: e,
				...t
			});
		} catch (e) {
			throw je.from(e);
		}
	}
};
//#endregion
//#region \0@oxc-project+runtime@0.148.0/helpers/esm/decorate.js
function q(e, t, n, r) {
	var i = arguments.length, a = i < 3 ? t : r === null ? r = Object.getOwnPropertyDescriptor(t, n) : r, o;
	if (typeof Reflect == "object" && typeof Reflect.decorate == "function") a = Reflect.decorate(e, t, n, r);
	else for (var s = e.length - 1; s >= 0; s--) (o = e[s]) && (a = (i < 3 ? o(a) : i > 3 ? o(t, n, a) : o(t, n)) || a);
	return i > 3 && a && Object.defineProperty(t, n, a), a;
}
//#endregion
//#region src/components/two-pane.ts
var J = class extends H {
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
		return M`
      <div class="pane ${e ? "hidden" : ""}"><slot name="list"></slot></div>
      <div class="pane ${t ? "hidden" : ""}"><slot name="detail"></slot></div>
    `;
	}
};
q([W({
	type: Boolean,
	reflect: !0
})], J.prototype, "narrow", void 0), q([W({
	type: Boolean,
	attribute: "show-detail"
})], J.prototype, "showDetail", void 0), J = q([U("dl-two-pane")], J);
//#endregion
//#region src/ha-components.ts
var Pe = [
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
], Fe = {
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
}, Ie = 5e3, Le = class {
	constructor(e, t) {
		this.defined = e, this.missing = t;
	}
	has(e) {
		return this.defined.has(e);
	}
	tag(e) {
		return this.defined.has(e) ? e : Fe[e] ?? "div";
	}
};
async function Re(e = Pe, t = {}) {
	let n = t.registry ?? globalThis.customElements;
	await ze(t.loadHelpers ?? (() => window.loadCardHelpers?.()));
	let r = t.timeoutMs ?? Ie, i = /* @__PURE__ */ new Set(), a = [];
	return await Promise.all(e.map(async (e) => {
		await Be(n, e, r) ? i.add(e) : a.push(e);
	})), a.sort(), a.length && console.warn(`Device Links: these Home Assistant components did not load, so plain elements are used instead: ${a.join(", ")}`), new Le(i, a);
}
async function ze(e) {
	try {
		let t = await e();
		if (!t) return;
		await (await t.createCardElement({
			type: "entities",
			entities: []
		})).constructor.getConfigElement?.();
	} catch {}
}
async function Be(e, t, n) {
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
var Y = [
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
], Ve = Y[0]?.id ?? "overview";
function He(e) {
	let t = (e ?? "").split("/").filter(Boolean)[0];
	return Y.some((e) => e.id === t) ? t : Ve;
}
//#endregion
//#region src/styles.ts
var X = o`
  :host {
    display: block;
    color: var(--primary-text-color, #212121);
    font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif);
  }

  .content {
    padding: 16px;
    max-width: 1400px;
    margin: 0 auto;
  }

  .card {
    background: var(--card-background-color, #fff);
    border-radius: var(--ha-card-border-radius, 12px);
    box-shadow: var(--ha-card-box-shadow, 0 2px 2px rgba(0, 0, 0, 0.12));
    padding: 16px;
  }

  h2 {
    font-size: 20px;
    font-weight: 500;
    margin: 0 0 8px;
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
`;
//#endregion
//#region src/views/placeholder.ts
function Z(e, t) {
	return M`
    <div class="content">
      <div class="card">
        <h2>${e}</h2>
        <p class="secondary">${t}</p>
        <p class="secondary">This view is not built yet.</p>
      </div>
    </div>
  `;
}
//#endregion
//#region src/views/view-base.ts
var Q = class extends H {
	constructor(...e) {
		super(...e), this.narrow = !1;
	}
};
q([W({ attribute: !1 })], Q.prototype, "hass", void 0), q([W({ attribute: !1 })], Q.prototype, "api", void 0), q([W({ attribute: !1 })], Q.prototype, "components", void 0), q([W({ type: Boolean })], Q.prototype, "narrow", void 0);
//#endregion
//#region src/views/activity.ts
var Ue = class extends Q {
	static {
		this.styles = X;
	}
	render() {
		return Z("Activity", "Every apply, and what became of each link in it.");
	}
};
Ue = q([U("device-links-activity")], Ue);
//#endregion
//#region src/views/devices.ts
var We = class extends Q {
	static {
		this.styles = X;
	}
	render() {
		return Z("Devices", "What each device holds, and who reaches it.");
	}
};
We = q([U("device-links-devices")], We);
//#endregion
//#region src/views/overview.ts
var Ge = class extends Q {
	static {
		this.styles = X;
	}
	render() {
		return Z("Overview", "What every rule is doing, and what needs attention.");
	}
};
Ge = q([U("device-links-overview")], Ge);
//#endregion
//#region src/views/profiles.ts
var Ke = class extends Q {
	static {
		this.styles = X;
	}
	render() {
		return Z("Profiles", "The sets of rules, and which one is in force.");
	}
};
Ke = q([U("device-links-profiles")], Ke);
//#endregion
//#region src/views/rules.ts
var qe = class extends Q {
	static {
		this.styles = X;
	}
	render() {
		return Z("Rules", "What each control should do, and what it is doing.");
	}
};
qe = q([U("device-links-rules")], qe);
//#endregion
//#region src/panel.ts
var Je = "0.0.1", $ = class extends H {
	constructor(...e) {
		super(...e), this.narrow = !1, this.componentLoader = () => Re(), this._components = null, this._api = null;
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
		return He(this.route?.path);
	}
	get api() {
		return this._api;
	}
	connectedCallback() {
		super.connectedCallback(), this._loadComponents();
	}
	disconnectedCallback() {
		super.disconnectedCallback(), this._api?.close(), this._api = null;
	}
	willUpdate(e) {
		e.has("hass") && this.hass && (this._api === null ? this._api = new Ne(this.hass) : this._api.hass = this.hass);
	}
	async _loadComponents() {
		this._components === null && (this._components = await this.componentLoader());
	}
	render() {
		return M`
      ${this._renderBar()}
      ${this._renderVersionBanner()}
      ${this._components === null ? M`<div class="loading">Loading Home Assistant components</div>` : this._renderView()}
    `;
	}
	_renderBar() {
		let e = this._components;
		return e?.has("ha-top-app-bar-fixed") ? M`
      <ha-top-app-bar-fixed>
        ${e.has("ha-menu-button") ? M`<ha-menu-button
              slot="navigationIcon"
              .hass=${this.hass}
              .narrow=${this.narrow}
            ></ha-menu-button>` : P}
        <div slot="title">Device Links</div>
        ${this._renderTabs()}
      </ha-top-app-bar-fixed>
    ` : M`
        <header class="plain-bar">
          <span>Device Links</span>
        </header>
        ${this._renderTabs()}
      `;
	}
	_renderTabs() {
		let e = this._components;
		return !e?.has("ha-tab-group") || !e.has("ha-tab-group-tab") ? M`
        <nav class="plain-tabs" aria-label="Device Links sections">
          ${Y.map((e) => M`
              <button
                type="button"
                aria-current=${e.id === this.tab ? "page" : "false"}
                @click=${() => this._selectTab(e.id)}
              >
                ${e.label}
              </button>
            `)}
        </nav>
      ` : M`
      <ha-tab-group slot="tabs" aria-label="Device Links sections">
        ${Y.map((t) => M`
            <ha-tab-group-tab
              slot="nav"
              panel=${t.id}
              .active=${t.id === this.tab}
              @click=${() => this._selectTab(t.id)}
            >
              ${this.narrow && e.has("ha-icon") ? M`<ha-icon .icon=${t.icon} aria-label=${t.label}></ha-icon>` : t.label}
            </ha-tab-group-tab>
          `)}
      </ha-tab-group>
    `;
	}
	_selectTab(e) {
		if (e === this.tab) return;
		let t = this.route?.prefix ?? "/device_links";
		history.pushState(null, "", `${t}/${e}`), this.dispatchEvent(new CustomEvent("location-changed", {
			bubbles: !0,
			composed: !0
		})), this.requestUpdate();
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
		if (!this.versionMismatch) return P;
		let e = `Device Links was updated to ${this.backendVersion} while this page was open. This panel is still running version ${Je}. Reload the page to pick up the new one.`;
		return this._components?.has("ha-alert") ? M`
        <ha-alert class="banner" alert-type="info" title="A newer version is installed">
          ${e}
          <button type="button" slot="action" @click=${() => this._reload()}>Reload</button>
        </ha-alert>
      ` : M`
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
		let e = Y.find((e) => e.id === this.tab) ?? Y[0];
		return e ? Ae`
      <${Oe(e.tagName)}
        class="view"
        .hass=${this.hass}
        .api=${this._api}
        .components=${this._components}
        .narrow=${this.narrow}
      ></${Oe(e.tagName)}>
    ` : M`<div class="loading">No view is registered.</div>`;
	}
};
q([W({ attribute: !1 })], $.prototype, "hass", void 0), q([W({
	type: Boolean,
	reflect: !0
})], $.prototype, "narrow", void 0), q([W({ attribute: !1 })], $.prototype, "route", void 0), q([W({ attribute: !1 })], $.prototype, "panel", void 0), q([W({ attribute: !1 })], $.prototype, "componentLoader", void 0), q([Te()], $.prototype, "_components", void 0), $ = q([U("device-links-panel")], $);
//#endregion
export { Je as BUNDLE_VERSION, $ as DeviceLinksPanel };
