/* global React, Panel, Help, Field, DoDont, PromptField, Preview, AIButton, Check, Toggle, Dialog, Figure, LAYER_DEFS */
const { useState: useS2 } = React;

/* =========================================================
   AI DIALOGS  (shared — exported to window)
   ========================================================= */
function AICheckDialog({ onClose, onAccept, layerName, reasoning, newPrompt }) {
  return (
    <Dialog onClose={onClose}>
      <h3>✦ ИИ проверил кадр</h3>
      <div className="panel soft" style={{ marginBottom: 14, background: "var(--blue-tint)", borderColor: "var(--blue)" }}>
        <div className="field-lbl"><span className="ru">Что говорит ИИ</span></div>
        <p style={{ margin: 0, color: "var(--ink)", fontSize: 14 }}>{reasoning}</p>
      </div>
      {newPrompt ? (
        <>
          <Field ru={"Предлагает поправить «" + layerName + "»"} en="">
            <PromptField value={newPrompt} readOnly rows={3} />
          </Field>
          <p className="muted" style={{ fontSize: 13 }}>Применить эту правку? Старый текст заменится на новый.</p>
          <div className="btnrow end">
            <button className="btn ghost" onClick={onClose}>Оставить как было</button>
            <button className="btn primary" onClick={() => { onAccept && onAccept(newPrompt); onClose(); }}>Принять правку</button>
          </div>
        </>
      ) : (
        <>
          <p className="muted">Замечаний нет — можно генерировать.</p>
          <div className="btnrow end"><button className="btn primary" onClick={onClose}>Понятно</button></div>
        </>
      )}
    </Dialog>
  );
}

const STEP_RU = { passport_face: "Лицо (паспорт)", passport_body: "Тело (паспорт)" };
function stepLabel(k) { return STEP_RU[k] || (k && k.startsWith("outfit_") ? "Наряд " + k.slice(7) : k); }

function AIEditDialog({ id, onClose }) {
  const [stage, setStage] = useS2("ask");
  const [req, setReq] = useS2("");
  const [blocks, setBlocks] = useS2([]);
  const [note, setNote] = useS2("");
  const [accepted, setAccepted] = useS2({});

  // Real whole-character review (Promise -> AI button shimmers for the round-trip).
  async function send() {
    if (!id) { setBlocks([]); setNote("Правка работает на сервере — нужен сохранённый герой."); setStage("res"); return; }
    try {
      const d = await window.api.edit(id, req);
      setBlocks(d.blocks || []); setNote(d.note || "");
    } catch (e) { setBlocks([]); setNote("Ошибка сети — попробуйте ещё раз."); }
    setStage("res");
  }
  async function acceptBlock(b, i) {
    if (id) { try { await window.api.editAccept(id, b.step_key, b.new_prompt); } catch (e) { /* ignore */ } }
    setAccepted((a) => Object.assign({}, a, { [i]: true }));
  }
  return (
    <Dialog onClose={onClose} wide>
      <h3>✦ Правка с ИИ</h3>
      {stage === "ask" ? (
        <>
          <p>Опишите простыми словами, чего хотите добиться — ИИ просмотрит весь паспорт героя и
            предложит правки сразу по нужным шагам. Например: «сделай его более грозным и старше».</p>
          <Field ru="Чего хотите добиться?">
            <textarea className="in" rows={3} value={req} onChange={(e) => setReq(e.target.value)} placeholder="Хочу, чтобы Герон выглядел суровее и опаснее…" />
          </Field>
          <div className="btnrow end">
            <button className="btn ghost" onClick={onClose}>Отмена</button>
            <AIButton onClick={send}>Отправить запрос</AIButton>
          </div>
        </>
      ) : (
        <>
          {blocks.length === 0 ? (
            <p className="muted">{note || "ИИ не предложил правок — по его оценке всё в порядке."}</p>
          ) : (
            <>
              <p>ИИ предлагает правки по {blocks.length} шаг(ам). Примите нужные — принятый шаг попросит перегенерировать кадр.</p>
              {blocks.map((b, i) => (
                <div className="panel soft" key={i} style={{ marginBottom: 12 }}>
                  <div className="field-lbl"><span className="ru">{stepLabel(b.step_key)}</span></div>
                  <p style={{ fontSize: 13, color: "var(--ink-2)", margin: "0 0 8px" }}>{b.justification}</p>
                  <PromptField value={b.new_prompt} readOnly rows={2} />
                  <div className="btnrow end" style={{ marginTop: 10 }}>
                    {accepted[i] ? <span className="badge done">✓ принято</span> : <button className="btn approve sm" onClick={() => acceptBlock(b, i)}>Принять</button>}
                  </div>
                </div>
              ))}
            </>
          )}
          <div className="btnrow end"><button className="btn ghost" onClick={onClose}>Закрыть</button></div>
        </>
      )}
    </Dialog>
  );
}

window.AICheckDialog = AICheckDialog;
window.AIEditDialog = AIEditDialog;

