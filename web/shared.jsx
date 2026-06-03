/* global React */
const { useState, useRef, useEffect } = React;

/* =========================================================
   FIGURE PLACEHOLDERS — model-sheet silhouettes per angle
   ========================================================= */
function Figure({ kind = "front-portrait", size = 70 }) {
  const stroke = "currentColor";
  const sw = 2.2;
  const common = { fill: "none", stroke, strokeWidth: sw, strokeLinecap: "round", strokeLinejoin: "round" };
  const W = size, H = size * 1.5;
  let body = null;
  if (kind === "front-portrait") {
    body = (
      <g {...common}>
        <circle cx="35" cy="30" r="16" />
        <path d="M16 70 q19 -22 38 0" />
      </g>
    );
  } else if (kind === "profile-portrait") {
    body = (
      <g {...common}>
        <path d="M44 16 q-22 2 -22 22 q0 14 16 18 l0 -8" />
        <path d="M22 32 l-6 6 l6 4" />
        <path d="M20 70 q14 -16 30 -6" />
      </g>
    );
  } else if (kind === "front-full") {
    body = (
      <g {...common}>
        <circle cx="35" cy="18" r="9" />
        <path d="M35 27 l0 38" />
        <path d="M35 33 l-15 16 M35 33 l15 16" />
        <path d="M35 65 l-11 32 M35 65 l11 32" />
      </g>
    );
  } else if (kind === "back-full") {
    body = (
      <g {...common}>
        <circle cx="35" cy="18" r="9" />
        <path d="M28 13 q7 -6 14 0" />
        <path d="M35 27 l0 38" />
        <path d="M35 33 l-15 16 M35 33 l15 16" />
        <path d="M35 65 l-11 32 M35 65 l11 32" />
      </g>
    );
  } else if (kind === "threeq-full") {
    body = (
      <g {...common}>
        <ellipse cx="36" cy="18" rx="8" ry="9" />
        <path d="M36 27 q4 18 0 38" />
        <path d="M36 34 l-13 13 M36 34 l16 14" />
        <path d="M34 65 l-9 32 M34 65 l13 31" />
      </g>
    );
  } else if (kind === "item") {
    body = (
      <g {...common}>
        <path d="M20 50 l30 -30 M44 14 l8 8 M50 24 l-6 -6" />
        <path d="M20 50 l-6 6 l4 4 l6 -6" />
      </g>
    );
  }
  return (
    <svg width={W} height={H} viewBox="0 0 70 105" className="figure" aria-hidden="true">
      {body}
    </svg>
  );
}

/* small inline icons */
const Ico = {
  check: <svg width="13" height="13" viewBox="0 0 14 14"><path d="M2 7.5l3.5 3.5L12 3" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  pencil: "✎",
  sparkle: "✦",
  lock: "🔒",
};

/* =========================================================
   STEPPER  (top horizontal, with substeps)
   ========================================================= */
const PHASES = [
  { key: "start", num: "0", lbl: "Старт", sub: "текст и герои" },
  { key: "data", num: "1", lbl: "Анкета героя", sub: "кто он" },
  { key: "passport", num: "2", lbl: "Паспорт", sub: "5 кадров" },
  { key: "emotions", num: "3", lbl: "Эмоции", sub: "опц." },
  { key: "outfit", num: "4", lbl: "Наряды", sub: "опц." },
  { key: "props", num: "5", lbl: "Предметы", sub: "финал" },
];

function Stepper({ current, done, onNav }) {
  return (
    <div className="stepper">
      {PHASES.map((p, i) => {
        const isDone = done.includes(p.key);
        const isCur = current === p.key;
        const cls = "step" + (isCur ? " current" : "") + (isDone && !isCur ? " done" : "");
        return (
          <React.Fragment key={p.key}>
            <div className={cls} onClick={() => onNav && onNav(p.key)}>
              <span className="num">{isDone && !isCur ? Ico.check : p.num}</span>
              <span>
                <span className="lbl" style={{ display: "block" }}>{p.lbl}</span>
                <span className="sub">{p.sub}</span>
              </span>
            </div>
            {i < PHASES.length - 1 && <span className="step" style={{ padding: "0 2px", cursor: "default" }}><span className="chev">›</span></span>}
          </React.Fragment>
        );
      })}
    </div>
  );
}

/* =========================================================
   LAYER RAIL  (right side — the 6 prompt layers + status)
   ========================================================= */