/* =========================================================
   PASSPORT — 5 frames, 3 layout variants
   ========================================================= */
const FRAMES = [
  { key: "face", n: 1, title: "Фас-портрет", fig: "front-portrait", cranks: "face",
    crit: "Лицо смотрит прямо в камеру, видно голову и плечи. Спокойное лицо, ровный серый фон, мягкий свет, без рамок и подписей.",
    why: "Это главный кадр — эталон лица. По нему нейросеть будет «узнавать» героя на всех остальных картинках. Здесь мы крутим и замораживаем ЛИЦО." },
  { key: "body", n: 2, title: "Фас, полный рост", fig: "front-full", cranks: "body",
    crit: "Видно героя ЦЕЛИКОМ — от макушки до обуви, без обрезки. Стоит прямо, стопы на земле, руки расслаблены, серый фон.",
    why: "Эталон телосложения. Лицо уже держится первым кадром, а здесь мы крутим и замораживаем ТЕЛО и базовый наряд." },
  { key: "profile", n: 3, title: "Профиль-портрет", fig: "profile-portrait", cranks: null,
    crit: "СТРОГИЙ профиль, 90° вбок — самый капризный кадр, тут нейросеть постоянно халтурит. Голова повёрнута ровно вбок, герой смотрит ПРЯМО ПЕРЕД СОБОЙ, а НЕ в камеру. Видна только ОДНА сторона лица: один глаз, одна бровь, одно ухо; нос и подбородок — чётким силуэтом на фоне. Это НЕ полуоборот и НЕ 3/4. Если лицо хоть немного развернулось к камере — перегенерируйте, нейросеть любит «подсматривать».",
    why: "Профиль нейросеть сама нарисовать не может — нужен эталон формы носа и подбородка сбоку. И она упорно норовит развернуть лицо обратно в 3/4 или к камере, поэтому тут придётся последить и, возможно, перегенерить пару раз." },
  { key: "back", n: 4, title: "Спина, полный рост", fig: "back-full", cranks: null,
    crit: "Вид со спины, в полный рост без обрезки. Видно затылок, причёску сзади, спину и одежду со спины.",
    why: "Затылок и спину нельзя «додумать» из вида спереди — поэтому снимаем отдельно." },
  { key: "3q", n: 5, title: "3/4, полный рост", fig: "threeq-full", cranks: null,
    crit: "Полуоборот примерно на 45°, в полный рост без обрезки, стопы на земле, серый фон.",
    why: "Объём фигуры на повороте — последний эталон для покрытия всех ракурсов." },
];

/* canonical COMPOSITION text per passport frame (advanced; edit only to nudge pose/camera) */
const FRAME_COMP = {
  face: "Front facing portrait, head and shoulders, plain neutral grey background, soft even lighting, neutral expression, no text, no panel border, no frame.",
  body: "Full-length character reference, head-to-toe, standing straight, both feet flat on the ground, legs and footwear visible, plain neutral grey background, soft even lighting, neutral expression, arms relaxed at sides, no frame.",
  profile: "Strict side profile, head facing 90 degrees to the side, only one eye visible, nose and lips in silhouette, head and shoulders, plain neutral grey background, soft even lighting, no frame.",
  back: "Full-length character reference seen from behind, back view, head-to-toe, back of the head, hairstyle and clothing from behind clearly visible, both feet flat on the ground, plain neutral grey background, no frame.",
  "3q": "Full-length character reference at a three-quarter angle, body turned about 45 degrees, head-to-toe, both feet flat on the ground, plain neutral grey background, soft even lighting, neutral expression, no frame.",
};

const VARIANTS = [
  ["A", "Форма → превью"],
  ["B", "Два столбца"],
  ["C", "Кадр крупно"],
];

function VariantSwitcher({ ctx }) {
  return (
    <div className="panel soft" style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 14px", marginBottom: 18, borderStyle: "dashed", borderColor: "var(--blue)", background: "var(--blue-tint)" }}>
      <span style={{ fontSize: 12.5, fontWeight: 700, color: "var(--blue-deep)" }}>🧪 Раскладка шага (на выбор):</span>
      <div className="btnrow" style={{ gap: 6 }}>
        {VARIANTS.map(([k, lbl]) => (
          <button key={k} className={"btn sm" + (ctx.variant === k ? " primary" : " ghost")} onClick={() => ctx.setVariant(k)}>{k} · {lbl}</button>
        ))}
      </div>
    </div>
  );
}

/* layer field block for a passport frame */
function PassportFields({ frame, step, face, body, outfit, setFace, setBody, setOutfit, id, stepKey }) {
  const faceRO = step >= 1;
  const bodyRO = step >= 2;
  const showBody = step >= 1;
  const outfitRO = step >= 2;
  const [check, setCheck] = useS2(null);

  // Real per-frame «Проверить с ИИ» (Promise -> AI button shimmers for the call).
  async function doCheck() {
    if (!id) { setCheck({ layer: frame.title, reasoning: "Проверка работает на сервере.", newPrompt: "" }); return; }
    try {
      const d = await window.api.check(id, stepKey);
      setCheck({ layer: frame.title, reasoning: d.justification || "Замечаний нет — можно генерировать.", newPrompt: d.new_prompt || "" });
    } catch (e) { setCheck({ layer: frame.title, reasoning: "Ошибка сети — попробуйте ещё раз.", newPrompt: "" }); }
  }
  function acceptCheck(np) {
    if (!faceRO) setFace(np); else if (showBody && !bodyRO) setBody(np);
    if (id) window.api.checkAccept(id, stepKey, np).catch(() => {});
  }
  return (
    <>
      <Field ru="Лицо" en="FACE"
        right={faceRO ? <span className="badge lock">🔒 заморожено</span> : <span className="badge ro">собрано из анкеты</span>}
        hint={!faceRO ? <DoDont yes="форма лица, нос, губы, глаза, волосы, кожа, шрамы" no="выражение/эмоцию (это слой «Эмоция»), позу и фон, одежду" /> : null}>
        <PromptField readOnly={faceRO} rows={2} layer="Лицо" value={face} onChange={setFace} />
      </Field>

      {showBody && (
        <Field ru="Тело" en="BODY"
          right={bodyRO ? <span className="badge lock">🔒 заморожено</span> : <span className="badge ro">собрано из анкеты</span>}
          hint={!bodyRO ? <DoDont yes="телосложение, рост (словами: «коренастый»), приметы на теле" no="одежду, лицо, позу или настроение" /> : null}>
          <PromptField readOnly={bodyRO} rows={2} layer="Тело" value={body} onChange={setBody} />
        </Field>
      )}

      <Field ru="Одежда" en="OUTFIT"
        right={outfitRO ? <span className="badge ro">по базовому наряду</span> : <span className="badge now">базовый наряд — вводим тут</span>}
        hint={!outfitRO ? <DoDont yes="одежду, материал, крой, цвет наряда" no="телосложение, лицо, позу/фон, эмоцию" /> : null}>
        <PromptField readOnly={outfitRO} rows={1} layer="Одежда" value={outfit} onChange={setOutfit} />
      </Field>

      {/* Одна общая проверка: разом проверяет все заполняемые поля этого кадра */}
      {(!faceRO || !bodyRO || !outfitRO) && (
        <div className="btnrow" style={{ marginTop: 14 }}>
          <AIButton onClick={doCheck}>Проверить поля с ИИ</AIButton>
          <span className="muted" style={{ fontSize: 12 }}>проверит лицо{showBody ? ", тело" : ""} и одежду разом</span>
        </div>
      )}

      {check && <AICheckDialog onClose={() => setCheck(null)} onAccept={acceptCheck} layerName={check.layer} reasoning={check.reasoning} newPrompt={check.newPrompt} />}
    </>
  );
}

function PassportActions({ ctx, step, onEdit, onApprove }) {
  const isLast = step >= FRAMES.length - 1;
  return (
    <div className="btnrow split">
      <button className="btn ghost" onClick={() => step > 0 ? ctx.setPStep(step - 1) : ctx.go("data")}>← Назад</button>
      <div className="btnrow">
        <AIButton onClick={onEdit}>Правка с ИИ</AIButton>
        <button className="btn approve" onClick={onApprove}>{isLast ? "Готово, дальше →" : "Утвердить кадр →"}</button>
      </div>
    </div>
  );
}