const LAYER_DEFS = [
  { key: "style", nm: "Стиль", en: "STYLE", desc: "манера рисунка" },
  { key: "face", nm: "Лицо", en: "FACE", desc: "только черты лица" },
  { key: "body", nm: "Тело", en: "BODY", desc: "телосложение, приметы" },
  { key: "outfit", nm: "Одежда", en: "OUTFIT", desc: "наряд" },
  { key: "expression", nm: "Эмоция", en: "EXPRESSION", desc: "выражение лица" },
  { key: "composition", nm: "Поза и кадр", en: "COMPOSITION", desc: "поза, ракурс, фон" },
];
const ST_LABEL = { frozen: "заморожен", active: "активен", caution: "с осторожностью", idle: "позже", variable: "меняется" };

function LayerRail({ layers, values }) {
  return (
    <div className="rail">
      <div className="rail-h">⛓ Слои промта</div>
      <div className="rail-sub">
        Описание героя собирается из 6 «слоёв». Вы заполняете их по очереди. Заполнили и одобрили —
        слой <b>замораживается</b> 🔒 и больше не плывёт от кадра к кадру.
      </div>
      {LAYER_DEFS.map((L) => {
        const st = layers[L.key] || "idle";
        // read-only behaves as frozen everywhere EXCEPT composition (поза и кадр),
        // which stays editable "with caution".
        let est = st;
        if (st === "ro") est = (L.key === "composition") ? "caution" : "frozen";
        const cls = "layer " + (est === "frozen" ? "frozen" : est === "active" ? "active" : est === "caution" ? "caution" : "idle");
        const val = values && values[L.key];
        return (
          <div className={cls} key={L.key}>
            <div className="lh">
              <span className="dot"></span>
              <span className="nm">{L.nm}</span>
              <span className="en">{L.en}</span>
              <span className="spacer"></span>
              <span className="st">{est === "frozen" ? "🔒 " : est === "caution" ? "⚠ " : ""}{ST_LABEL[est] || est}</span>
            </div>
            {val ? <div className="val">{val}</div> : <div className="val" style={{ opacity: 0.6 }}>{L.desc}</div>}
          </div>
        );
      })}
      <div className="rail-note">
        <b>Зачем это нужно?</b> Чтобы герой выглядел одинаково на всех картинках. Лицо и тело
        замораживаются один раз — дальше меняются только одежда, эмоция и поза.
      </div>
    </div>
  );
}

/* =========================================================
   PANEL  (with crop marks)
   ========================================================= */
function Panel({ title, icon, badge, children, className = "", actions, marks = true, collapsible = false, defaultCollapsed = false }) {
  const [collapsed, setCollapsed] = useState(collapsible ? defaultCollapsed : false);
  const headClick = collapsible ? () => setCollapsed(!collapsed) : undefined;
  return (
    <div className={"panel " + className}>
      {marks && <><i className="crop tl"></i><i className="crop tr"></i><i className="crop bl"></i><i className="crop br"></i></>}
      {(title || actions) && (
        <div className="panel-h" style={collapsible ? { cursor: "pointer", marginBottom: collapsed ? -2 : 16 } : null} onClick={headClick}>
          {icon && <span className="ico">{icon}</span>}
          {title && <span className="ttl">{title}</span>}
          {badge}
          <span className="spacer"></span>
          {actions}
          {collapsible && <span className="badge ro" style={{ marginLeft: 8 }}>{collapsed ? "развернуть" : "свернуть"}</span>}
          {collapsible && <span className="tw" style={{ fontSize: 13, color: "var(--ink-3)", transition: "transform .18s ease", transform: collapsed ? "none" : "rotate(180deg)" }}>▾</span>}
        </div>
      )}
      {!collapsed && children}
    </div>
  );
}

/* =========================================================
   HELP CALLOUT  (expandable friendly explainer)
   ========================================================= */
function Help({ title = "Что это и зачем?", children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={"help" + (open ? " open" : "")}>
      <div className="help-head" onClick={() => setOpen(!open)}>
        <span className="q">?</span>
        <span>{title}</span>
        <span className="spacer"></span>
        <span className="tw">▾</span>
      </div>
      {open && <div className="help-body">{children}</div>}
    </div>
  );
}

/* =========================================================
   FIELD + PROMPT FIELD
   ========================================================= */
function Field({ ru, en, hint, children, right }) {
  return (
    <div className="field">
      {(ru || en) && (
        <div className="field-lbl">
          {ru && <span className="ru">{ru}</span>}
          {en && <span className="en">{en}</span>}
          {right && <><span className="spacer"></span>{right}</>}
        </div>
      )}
      {children}
      {hint}
    </div>
  );
}