function ScreenPassport({ ctx }) {
  const step = ctx.pStep;
  const frame = FRAMES[step];
  const [pp, setPp] = useS2(null);
  const [face, setFace] = useS2("");
  const [body, setBody] = useS2("");
  const [outfit, setOutfit] = useS2("");
  const [gen, setGen] = useS2("empty"); // empty | gen | ready
  const [imgV, setImgV] = useS2(0);
  const [err, setErr] = useS2(null);
  const [edit, setEdit] = useS2(false);
  const [frameCheck, setFrameCheck] = useS2(null);
  const [comp, setComp] = useS2("");      // editable COMPOSITION (scene) for this frame
  const [compDflt, setCompDflt] = useS2(""); // registry default (for the reset button)

  const serverKey = "passport_" + frame.key;

  async function doCheckFrame() {
    if (!ctx.activeCharId) { setFrameCheck({ reasoning: "Проверка работает на сервере.", newPrompt: "" }); return; }
    try {
      const d = await window.api.check(ctx.activeCharId, serverKey);
      setFrameCheck({ reasoning: d.justification || "Замечаний нет — кадр в порядке.", newPrompt: d.new_prompt || "" });
    } catch (e) { setFrameCheck({ reasoning: "Ошибка сети — попробуйте ещё раз.", newPrompt: "" }); }
  }
  function acceptFrameCheck(np) {
    if (step === 0) setFace(np); else if (step === 1) setBody(np);
    if (ctx.activeCharId) window.api.checkAccept(ctx.activeCharId, serverKey, np).catch(() => {});
  }
  const SAMPLE = {
    face: "coarse face, broad nose, full lips, deep-set dark eyes, short rough dark hair, weathered tanned skin",
    body: "stocky, powerfully built, broad shoulders, faded tattoo on left forearm",
    outfit: "dark fur-trimmed leather tunic, wide leather belt",
  };

  // Load the passport phase from the backend (sample defaults with no backend).
  React.useEffect(() => {
    if (!ctx.activeCharId) {
      setFace(SAMPLE.face); setBody(SAMPLE.body); setOutfit(SAMPLE.outfit); setGen("ready");
      return;
    }
    let alive = true;
    window.api.getPassport(ctx.activeCharId)
      .then((d) => {
        if (!alive || !d || !d.passport) return;
        setPp(d.passport);
        // Resume on the frame the backend points at (earliest need_regen, else the
        // saved step) instead of always frame 1 — honours «откроем на том шаге, где
        // вы остановились» + the need_regen gate. Mount/char-keyed so it won't
        // fight in-phase chip/Back navigation.
        const i = FRAMES.findIndex((f) => "passport_" + f.key === d.passport.current_step);
        if (i >= 0 && i !== step) ctx.setPStep(i);
      })
      .catch(() => {});
    return () => { alive = false; };
  }, [ctx.activeCharId]);

  // Seed editable layer values + preview state from the active frame.
  React.useEffect(() => {
    if (!pp || !pp.frames[step]) return;
    const f = pp.frames[step];
    setFace(f.face || ""); setBody(f.body || ""); setOutfit(f.outfit || "");
    setComp(f.composition || FRAME_COMP[frame.key] || "");
    setCompDflt(f.scene_default || FRAME_COMP[frame.key] || "");
    setGen(f.has_image ? "ready" : "empty");
    setErr(null);
  }, [pp, step]);

  async function doGen() {
    if (window.__bumpCost) window.__bumpCost(0.04);
    if (!ctx.activeCharId) { setGen("gen"); await new Promise((r) => setTimeout(r, 1100)); setGen("ready"); return; }
    const regenerate = gen === "ready";
    setGen("gen"); setErr(null);
    try {
      const d = await window.api.passportGenerate(ctx.activeCharId, { step_key: serverKey, face, body, outfit, composition: comp, regenerate });
      if (d.passport) setPp(d.passport);
      setImgV((v) => v + 1);
      setGen(d.ok ? "ready" : "empty");
      if (!d.ok) setErr(d.error || "Не удалось сгенерировать кадр");
      window.setLastGen({
        section: "Паспорт", view: frame.title, model: "nano-banana", size: "1024×1536",
        layers: { style: (pp && pp.style) || "", face: face, body: step >= 1 ? body : "", outfit: outfit, composition: comp || FRAME_COMP[frame.key] },
        refs: frame.key === "face"
          ? [{ label: "стиль-реф", kind: "item" }]
          : (["profile", "back", "3q"].includes(frame.key)
            ? [{ label: "стиль-реф", kind: "item" }, { label: "паспорт: фас (FACE)", kind: "front-portrait" }, { label: "паспорт: рост (BODY)", kind: "front-full" }]
            : [{ label: "стиль-реф", kind: "item" }, { label: "паспорт: фас (FACE)", kind: "front-portrait" }]),
      });
    } catch (e) { setGen("empty"); setErr("Ошибка сети — попробуйте ещё раз"); }
  }

  async function approveAndNext() {
    const isLast = step >= FRAMES.length - 1;
    if (ctx.activeCharId && gen === "ready") {
      try {
        const d = await window.api.passportApprove(ctx.activeCharId, serverKey);
        if (d.passport) {
          setPp(d.passport);
          // need_regen gate: if a prior frame is now flagged for regeneration
          // (e.g. an accepted «Правка с ИИ»), pull the user back to it instead of
          // blindly advancing past a step that's waiting.
          const i = FRAMES.findIndex((f) => "passport_" + f.key === d.passport.current_step);
          if (!isLast && i >= 0 && i !== step + 1) { ctx.setPStep(i); window.scrollTo({ top: 0 }); return; }
        }
      } catch (e) { /* navigate anyway */ }
    }
    if (isLast) ctx.go("emotions"); else ctx.setPStep(step + 1);
    window.scrollTo({ top: 0 });
  }

  const imgSrc = ctx.activeCharId ? window.api.imageUrl(ctx.activeCharId, serverKey, imgV, 768) : null;
  const imgStyle = { maxWidth: "100%", maxHeight: ctx.variant === "C" ? 340 : 210, borderRadius: 6, objectFit: "contain", cursor: "zoom-in" };
  const fullImg = () => ctx.activeCharId && window.__lightbox(window.api.imageUrl(ctx.activeCharId, serverKey, imgV));

  const previewBlock = (
    <Panel className={ctx.variant === "C" ? "" : "soft"} marks={ctx.variant === "C"}>
      <div className="pv-title">Кадр {frame.n} · {frame.title}</div>
      <div className={"pv " + (gen === "ready" ? "ready" : gen === "gen" ? "gen" : "empty")} style={{ minHeight: ctx.variant === "C" ? 360 : 230 }}>
        {gen === "gen" ? (<><div className="pv-spin"></div><span className="pv-cap">генерация…</span></>)
          : gen === "ready" ? (
            <>
              <span className="pv-badge"><span className="badge done">✓ кадр готов</span></span>
              {imgSrc
                ? <img src={imgSrc} alt={frame.title} style={imgStyle} onClick={fullImg} onError={(e) => { e.target.style.display = "none"; }} />
                : <Figure kind={frame.fig} size={ctx.variant === "C" ? 130 : 92} />}
              <span className="pv-cap">{frame.title}</span>
              <span className="pv-sub">нейтральное лицо · серый фон</span>
            </>)
            : (<><Figure kind={frame.fig} size={92} /><span className="pv-cap">нажмите «Сгенерировать»</span></>)}
      </div>
      {err && <div className="notice red" style={{ marginTop: 10 }}><span className="ic">⚠️</span><span className="tx">{err}</span></div>}
      {pp && pp.frames[step] && pp.frames[step].warning &&
        <div className="notice" style={{ marginTop: 10 }}><span className="ic">⚠️</span><span className="tx">{pp.frames[step].warning}</span></div>}
      <div className="btnrow" style={{ marginTop: 12 }}>
        <button className="btn primary" onClick={doGen}>{gen === "ready" ? "↻ Перегенерировать" : "Сгенерировать кадр"}</button>
        <AIButton onClick={doCheckFrame}>Проверить кадр с ИИ</AIButton>
      </div>
      {gen === "ready" && <p className="muted" style={{ fontSize: 12, marginTop: 10, marginBottom: 0 }}>Не нравится — жмите «Перегенерировать». Прошлый вариант не пропадёт: он уйдёт в архив «отклонённые».</p>}
    </Panel>
  );

  const fieldsBlock = (
    <Panel key={"fields-" + frame.key} title="Описание кадра" icon="✍️" marks={ctx.variant !== "B"}
      collapsible={step >= 2} defaultCollapsed={step >= 2}
      badge={step >= 2 ? <span className="badge lock">🔒 всё заморожено</span> : null}>
      <PassportFields frame={frame} step={step} face={face} body={body} outfit={outfit} setFace={setFace} setBody={setBody} setOutfit={setOutfit} id={ctx.activeCharId} stepKey={serverKey} />
    </Panel>
  );

  const sceneBlock = (
    <AdvancedScene key={"scene-" + frame.key} value={comp} onChange={setComp} dflt={compDflt}
      note={<>Это поле уже настроено под этот паспортный кадр. Меняйте его <b>только</b> чтобы поправить <b>положение героя</b> и <b>ракурс камеры</b> ближе к нужному виду (например, если герой смотрит не туда). Фон, свет и пометки «без рамок» лучше не трогать. Изменение применится при следующей генерации кадра и сохранится для этого героя.</>} />
  );

  return (
    <div>
      <div className="eyebrow">Шаг 2 из 6 · Паспорт · кадр {frame.n} из 5</div>
      <h1 className="pagetitle">{frame.title}</h1>

      {/* substep chips */}
      <div className="btnrow" style={{ marginBottom: 18, gap: 7 }}>
        {FRAMES.map((f, i) => (
          <button key={f.key} className={"btn sm " + (i === step ? "primary" : i < step ? "approve" : "ghost")} onClick={() => ctx.setPStep(i)} style={{ minHeight: 32 }}>
            {i < step ? "✓ " : ""}{f.n}. {f.title}
          </button>
        ))}
      </div>

      <VariantSwitcher ctx={ctx} />

      <div className="notice">
        <span className="ic">⚠️</span>
        <span className="tx"><b>Это базовый кадр идентичности.</b> Важно, чтобы он точно соответствовал критерию ниже — от этих кадров зависит весь дальнейший набор. <br /><b>Критерий кадра:</b> {frame.crit}</span>
      </div>

      <Help title={"Что мы делаем на этом шаге?"}>
        <p>{frame.why}</p>
        <p>Заполните текстовые поля (или нажмите <b>✦ помощь ИИ</b>, чтобы их написала нейросеть),
          затем нажмите <b>«Сгенерировать кадр»</b>. Если кадр хороший — <b>«Утвердить»</b>.
          После утверждения слой замораживается 🔒 и дальше не меняется.</p>
        {step <= 1 && (
          <p><b>Про одежду.</b> Базовый наряд на этом шаге тоже можно менять. Но нейросеть не помнит
            одежду между кадрами, поэтому за согласованностью следите сами: наряд на <b>портрете</b> (кадр 1)
            и в <b>полный рост</b> (кадр 2) должен совпадать. Если одежда разъехалась — вернитесь к кадру 1,
            поправьте описание одежды, <b>перегенерируйте портрет</b>, а затем с <b>тем же</b> описанием
            генерируйте полный рост.</p>
        )}
      </Help>

      {/* layout variants */}
      {ctx.variant === "A" && (<>{fieldsBlock}{sceneBlock}{previewBlock}</>)}
      {ctx.variant === "B" && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 0.9fr", gap: 18, alignItems: "start" }}>
            <div>{fieldsBlock}</div>
            <div style={{ position: "sticky", top: 16 }}>{previewBlock}</div>
          </div>
          {sceneBlock}
        </>
      )}
      {ctx.variant === "C" && (<>{previewBlock}{sceneBlock}{fieldsBlock}</>)}

      <div style={{ marginTop: 22 }}>
        <PassportActions ctx={ctx} step={step} onEdit={() => setEdit(true)} onApprove={approveAndNext} />
      </div>

      {edit && <AIEditDialog id={ctx.activeCharId} onClose={() => setEdit(false)} />}
      {frameCheck && <AICheckDialog onClose={() => setFrameCheck(null)} onAccept={acceptFrameCheck} layerName={frame.title} reasoning={frameCheck.reasoning} newPrompt={frameCheck.newPrompt} />}
    </div>
  );
}