function DoDont({ yes, no }) {
  return (
    <div className="dodont">
      {yes && <div className="yes ex"><b>✓ сюда пишем:</b> {yes}</div>}
      {no && <div className="no ex"><b>✕ сюда НЕ пишем:</b> {no}</div>}
    </div>
  );
}

/* sample RU->EN optimisations per layer (prototype) */
const SAMPLE_TRANSLATIONS = {
  "Лицо": "weathered face, broad nose, full lips, deep-set dark eyes, short rough dark hair, tanned skin",
  "Тело": "stocky, powerfully built frame, broad shoulders, faded tattoo on the left forearm",
  "Одежда": "dark fur-trimmed leather tunic, wide leather belt, worn brown leather boots",
  "Эмоция": "grim, brooding",
  "Поза и кадр": "walking mid-stride, three-quarter angle, full body, dim tavern interior background",
  "Предмет": "ancient bronze longsword, ornate hilt, runic engravings, product shot, plain background",
  "Деталь": "extreme close-up of engraved pauldron, fine metal texture, plain background",
  "этот слой": "bold ink linework, muted watercolour wash, dramatic lighting",
};

/* dialog: write in Russian -> AI turns it into an optimised EN prompt */
function TranslateDialog({ layer = "этот слой", onClose, onInsert }) {
  const [ru, setRu] = useState("");
  const [stage, setStage] = useState("ask");
  const en = SAMPLE_TRANSLATIONS[layer] || SAMPLE_TRANSLATIONS["этот слой"];
  return (
    <Dialog onClose={onClose}>
      <h3>⇄ Написать по-русски</h3>
      {stage === "ask" ? (
        <>
          <p>Опишите простыми словами, что хотите в слое <b>«{layer}»</b>. ИИ сам переведёт это
            на английский и превратит в правильный промт под нейросеть — знать английский не нужно.</p>
          <Field ru={"Опишите «" + layer + "» по-русски"} hint={<div className="tip"><span className="ic">💡</span><span>Пишите только про этот слой. Например для одежды: «тёмная кожаная туника с меховой оторочкой, широкий пояс, потёртые сапоги».</span></div>}>
            <textarea className="in" rows={3} value={ru} onChange={(e) => setRu(e.target.value)} placeholder="тёмная кожаная туника с меховой оторочкой, широкий пояс…" />
          </Field>
          <div className="btnrow end">
            <button className="btn ghost" onClick={onClose}>Отмена</button>
            <AIButton onClick={() => setStage("res")}>Превратить в промт</AIButton>
          </div>
        </>
      ) : (
        <>
          <p>Готово. Вот промт для нейросети — <b>оптимизирован под Nano Banana</b>. Можно вставить
            в поле как есть или сначала подправить.</p>
          <Field ru="Промт для нейросети" en="">
            <PromptField value={en} rows={3} />
          </Field>
          <div className="btnrow split">
            <button className="btn ghost" onClick={() => setStage("ask")}>← Изменить русский</button>
            <button className="btn primary" onClick={() => { onInsert && onInsert(en); onClose(); }}>Вставить в поле</button>
          </div>
        </>
      )}
    </Dialog>
  );
}

/* prompt textarea — english, mono, with EN badge + RU->EN translate button */
function PromptField({ value, onChange, placeholder, readOnly, rows = 2, layer }) {
  const [text, setText] = useState(value || "");
  useEffect(() => { setText(value || ""); }, [value]);
  function set(v) { setText(v); onChange && onChange(v); }
  return (
    <div className="promptwrap">
      <span className="lang">EN · англ.</span>
      <textarea
        className={"in mono" + (readOnly ? " ro" : "")}
        value={text}
        placeholder={placeholder}
        readOnly={readOnly}
        rows={rows}
        onChange={(e) => set(e.target.value)}
      />
    </div>
  );
}

/* =========================================================
   PREVIEW
   ========================================================= */
function Preview({ kind, cap, state = "empty", sub, small }) {
  // state: empty | gen | ready
  const cls = "pv " + state + (small ? " sm" : "");
  return (
    <div className={cls} style={small ? { minHeight: 110 } : null}>
      {state === "gen" ? (
        <>
          <div className="pv-spin"></div>
          <span className="pv-cap">генерация…</span>
        </>
      ) : state === "ready" ? (
        <>
          <span className="pv-badge"><span className="badge done">✓ готово</span></span>
          <Figure kind={kind} size={small ? 46 : 64} />
          <span className="pv-cap">{cap}</span>
          {sub && <span className="pv-sub">{sub}</span>}
        </>
      ) : (
        <>
          <Figure kind={kind} size={small ? 46 : 64} />
          <span className="pv-cap">{cap}</span>
          <span className="pv-sub">{sub || "ещё не сгенерировано"}</span>
        </>
      )}
    </div>
  );
}

/* =========================================================
   AI BUTTONS  (blue-pencil, with cost mark)
   ========================================================= */
function AIButton({ children, onClick, kind = "check", small, busyMs = 1100 }) {
  const [busy, setBusy] = useState(false);
  async function handle(e) {
    if (busy) return;
    setBusy(true);
    if (window.__bumpCost) window.__bumpCost(0.003); // ~LLM call, USD
    // Shimmer while the LLM is queried. A wired button returns a Promise from
    // onClick -> the shimmer lasts the *real* round-trip. An un-wired demo
    // button returns nothing -> fall back to a fixed simulated delay.
    try {
      const r = onClick && onClick(e);
      if (r && typeof r.then === "function") {
        await r;
      } else {
        await new Promise((resolve) => setTimeout(resolve, busyMs));
      }
    } finally {
      setBusy(false);
    }
  }
  return (
    <button
      className={"btn ai" + (small ? " sm" : "") + (busy ? " busy" : "")}
      disabled={busy}
      onClick={handle}
      title="Это платный запрос к ИИ — он подумает и подскажет"
    >
      <span className="pencil">✦</span>
      {busy ? "ИИ думает…" : children}
      <span className="cost">{busy ? "…" : "платно"}</span>
    </button>
  );
}

/* =========================================================
   CHECKBOX / TOGGLE
   ========================================================= */
function Check({ on, onToggle, label, children }) {
  return (
    <label className={"chk" + (on ? " on" : "")} onClick={(e) => { e.preventDefault(); onToggle && onToggle(!on); }}>
      <span className="bx">{Ico.check}</span>
      {label && <span className="ck-lbl">{label}</span>}
      {children}
    </label>
  );
}

function Toggle({ on, onToggle, label }) {
  return (
    <label className={"toggle" + (on ? " on" : "")} onClick={(e) => { e.preventDefault(); onToggle && onToggle(!on); }}>
      <span className="tr"></span>
      {label && <span style={{ fontWeight: 700, fontSize: 14 }}>{label}</span>}
    </label>
  );
}

/* =========================================================
   DIALOG
   ========================================================= */
function Dialog({ children, onClose, wide }) {
  return (
    <div className="overlay" onClick={onClose}>
      <div className="dialog" style={wide ? { maxWidth: 680 } : null} onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}

/* =========================================================
   PRESET PICKER (base emotion)
   ========================================================= */
const EMOTION_PRESETS = [
  ["calm, composed", "Спокойный, собранный — невозмутимое, уверенное лицо"],
  ["grim, brooding", "Мрачный, угрюмый — тяжёлый взгляд, сведённые брови"],
  ["stern, serious", "Суровый, серьёзный — жёсткое сосредоточенное лицо"],
  ["confident, slight smirk", "Уверенный, с лёгкой ухмылкой — спокойная насмешка"],
  ["warm, friendly", "Тёплый, дружелюбный — мягкое открытое лицо"],
  ["tired, weary", "Усталый, измотанный — опущенные веки, тяжесть"],
  ["cold, detached", "Холодный, отстранённый — бесстрастность, дистанция"],
  ["cunning, sly", "Хитрый, лукавый — прищур, едва заметная усмешка"],
  ["melancholic, sad", "Меланхоличный, печальный — тихая грусть"],
  ["arrogant, haughty", "Надменный — приподнятый подбородок, взгляд свысока"],
  ["anxious, wary", "Тревожный, настороженный — напряжение во взгляде"],
  ["kind, gentle", "Добрый, мягкий — спокойная теплота"],
];

function PresetPicker({ onPick, onClose }) {
  return (
    <Dialog onClose={onClose} wide>
      <h3>Готовые эмоции</h3>
      <p>Выберите настроение «по умолчанию» для героя. Слева — как это запишется в промт (по-английски),
        справа — что это значит. Нажмите на строку — текст сам подставится в поле.</p>
      <div className="presets">
        {EMOTION_PRESETS.map(([v, d]) => (
          <div className="preset" key={v} onClick={() => { onPick(v); onClose(); }}>
            <span className="v">{v}</span>
            <span className="d">{d}</span>
          </div>
        ))}
      </div>
      <div className="btnrow end" style={{ marginTop: 16 }}>
        <button className="btn ghost" onClick={onClose}>Закрыть</button>
      </div>
    </Dialog>
  );
}

/* =========================================================
   ADVANCED SCENE — collapsible editable COMPOSITION block
   ========================================================= */
function AdvancedScene({ value, layer = "Поза и кадр", note }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={"adv" + (open ? " open" : "")} style={{ marginTop: 16 }}>
      <button className="adv-head" onClick={() => setOpen(!open)}>
        <span className="ico" style={{ fontSize: 15 }}>⚙</span>
        <span style={{ whiteSpace: "nowrap" }}>Поза и кадр <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-3)" }}>COMPOSITION</span></span>
        <span className="muted" style={{ fontSize: 12, whiteSpace: "nowrap" }}>— редактировать сцену</span>
        <span className="spacer" style={{ flex: 1 }}></span>
        <span className="badge ro">{open ? "скрыть" : "показать"}</span>
        <span className="tw">▾</span>
      </button>
      {open && (
        <div className="adv-body">
          <div className="tip" style={{ color: "var(--amber)", marginTop: 0, marginBottom: 10 }}>
            <span className="ic">⚠️</span>
            <span>{note || <>Это поле уже настроено под этот кадр. Меняйте его <b>только</b> чтобы поправить <b>положение героя</b> и <b>ракурс камеры</b>. Фон, свет и пометки «без рамок» лучше не трогать.</>}</span>
          </div>
          <PromptField value={value} rows={3} layer={layer} />
        </div>
      )}
    </div>
  );
}