/* =========================================================
   EMOTIONS SCREEN
   ========================================================= */
const EMO_ROW = [
  { v: "neutral", ru: "спокойствие", fig: "front-portrait" },
  { v: "angry, furious", ru: "злость, ярость", fig: "front-portrait" },
  { v: "smiling warmly", ru: "тёплая улыбка", fig: "front-portrait" },
];

function EmotionCell({ item, id, onUpdate }) {
  const [st, setSt] = useS2(item.has_image ? "ready" : "empty");
  const [v, setV] = useS2(0);
  React.useEffect(() => { setSt(item.has_image ? "ready" : "empty"); }, [item.has_image]);
  async function gen() {
    if (window.__bumpCost) window.__bumpCost(0.04);
    if (!id) { setSt("gen"); await new Promise((r) => setTimeout(r, 1000)); setSt("ready"); return; }
    setSt("gen");
    try {
      const d = await window.api.emotionGenerate(id, item.index);
      setV((x) => x + 1);
      setSt(d.ok ? "ready" : "empty");
      onUpdate && d.emotions && onUpdate(d.emotions);
      window.setLastGen({
        section: "Эмоции", view: item.value, model: "nano-banana", size: "1024×1024",
        layers: { expression: item.value, composition: "front facing portrait, head and shoulders, plain neutral grey background, soft even lighting" },
        refs: [{ label: "стиль-реф", kind: "item" }, { label: "паспорт: фас (FACE)", kind: "front-portrait" }],
      });
    } catch (e) { setSt("empty"); }
  }
  async function archive() {
    if (id) {
      try { const d = await window.api.emotionDelete(id, item.index); onUpdate && d.emotions && onUpdate(d.emotions); } catch (e) { /* ignore */ }
    }
    setSt("empty");
  }
  const imgSrc = id && st === "ready" ? window.api.imageUrl(id, item.step_key, v, 320) : null;
  return (
    <div className="pv-col">
      <div className="pv-title">{item.value}</div>
      <div className={"pv " + (st === "ready" ? "ready" : st === "gen" ? "gen" : "empty")} style={{ minHeight: 150 }}>
        {st === "gen" ? (<><div className="pv-spin"></div><span className="pv-cap">генерация…</span></>)
          : st === "ready" ? (<><span className="pv-badge"><span className="badge done">✓</span></span>{imgSrc ? <img src={imgSrc} alt={item.value} onClick={() => id && window.__lightbox(window.api.imageUrl(id, item.step_key, v))} style={{ maxWidth: "100%", maxHeight: 130, borderRadius: 6, objectFit: "contain", cursor: "zoom-in" }} onError={(e) => { e.target.style.display = "none"; }} /> : <Figure kind="front-portrait" size={58} />}</>)
            : (<><Figure kind="front-portrait" size={58} /><span className="pv-sub">нет кадра</span></>)}
      </div>
      {st === "ready" ? (
        <div className="btnrow" style={{ flexWrap: "nowrap", gap: 6 }}>
          <button className="btn warn sm" onClick={archive} title="Отправить этот кадр в архив (rejected)" style={{ flex: "0 0 auto" }}>🗑 Удалить</button>
          <button className="btn sm" onClick={gen} style={{ flex: 1 }}>↻ Заново</button>
        </div>
      ) : (
        <button className="btn sm" onClick={gen} style={{ width: "100%" }}>Сгенерировать</button>
      )}
    </div>
  );
}