/* =========================================================
   SCENE MODAL — edit one frame's COMPOSITION; OK only re-gens if changed
   ========================================================= */
function SceneModal({ title, value, onClose, onApply }) {
  const [txt, setTxt] = useState(value);
  const changed = txt.trim() !== (value || "").trim();
  return (
    <Dialog onClose={onClose}>
      <h3>⚙ Сцена кадра · {title}</h3>
      <p>Здесь описывается <b>поза героя, ракурс и фон</b> для этого кадра. Поле уже настроено —
        меняйте, только если нужно поправить положение/обрезку. После «ОК» кадр перегенерируется
        автоматически (если вы что-то изменили).</p>
      <Field ru="Поза и кадр" en="COMPOSITION" hint={<DoDont yes="позу, ракурс, план кадра, фон" no="лицо, тело, одежду, эмоцию" />}>
        <PromptField value={txt} onChange={setTxt} rows={3} layer="Поза и кадр" />
      </Field>
      <div className="btnrow split" style={{ marginTop: 4 }}>
        <button className="btn ghost" onClick={onClose}>Отмена</button>
        <button className={"btn " + (changed ? "primary" : "")} onClick={() => { onApply(txt, changed); onClose(); }}>
          {changed ? "ОК — перегенерировать" : "ОК"}
        </button>
      </div>
      {!changed && <p className="muted center" style={{ fontSize: 12, marginTop: 8, marginBottom: 0 }}>Ничего не изменено — перегенерации не будет.</p>}
    </Dialog>
  );
}

/* =========================================================
   DEBUG — last prompt store + unobtrusive viewer
   window.setLastGen({ section, view, layers:{...}, refs:[{label,kind}], negative, model, size })
   ========================================================= */
window.__lastGen = null;
window.setLastGen = function (p) {
  window.__lastGen = Object.assign({ at: new Date().toLocaleTimeString() }, p);
  window.dispatchEvent(new CustomEvent("om-lastgen"));
};

const LAYER_ORDER = [
  ["style", "STYLE", "стиль"],
  ["face", "FACE", "лицо"],
  ["body", "BODY", "тело"],
  ["outfit", "OUTFIT", "одежда"],
  ["item", "ITEM", "предмет"],
  ["expression", "EXPRESSION", "эмоция"],
  ["composition", "COMPOSITION", "поза и кадр"],
];

/* short English instruction for each ref (what the model should take from it) */
function refTake(r) {
  if (r.take) return r.take;
  const l = (r.label || "").toLowerCase();
  if (l.includes("стиль")) return "use STYLE only — the drawing manner, do not copy any character";
  if (l.includes("face") || l.includes("фас-портрет")) return "use FACE only — facial features";
  if (l.includes("body") || l.includes("рост")) return "use BODY only — build / physique";
  return "reference";
}

function refPreamble(g) {
  const refs = g.refs || [];
  if (!refs.length) return "";
  const lines = refs.map((r, i) => `image ${i + 1} — ${refTake(r)}`);
  return "Attached reference images:\n" + lines.join("\n");
}

/* full prompt EXACTLY as it goes to the model: ref note + labeled layers, no negative */
function assembleFull(g) {
  if (!g || !g.layers) return "";
  const blocks = LAYER_ORDER
    .filter(([k]) => g.layers[k])
    .map(([k, en]) => "[" + en + "]:\n" + g.layers[k]);
  const pre = refPreamble(g);
  return (pre ? pre + "\n\n" : "") + blocks.join("\n");
}

function DebugLastPrompt() {
  const [open, setOpen] = useState(false);
  const [, force] = useState(0);
  useEffect(() => {
    const h = () => force((n) => n + 1);
    window.addEventListener("om-lastgen", h);
    return () => window.removeEventListener("om-lastgen", h);
  }, []);
  const g = window.__lastGen;
  return (
    <>
      <button className="dbg-tab" onClick={() => setOpen(true)} title="Отладка: показать последний промт, ушедший в нейросеть">
        ⟐ последний промт
      </button>
      {open && (
        <Dialog onClose={() => setOpen(false)} wide>
          <h3 style={{ display: "flex", alignItems: "center", gap: 10 }}>⟐ Последний промт <span className="badge ro" style={{ fontSize: 10 }}>отладка</span></h3>
          {!g ? (
            <p className="muted">Пока ничего не генерировали в этой сессии. Нажмите любую кнопку «Сгенерировать» — здесь появится точный промт, который ушёл в нейросеть, и прикреплённые к нему картинки.</p>
          ) : (
            <>
              <div className="dbg-meta">
                <span><b>раздел:</b> {g.section || "—"}</span>
                <span><b>кадр:</b> {g.view || "—"}</span>
                <span><b>модель:</b> {g.model || "nano-banana"}</span>
                {g.size && <span><b>размер:</b> {g.size}</span>}
                <span><b>время:</b> {g.at}</span>
              </div>

              <div className="dbg-sec-h">Промт целиком (как уходит в модель)</div>
              <pre className="dbg-pre">{assembleFull(g)}</pre>

              <div className="dbg-sec-h">Прикреплённые картинки ({(g.refs || []).length})</div>
              {(g.refs || []).length === 0 ? (
                <p className="muted" style={{ fontSize: 12.5 }}>Без референсов — генерация «с нуля» по тексту.</p>
              ) : (
                <div className="dbg-refs">
                  {g.refs.map((r, i) => (
                    <div className="dbg-ref" key={i}>
                      <div className="dbg-ref-img"><Figure kind={r.kind || "front-portrait"} size={40} /><span className="dbg-ref-n">{i + 1}</span></div>
                      <span className="dbg-ref-lbl">{r.label}</span>
                      <span className="dbg-ref-take">{refTake(r)}</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="btnrow end" style={{ marginTop: 16 }}>
                <button className="btn ghost sm" onClick={() => { navigator.clipboard && navigator.clipboard.writeText(assembleFull(g)); }}>⧉ Копировать промт</button>
                <button className="btn sm" onClick={() => setOpen(false)}>Закрыть</button>
              </div>
            </>
          )}
        </Dialog>
      )}
    </>
  );
}

/* =========================================================
   LIGHTBOX — click a preview thumbnail to see the original.
   Closes on ANY key or a click outside the image.
   ========================================================= */
function Lightbox({ url, onClose }) {
  useEffect(() => {
    const onKey = () => onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="overlay" onClick={onClose} style={{ cursor: "zoom-out", padding: 24 }}>
      <img
        src={url}
        alt="оригинал"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: "92vw", maxHeight: "92vh", borderRadius: 8, boxShadow: "0 10px 50px rgba(0,0,0,.55)", cursor: "default" }}
      />
    </div>
  );
}

/* export */
Object.assign(window, {
  Figure, Ico, Stepper, PHASES, LayerRail, LAYER_DEFS, Panel, Help,
  Field, DoDont, PromptField, Preview, AIButton, Check, Toggle, Dialog,
  PresetPicker, EMOTION_PRESETS, TranslateDialog, AdvancedScene, SceneModal,
  DebugLastPrompt, assembleFull, Lightbox,
});