function ScreenEmotions({ ctx }) {
  const [emo, setEmo] = useS2(null);
  const [baseOn, setBaseOn] = useS2(true);
  const [baseVal, setBaseVal] = useS2("grim, brooding");
  const [baseSt, setBaseSt] = useS2("empty");
  const [baseV, setBaseV] = useS2(0);
  const [archived, setArchived] = useS2(0);

  React.useEffect(() => {
    if (!ctx.activeCharId) return;
    let alive = true;
    window.api.getEmotions(ctx.activeCharId).then((d) => {
      if (!alive || !d || !d.emotions) return;
      setEmo(d.emotions);
      setBaseOn(d.emotions.base.enabled);
      if (d.emotions.base.value) setBaseVal(d.emotions.base.value);
      setBaseSt(d.emotions.base.has_image ? "ready" : "empty");
    }).catch(() => {});
    return () => { alive = false; };
  }, [ctx.activeCharId]);

  async function genBase() {
    if (window.__bumpCost) window.__bumpCost(0.04);
    genBaseDebug();
    if (!ctx.activeCharId) { setBaseSt("gen"); await new Promise((r) => setTimeout(r, 1000)); setBaseSt("ready"); return; }
    setBaseSt("gen");
    try {
      const d = await window.api.emotionBase(ctx.activeCharId, baseVal);
      setBaseV((v) => v + 1);
      setBaseSt(d.ok ? "ready" : "empty");
      if (d.emotions) setEmo(d.emotions);
    } catch (e) { setBaseSt("empty"); }
  }

  async function genBaseDebug() {
    window.setLastGen({
      section: "Эмоция по умолчанию", view: baseVal, model: "nano-banana", size: "1024×1024",
      layers: { expression: baseVal, composition: "front facing portrait, head and shoulders, plain neutral grey background, soft even lighting" },
      refs: [{ label: "стиль-реф", kind: "item" }, { label: "паспорт: фас (FACE)", kind: "front-portrait" }],
    });
  }
  async function toggleEmotions(next) {
    if (!ctx.activeCharId) { setEmo((e) => Object.assign({}, e || {}, { enabled: next })); return; }
    try { const d = await window.api.emotionEnable(ctx.activeCharId, next); if (d.emotions) setEmo(d.emotions); } catch (e) { /* ignore */ }
  }
  // Persist the base-emotion on/off to the server (free, value-preserving), so
  // turning it off actually stops it contaminating downstream scenes + survives
  // reload — not just a local dim.
  async function toggleBase(next) {
    setBaseOn(next);
    if (!ctx.activeCharId) return;
    try { const d = await window.api.emotionBaseEnable(ctx.activeCharId, next); if (d.emotions) setBaseOn(d.emotions.base.enabled); } catch (e) { /* ignore */ }
  }
  const [baseCheck, setBaseCheck] = useS2(null);
  async function doCheckBase() {
    if (!ctx.activeCharId) { setBaseCheck({ reasoning: "Проверка работает на сервере.", newPrompt: "" }); return; }
    try {
      const d = await window.api.check(ctx.activeCharId, "base_emotion");
      setBaseCheck({ reasoning: d.justification || "Замечаний нет.", newPrompt: d.new_prompt || "" });
    } catch (e) { setBaseCheck({ reasoning: "Ошибка сети — попробуйте ещё раз.", newPrompt: "" }); }
  }

  const cells = emo
    ? emo.items
    : EMO_ROW.slice(1).map((e, i) => ({ index: i, value: e.v, step_key: e.v, has_image: false }));
  const emoEnabled = emo ? emo.enabled : true;
  const neutral = emo && emo.neutral;
  const neutralImg = ctx.activeCharId && neutral && neutral.has_image ? window.api.imageUrl(ctx.activeCharId, "passport_face", 0, 320) : null;
  const baseImg = ctx.activeCharId && baseSt === "ready" ? window.api.imageUrl(ctx.activeCharId, "base_emotion", baseV, 320) : null;

  return (
    <div>
      <div className="eyebrow">Шаг 3 из 6 · Эмоции · по желанию</div>
      <h1 className="pagetitle">Эмоции <span className="accent">{ctx.activeChar}</span></h1>
      <p className="kicker">Соберём эталоны мимики. Каждый кадр — крупный портрет: лицо одно и то же (его держит паспорт), меняется только выражение.</p>

      <Help title="Зачем отдельные кадры эмоций?">
        <p>Сильные эмоции (крик, широкая улыбка) нейросеть часто рисует плохо и «уводит» лицо.
          Поэтому делаем чистые эталоны злости и улыбки заранее — потом по ним легко добавлять эмоции в сценах.</p>
        <p>Это <b>необязательно</b>. Можно сгенерировать не все — кнопка «Готово» пропустит дальше даже с пустыми ячейками.</p>
      </Help>

      <Panel title="Три базовые эмоции" icon="🎭" badge={<span className="badge opt">по желанию</span>} actions={<Toggle on={emoEnabled} onToggle={toggleEmotions} />}>
        <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>Под каждой — своя кнопка. Перегенерируется только та эмоция, под которой нажали. Если блок выключен — эти кадры не нужны и не требуются для завершения.</p>
        <div style={{ opacity: emoEnabled ? 1 : 0.45, pointerEvents: emoEnabled ? "auto" : "none" }}>
          <div className="pv-grid" style={{ gridTemplateColumns: "repeat(3,1fr)" }}>
            <div className="pv-col">
              <div className="pv-title">neutral<br /><span style={{ fontWeight: 400, textTransform: "none", color: "var(--ink-2)", fontSize: 11 }}>спокойствие · из паспорта</span></div>
              <div className={"pv " + (neutralImg ? "ready" : "empty")} style={{ minHeight: 150 }}>
                {neutralImg
                  ? <><span className="pv-badge"><span className="badge done">✓</span></span><img src={neutralImg} alt="neutral" onClick={() => window.__lightbox(window.api.imageUrl(ctx.activeCharId, "passport_face", 0))} style={{ maxWidth: "100%", maxHeight: 130, borderRadius: 6, objectFit: "contain", cursor: "zoom-in" }} onError={(e) => { e.target.style.display = "none"; }} /></>
                  : <><Figure kind="front-portrait" size={58} /><span className="pv-sub">сделайте паспорт</span></>}
              </div>
              <p className="muted center" style={{ fontSize: 11.5, margin: "6px 0 0" }}>берётся с паспортного портрета</p>
            </div>
            {cells.map((it) => <EmotionCell key={it.value} item={it} id={ctx.activeCharId} onUpdate={(e) => { setEmo(e); setArchived((n) => n + 1); }} />)}
          </div>
          {archived > 0 && <p className="muted" style={{ fontSize: 12, marginTop: 12, marginBottom: 0 }}>🗑 Отправлено в архив за эту сессию: <b>{archived}</b> — лежат в папке <span className="mono">rejected/</span>.</p>}
        </div>
      </Panel>

      <AdvancedScene value="Front facing portrait, head and shoulders, plain neutral grey background, soft even lighting." note={<>Кадры эмоций — крупный <b>портрет</b> (голова и плечи), одна и та же сцена на все три. Меняйте это поле <b>только</b> чтобы поправить план или ракурс (например, если лицо слишком мелкое). Фон и свет лучше не трогать.</>} />

      <Panel title="Эмоция по умолчанию" icon="🎯" badge={<span className="badge opt">по желанию</span>} actions={<Toggle on={baseOn} onToggle={toggleBase} />}>
        <div style={{ opacity: baseOn ? 1 : 0.45, pointerEvents: baseOn ? "auto" : "none" }}>
          <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>«Обычное» выражение героя — будет подставляться во всех сценах вместо нейтрального.</p>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 170px", gap: 16, alignItems: "start" }}>
            <Field ru="Настроение героя" en="EXPRESSION" hint={<DoDont yes="короткое выражение по-английски: grim, smiling, furious" no="описание мимики прозой, позу, одежду или фон" />}>
              <PromptField value={baseVal} onChange={setBaseVal} rows={1} layer="Эмоция" />
              <div className="btnrow" style={{ marginTop: 10 }}>
                <button className="btn sm" onClick={genBase}>{baseSt === "ready" ? "↻ Заново" : "Сгенерировать"}</button>
                <AIButton small onClick={doCheckBase}>Проверить</AIButton>
              </div>
            </Field>
            <div className="pv-col">
              <div className="pv-title">превью</div>
              <div className={"pv " + (baseSt === "ready" ? "ready" : baseSt === "gen" ? "gen" : "empty")} style={{ minHeight: 130 }}>
                {baseSt === "gen" ? <div className="pv-spin"></div>
                  : baseImg ? <img src={baseImg} alt="база" onClick={() => window.__lightbox(window.api.imageUrl(ctx.activeCharId, "base_emotion", baseV))} style={{ maxWidth: "100%", maxHeight: 120, borderRadius: 6, objectFit: "contain", cursor: "zoom-in" }} onError={(e) => { e.target.style.display = "none"; }} />
                    : <Figure kind="front-portrait" size={54} />}
              </div>
            </div>
          </div>
        </div>
      </Panel>

      <div className="btnrow split" style={{ marginTop: 22 }}>
        <button className="btn ghost" onClick={() => ctx.go("passport")}>← Назад</button>
        <button className="btn go" onClick={() => ctx.go("outfit")}>Готово, дальше: наряды →</button>
      </div>

      {baseCheck && <AICheckDialog onClose={() => setBaseCheck(null)} layerName="Эмоция по умолчанию" reasoning={baseCheck.reasoning} newPrompt={baseCheck.newPrompt}
        onAccept={(np) => { setBaseVal(np); if (ctx.activeCharId) window.api.checkAccept(ctx.activeCharId, "base_emotion", np).catch(() => {}); }} />}
    </div>
  );
}

window.ScreenPassport = ScreenPassport;
window.ScreenEmotions = ScreenEmotions;
